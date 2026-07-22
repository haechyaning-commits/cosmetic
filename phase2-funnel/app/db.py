"""DB 연결 및 스키마.

MVP는 SQLite로 시작하되, 스키마는 PostgreSQL로 무리 없이 옮길 수 있게
표준 SQL 위주로 작성한다(자동증가 PK와 타입만 이관 시 조정).
"""
import os
import sqlite3

DB_PATH = os.environ.get("COSMETIC_DB", os.path.join(os.path.dirname(__file__), "..", "cosmetic.db"))

# 퍼널 단계 순서 (링크 트랙). 대시보드/집계에서 공통 참조.
FUNNEL_STAGES = ["click", "landing", "cart", "checkout", "purchase"]
STAGE_LABELS = {
    "click": "클릭",
    "landing": "랜딩",
    "cart": "장바구니",
    "checkout": "결제시도",
    "purchase": "구매",
}


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS influencers (
    influencer_id   INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    handle          TEXT,
    follower_count  INTEGER,
    tier            TEXT CHECK (tier IN ('mega','mid','micro')),
    category        TEXT
);

CREATE TABLE IF NOT EXISTS products (
    product_id      INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    price           INTEGER,
    channel         TEXT,           -- 자사몰/스마트스토어/올리브영/쿠팡
    bundle_option   TEXT
);

CREATE TABLE IF NOT EXISTS contents (
    content_id      INTEGER PRIMARY KEY,
    influencer_id   INTEGER NOT NULL REFERENCES influencers(influencer_id),
    product_id      INTEGER NOT NULL REFERENCES products(product_id),
    platform        TEXT,           -- ig_reels/ig_story/yt_long/yt_shorts
    tracking_type   TEXT CHECK (tracking_type IN ('coupon','link','both')),
    coupon_code     TEXT UNIQUE,
    landing_url     TEXT,
    utm_content     TEXT,
    reported_views  INTEGER,
    upload_date     TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    order_id        INTEGER PRIMARY KEY,
    session_id      TEXT,
    product_id      INTEGER REFERENCES products(product_id),
    amount          INTEGER,
    coupon_code     TEXT,
    ts              TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_id        INTEGER PRIMARY KEY,
    content_id      INTEGER NOT NULL REFERENCES contents(content_id),
    session_id      TEXT,
    event_type      TEXT CHECK (event_type IN ('impression','click','landing','cart','checkout','purchase')),
    order_id        INTEGER REFERENCES orders(order_id),
    ts              TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_content ON events(content_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_orders_coupon ON orders(coupon_code);
CREATE INDEX IF NOT EXISTS idx_contents_influencer ON contents(influencer_id);
"""


def init_db(conn=None):
    own = conn is None
    conn = conn or get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    if own:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"initialized schema at {os.path.abspath(DB_PATH)}")
