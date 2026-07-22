"""FastAPI 앱 — 인플루언서-제품 매칭 스코어링 대시보드(서버렌더).

상품을 고르면 정형 필터 → 의미 매칭으로 인플루언서를 순위화하고,
가중치 슬라이더/프리셋과 '정형만 vs 의미추가' 토글은 클라이언트에서
선계산된 하위 점수로 즉시 재정렬한다.
"""
import json
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import get_conn, init_db
from app.embeddings import make_backend
from app import scoring

BASE = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="인플루언서-제품 매칭")
app.mount("/static", StaticFiles(directory=os.path.join(BASE, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))


@app.on_event("startup")
def _startup():
    init_db()


def won(n):
    return f"{n:,.0f}" if n is not None else "—"


templates.env.filters["won"] = won


@app.get("/", response_class=HTMLResponse)
def home():
    conn = get_conn()
    first = conn.execute("SELECT product_id FROM products ORDER BY product_id LIMIT 1").fetchone()
    conn.close()
    if not first:
        return HTMLResponse("<p>상품 데이터가 없습니다. scripts/seed_matching.py 를 실행하세요.</p>")
    return RedirectResponse(url=f"/product/{first['product_id']}")


@app.get("/product/{product_id}", response_class=HTMLResponse)
def product_view(request: Request, product_id: int):
    conn = get_conn()
    backend = make_backend()
    products = [dict(r) for r in conn.execute(
        "SELECT product_id, name, category FROM products ORDER BY product_id")]
    result = scoring.match(product_id, conn, backend, weights=scoring.DEFAULT_WEIGHTS)
    conn.close()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "products": products,
            "product": result["product"],
            "rows_json": json.dumps(result["rows"], ensure_ascii=False),
            "presets_json": json.dumps(scoring.PRESETS),
            "backend": result["backend"],
            "weights": scoring.DEFAULT_WEIGHTS,
        },
    )
