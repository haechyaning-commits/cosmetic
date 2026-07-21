"""샘플 데이터 생성기.

실데이터 확보 전 대시보드를 검증하기 위한 시드.
각 인플루언서가 '서로 다른 이탈 패턴'을 갖도록 설계해서, 대시보드가
인플루언서 간 상대 성과와 이탈 지점 차이를 실제로 드러내는지 확인한다.
"""
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db import get_conn, init_db, FUNNEL_STAGES  # noqa: E402

random.seed(42)
BASE_DATE = datetime(2026, 6, 1)


def tier_of(followers):
    if followers >= 500_000:
        return "mega"
    if followers >= 50_000:
        return "mid"
    return "micro"


# (name, handle, followers, category)
INFLUENCERS = [
    ("김서연", "seoyeon.skin", 32_000, "스킨케어"),      # micro, 우수 전환
    ("이하늘", "haneul_beauty", 88_000, "메이크업"),      # mid, 랜딩 이탈(관심 부족)
    ("박지수", "jisoo.glow", 41_000, "스킨케어"),         # micro, 리뷰/장바구니 이탈(신뢰도)
    ("최유진", "yujin.daily", 620_000, "라이프스타일"),   # mega, 클릭多 전환低(과다노출)
    ("정민아", "mina_shorts", 150_000, "메이크업"),       # mid, 쇼츠=쿠폰전용
    ("한소희", "sohee.care", 26_000, "스킨케어"),         # micro, 결제 이탈(가격)
]

# (name, price, channel, bundle)
PRODUCTS = [
    ("수분 앰플 30ml", 28_000, "자사몰", "본품+미니어처"),
    ("톤업 선크림 50ml", 22_000, "자사몰", "본품 단품"),
    ("립 틴트 세트", 19_000, "자사몰", "3종 구성"),
]

# 인플루언서별 퍼널 프로파일: 단계별 '통과율'(전 단계 대비)
# platform 이 쇼츠면 링크가 없으므로 쿠폰 전용(클릭 트래킹 불가) 처리.
# (clicks, [landing, cart, checkout, purchase] 통과율, platform, tracking_type)
PROFILES = [
    dict(idx=0, clicks=800, rates=[0.75, 0.55, 0.70, 0.72], platform="ig_story", tracking="both"),   # 우수
    dict(idx=1, clicks=1400, rates=[0.30, 0.45, 0.60, 0.55], platform="ig_story", tracking="both"),  # 랜딩 이탈
    dict(idx=2, clicks=650, rates=[0.68, 0.28, 0.55, 0.60], platform="yt_long", tracking="both"),    # 장바구니 이탈
    dict(idx=3, clicks=5200, rates=[0.55, 0.32, 0.40, 0.25], platform="ig_story", tracking="both"),  # 과다노출
    dict(idx=4, clicks=0, rates=None, platform="yt_shorts", tracking="coupon"),                       # 쿠폰 전용
    dict(idx=5, clicks=520, rates=[0.70, 0.60, 0.30, 0.65], platform="ig_story", tracking="both"),   # 결제 이탈
]

COUPON_CONV = {  # 쿠폰 전용 콘텐츠의 대략적 구매 건수(지연 전환 포함)
    4: 210,
}


def brand_code(i):
    return f"COS-{INFLUENCERS[i][1][:4].upper()}-{random.randint(1000,9999)}"


def main():
    if os.path.exists(os.environ.get("COSMETIC_DB", os.path.join(os.path.dirname(__file__), "..", "cosmetic.db"))):
        os.remove(os.path.join(os.path.dirname(__file__), "..", "cosmetic.db"))
    init_db()
    conn = get_conn()
    cur = conn.cursor()

    for i, (name, handle, foll, cat) in enumerate(INFLUENCERS, start=1):
        cur.execute(
            "INSERT INTO influencers(influencer_id,name,handle,follower_count,tier,category) VALUES (?,?,?,?,?,?)",
            (i, name, handle, foll, tier_of(foll), cat),
        )
    for j, (pname, price, channel, bundle) in enumerate(PRODUCTS, start=1):
        cur.execute(
            "INSERT INTO products(product_id,name,price,channel,bundle_option) VALUES (?,?,?,?,?)",
            (j, pname, price, channel, bundle),
        )

    event_id = 1
    order_id = 1
    session_seq = 1

    for prof in PROFILES:
        i = prof["idx"]
        influencer_id = i + 1
        product_id = (i % len(PRODUCTS)) + 1
        product = PRODUCTS[product_id - 1]
        content_id = i + 1
        coupon = brand_code(i)
        upload = (BASE_DATE + timedelta(days=i)).strftime("%Y-%m-%d")
        cur.execute(
            """INSERT INTO contents(content_id,influencer_id,product_id,platform,tracking_type,
               coupon_code,landing_url,utm_content,reported_views,upload_date)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                content_id, influencer_id, product_id, prof["platform"], prof["tracking"],
                coupon,
                f"https://shop.example.com/p/{product_id}?utm_source=influencer&utm_medium={prof['platform']}&utm_campaign=seeding&utm_content=c{content_id}",
                f"c{content_id}",
                prof["clicks"] * random.randint(15, 40) if prof["clicks"] else random.randint(80_000, 300_000),
                upload,
            ),
        )

        # 링크 트랙: 클릭부터 단계별 세션 감소 이벤트 생성
        if prof["clicks"] and prof["rates"]:
            n = prof["clicks"]
            stage_counts = {"click": n}
            for stage, rate in zip(FUNNEL_STAGES[1:], prof["rates"]):
                n = int(n * rate)
                stage_counts[stage] = n

            purchases = stage_counts["purchase"]
            # 세션별로 도달 최고 단계를 정해 이벤트를 채운다
            reached = []
            for stage in FUNNEL_STAGES:
                reached += [stage] * (stage_counts[stage] - stage_counts.get(_next(stage), 0))

            for k in range(stage_counts["click"]):
                sid = f"s{session_seq}"
                session_seq += 1
                top = reached[k] if k < len(reached) else "click"
                ts = BASE_DATE + timedelta(days=i, minutes=k)
                oid = None
                if top == "purchase":
                    # 구매 세션은 주문 생성 + 쿠폰/세션 귀속
                    amount = product[1] - (2000 if random.random() < 0.6 else 0)
                    use_coupon = coupon if random.random() < 0.8 else None
                    cur.execute(
                        "INSERT INTO orders(order_id,session_id,product_id,amount,coupon_code,ts) VALUES (?,?,?,?,?,?)",
                        (order_id, sid, product_id, amount, use_coupon, ts.strftime("%Y-%m-%d %H:%M:%S")),
                    )
                    oid = order_id
                    order_id += 1
                # click..top 까지 단계 이벤트를 순서대로 남긴다
                for stage in FUNNEL_STAGES[: FUNNEL_STAGES.index(top) + 1]:
                    cur.execute(
                        "INSERT INTO events(event_id,content_id,session_id,event_type,order_id,ts) VALUES (?,?,?,?,?,?)",
                        (event_id, content_id, sid, stage,
                         oid if stage == "purchase" else None,
                         (ts + timedelta(seconds=FUNNEL_STAGES.index(stage) * 20)).strftime("%Y-%m-%d %H:%M:%S")),
                    )
                    event_id += 1

        # 쿠폰 전용 콘텐츠: 클릭/중간단계 없이 주문만(지연 전환)
        if i in COUPON_CONV:
            for _ in range(COUPON_CONV[i]):
                ts = BASE_DATE + timedelta(days=i + random.randint(0, 10), minutes=random.randint(0, 1000))
                amount = product[1] - (2000 if random.random() < 0.7 else 0)
                cur.execute(
                    "INSERT INTO orders(order_id,session_id,product_id,amount,coupon_code,ts) VALUES (?,?,?,?,?,?)",
                    (order_id, None, product_id, amount, coupon, ts.strftime("%Y-%m-%d %H:%M:%S")),
                )
                order_id += 1

    conn.commit()
    counts = {
        t: cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("influencers", "products", "contents", "events", "orders")
    }
    conn.close()
    print("seeded:", counts)


def _next(stage):
    idx = FUNNEL_STAGES.index(stage)
    return FUNNEL_STAGES[idx + 1] if idx + 1 < len(FUNNEL_STAGES) else None


if __name__ == "__main__":
    main()
