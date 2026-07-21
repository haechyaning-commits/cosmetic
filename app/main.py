"""FastAPI 앱 — 발급기 + 리다이렉트 로깅 + 퍼널 대시보드(서버렌더).

MVP: 대시보드가 주 산출물. 발급/리다이렉트 엔드포인트는 데이터 수집의
시작점으로 함께 제공한다.
"""
import os
import random
import string
import uuid

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import get_conn, init_db, FUNNEL_STAGES
from app import metrics

BASE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="시딩 퍼널 분석")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))


@app.on_event("startup")
def _startup():
    init_db()


def won(n):
    return f"{n:,.0f}" if n is not None else "—"


def pct(x, digits=1):
    return f"{x*100:.{digits}f}%" if x is not None else "N/A"


templates.env.filters["won"] = won
templates.env.filters["pct"] = pct


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    summary = metrics.influencer_summary()
    totals = metrics.overall_totals()
    max_cvr = max((s["cvr"] or 0) for s in summary) or 1
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"summary": summary, "totals": totals, "max_cvr": max_cvr},
    )


@app.get("/influencer/{influencer_id}", response_class=HTMLResponse)
def influencer_detail(request: Request, influencer_id: int):
    conn = get_conn()
    inf = conn.execute(
        "SELECT * FROM influencers WHERE influencer_id=?", (influencer_id,)
    ).fetchone()
    conn.close()
    contents = metrics.content_funnel(influencer_id)
    # 각 콘텐츠에서 최대 이탈 단계 표시
    for c in contents:
        worst = None
        for st in c["steps"]:
            if st["drop"] is not None and (worst is None or st["drop"] > worst["drop"]):
                worst = st
        c["worst_stage"] = worst["stage"] if worst else None
        first = c["steps"][0]["count"] if c["steps"] else 0
        for st in c["steps"]:
            st["width"] = (st["count"] / first * 100) if first else 0
            st["is_worst"] = worst is not None and st["stage"] == worst["stage"]
    return templates.TemplateResponse(
        request,
        "influencer.html",
        {"inf": inf, "contents": contents},
    )


# ---------- 발급기 & 리다이렉트 (데이터 수집 진입점) ----------

def _new_coupon(conn, influencer_handle):
    for _ in range(20):
        code = f"COS-{influencer_handle[:4].upper()}-{''.join(random.choices(string.digits, k=4))}"
        exists = conn.execute("SELECT 1 FROM contents WHERE coupon_code=?", (code,)).fetchone()
        if not exists:
            return code
    raise RuntimeError("쿠폰코드 채번 실패")


@app.post("/api/issue")
def issue(influencer_id: int = Form(...), product_id: int = Form(...),
          platform: str = Form(...), tracking_type: str = Form("both")):
    """콘텐츠 1건에 대해 쿠폰코드 + UTM 링크를 발급."""
    conn = get_conn()
    inf = conn.execute("SELECT handle FROM influencers WHERE influencer_id=?", (influencer_id,)).fetchone()
    if not inf:
        conn.close()
        return {"error": "influencer not found"}
    content_id = (conn.execute("SELECT COALESCE(MAX(content_id),0)+1 FROM contents").fetchone()[0])
    coupon = _new_coupon(conn, inf["handle"]) if tracking_type in ("coupon", "both") else None
    utm = f"c{content_id}"
    landing = (
        f"https://shop.example.com/p/{product_id}?utm_source=influencer"
        f"&utm_medium={platform}&utm_campaign=seeding&utm_content={utm}"
    ) if tracking_type in ("link", "both") else None
    conn.execute(
        """INSERT INTO contents(content_id,influencer_id,product_id,platform,tracking_type,
           coupon_code,landing_url,utm_content) VALUES (?,?,?,?,?,?,?,?)""",
        (content_id, influencer_id, product_id, platform, tracking_type, coupon, landing, utm),
    )
    conn.commit()
    conn.close()
    return {
        "content_id": content_id,
        "coupon_code": coupon,
        "redirect_url": f"/r/{content_id}" if landing else None,
        "landing_url": landing,
    }


@app.get("/r/{content_id}")
def redirect_and_log(content_id: int):
    """리다이렉트하며 클릭 이벤트 로깅. session_id 발급 후 랜딩으로 302."""
    conn = get_conn()
    c = conn.execute("SELECT landing_url FROM contents WHERE content_id=?", (content_id,)).fetchone()
    if not c or not c["landing_url"]:
        conn.close()
        return {"error": "no landing url"}
    sid = uuid.uuid4().hex[:16]
    conn.execute(
        "INSERT INTO events(content_id,session_id,event_type,ts) VALUES (?,?,?,datetime('now'))",
        (content_id, sid, "click"),
    )
    conn.commit()
    conn.close()
    resp = RedirectResponse(url=c["landing_url"], status_code=302)
    resp.set_cookie("sid", sid, max_age=60 * 60 * 24 * 7)
    return resp
