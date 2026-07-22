"""집계 로직 — 어트리뷰션 규칙과 퍼널 지표.

어트리뷰션(주문 → 콘텐츠 귀속):
  1순위) 쿠폰 매칭: orders.coupon_code == contents.coupon_code
  2순위) 세션 매칭: 쿠폰이 없는 주문은 그 세션의 purchase 이벤트 content_id 로 귀속
둘 다 없으면 미귀속(집계 제외).
"""
from app.db import get_conn, FUNNEL_STAGES, STAGE_LABELS


def _attribute_orders(conn):
    """order_id -> content_id 매핑을 규칙에 따라 계산."""
    mapping = {}
    # 1순위: 쿠폰 매칭
    for row in conn.execute(
        """SELECT o.order_id, c.content_id
           FROM orders o JOIN contents c ON o.coupon_code = c.coupon_code
           WHERE o.coupon_code IS NOT NULL"""
    ):
        mapping[row["order_id"]] = row["content_id"]
    # 2순위: 세션 매칭(쿠폰 미귀속 주문만)
    for row in conn.execute(
        """SELECT o.order_id, e.content_id
           FROM orders o
           JOIN events e ON e.order_id = o.order_id AND e.event_type = 'purchase'"""
    ):
        mapping.setdefault(row["order_id"], row["content_id"])
    return mapping


def _clicks_by_content(conn):
    rows = conn.execute(
        "SELECT content_id, COUNT(*) n FROM events WHERE event_type='click' GROUP BY content_id"
    )
    return {r["content_id"]: r["n"] for r in rows}


def influencer_summary(conn=None):
    """인플루언서별 비교 지표(대시보드 메인)."""
    own = conn is None
    conn = conn or get_conn()
    try:
        order_to_content = _attribute_orders(conn)
        clicks_by_content = _clicks_by_content(conn)

        content_meta = {
            r["content_id"]: r
            for r in conn.execute(
                "SELECT content_id, influencer_id, tracking_type FROM contents"
            )
        }
        order_rows = {r["order_id"]: r for r in conn.execute("SELECT order_id, amount, coupon_code FROM orders")}

        agg = {}
        for r in conn.execute(
            "SELECT influencer_id, name, tier, category, follower_count FROM influencers"
        ):
            agg[r["influencer_id"]] = dict(
                influencer_id=r["influencer_id"], name=r["name"], tier=r["tier"],
                category=r["category"], follower_count=r["follower_count"],
                clicks=0, purchases=0, revenue=0, coupon_orders=0,
            )

        for cid, n in clicks_by_content.items():
            inf = content_meta[cid]["influencer_id"]
            agg[inf]["clicks"] += n

        for oid, cid in order_to_content.items():
            inf = content_meta[cid]["influencer_id"]
            o = order_rows[oid]
            agg[inf]["purchases"] += 1
            agg[inf]["revenue"] += o["amount"] or 0
            if o["coupon_code"]:
                agg[inf]["coupon_orders"] += 1

        out = []
        for a in agg.values():
            a["cvr"] = (a["purchases"] / a["clicks"]) if a["clicks"] else None
            a["aov"] = (a["revenue"] / a["purchases"]) if a["purchases"] else None
            out.append(a)
        out.sort(key=lambda x: (x["cvr"] is not None, x["cvr"] or 0), reverse=True)
        return out
    finally:
        if own:
            conn.close()


def content_funnel(influencer_id, conn=None):
    """특정 인플루언서의 콘텐츠별 퍼널 단계 카운트."""
    own = conn is None
    conn = conn or get_conn()
    try:
        order_to_content = _attribute_orders(conn)
        rows = conn.execute(
            """SELECT c.content_id, c.platform, c.tracking_type, c.coupon_code,
                      p.name AS product_name
               FROM contents c JOIN products p ON c.product_id = p.product_id
               WHERE c.influencer_id = ?""",
            (influencer_id,),
        ).fetchall()

        result = []
        for c in rows:
            cid = c["content_id"]
            stage_counts = {}
            for s in FUNNEL_STAGES:
                stage_counts[s] = conn.execute(
                    "SELECT COUNT(DISTINCT session_id) FROM events WHERE content_id=? AND event_type=?",
                    (cid, s),
                ).fetchone()[0]

            # 쿠폰 전용(링크 트랙 없음): 귀속 주문·매출 요약만
            coupon_orders = [oid for oid, mapped in order_to_content.items() if mapped == cid]
            revenue = 0
            for oid in coupon_orders:
                revenue += conn.execute("SELECT amount FROM orders WHERE order_id=?", (oid,)).fetchone()[0] or 0

            has_link = c["tracking_type"] in ("link", "both") and stage_counts["click"] > 0
            steps = []
            if has_link:
                prev = None
                for s in FUNNEL_STAGES:
                    n = stage_counts[s]
                    drop = None if prev is None else (1 - n / prev if prev else 0)
                    steps.append(dict(stage=s, label=STAGE_LABELS[s], count=n, drop=drop))
                    prev = n

            result.append(dict(
                content_id=cid,
                platform=c["platform"],
                tracking_type=c["tracking_type"],
                product_name=c["product_name"],
                coupon_code=c["coupon_code"],
                has_link=has_link,
                steps=steps,
                orders=len(coupon_orders),
                revenue=revenue,
            ))
        return result
    finally:
        if own:
            conn.close()


def overall_totals(conn=None):
    own = conn is None
    conn = conn or get_conn()
    try:
        summary = influencer_summary(conn)
        clicks = sum(s["clicks"] for s in summary)
        purchases = sum(s["purchases"] for s in summary)
        revenue = sum(s["revenue"] for s in summary)
        return dict(
            influencers=len(summary),
            clicks=clicks,
            purchases=purchases,
            revenue=revenue,
            cvr=(purchases / clicks) if clicks else None,
        )
    finally:
        if own:
            conn.close()
