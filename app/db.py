"""DB 연결 및 스키마 (매칭 스코어링).

SQLite로 시작하되 PostgreSQL 이관을 고려한 표준 SQL 위주.
"""
import os
import sqlite3

DB_PATH = os.environ.get("MATCH_DB", os.path.join(os.path.dirname(__file__), "..", "matching.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS influencers (
    influencer_id       INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    handle              TEXT,
    follower_count      INTEGER,
    tier                TEXT,               -- nano/micro/mid/mega
    niche_category      TEXT,               -- 라벨상 니치 (건강/스킨케어/메이크업 ...)
    recent_captions     TEXT,               -- 최근 콘텐츠 캡션 모음
    comment_keywords    TEXT,               -- 댓글에서 반복되는 관심사 키워드
    engagement_rate     REAL,               -- 0~1
    avg_sponsorship_price INTEGER,          -- 평균 협찬 단가(KRW)
    audience_age_group  TEXT,               -- 예: "20-34"
    audience_gender_ratio TEXT,             -- 예: "F72/M28"
    recent_sponsor_brands TEXT              -- 최근 협찬 브랜드(콤마구분)
);

CREATE TABLE IF NOT EXISTS products (
    product_id          INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    category            TEXT,
    price               INTEGER,
    ingredients         TEXT,
    efficacy_description TEXT,
    usage_scenario      TEXT,
    target_age_group    TEXT,               -- 예: "20-39"
    target_gender       TEXT,               -- F/M/A(all)
    competitor_brands   TEXT                -- 경쟁 브랜드(콤마구분)
);

CREATE TABLE IF NOT EXISTS match_results (
    match_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    influencer_id       INTEGER REFERENCES influencers(influencer_id),
    product_id          INTEGER REFERENCES products(product_id),
    semantic_score      REAL,
    engagement_score    REAL,
    audience_fit_score  REAL,
    final_score         REAL,
    created_at          TEXT
);

CREATE TABLE IF NOT EXISTS embedding_cache (
    backend             TEXT,
    text_hash           TEXT,
    vector              TEXT,               -- JSON 직렬화된 float 리스트
    PRIMARY KEY (backend, text_hash)
);
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
    print(f"initialized matching schema at {os.path.abspath(DB_PATH)}")
