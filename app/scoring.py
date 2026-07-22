"""매칭 스코어링 — 정형 필터 + 하위 점수 + 최종 스코어 + 매칭 근거.

final = w1·semantic + w2·engagement + w3·audience_fit   (w1+w2+w3 = 1)
코사인 유사도(-1~1)는 (sim+1)/2 로 0~1 정규화.
"""
import re

import numpy as np

from app.embeddings import embed_cached

DEFAULT_WEIGHTS = {"w1": 0.6, "w2": 0.2, "w3": 0.2}   # 매출 전환형 프리셋
PRESETS = {
    "conversion": {"w1": 0.6, "w2": 0.2, "w3": 0.2},  # 전환형: 콘텐츠 적합성↑
    "awareness":  {"w1": 0.3, "w2": 0.5, "w3": 0.2},  # 인지도형: 참여율↑
}


# ---------------- 텍스트 프로필 ----------------

def influencer_text(inf):
    return " ".join(filter(None, [
        inf["niche_category"], inf["comment_keywords"], inf["recent_captions"],
    ]))


def product_text(prod):
    return " ".join(filter(None, [
        prod["name"], prod["category"], prod["ingredients"],
        prod["efficacy_description"], prod["usage_scenario"],
    ]))


_TERM_STOP = {"도움", "주는", "먹는", "타먹", "관리", "필요", "종일", "하루"}


def product_terms(prod):
    """상품 텍스트에서 하이라이트용 핵심어 추출(중복 제거)."""
    text = " ".join(filter(None, [
        prod["name"], prod["ingredients"], prod["efficacy_description"], prod["usage_scenario"],
    ]))
    out = []
    for w in re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", text):
        if w not in out and w not in _TERM_STOP:
            out.append(w)
    return out[:20]


def influencer_phrases(inf):
    phrases = []
    for kw in (inf["comment_keywords"] or "").split(","):
        kw = kw.strip()
        if kw:
            phrases.append(kw)
    for c in re.split(r"[.!?\n·,]", inf["recent_captions"] or ""):
        c = c.strip()
        if len(c) >= 4:
            phrases.append(c)
    # 중복 제거, 순서 유지
    seen, out = set(), []
    for p in phrases:
        if p not in seen:
            seen.add(p); out.append(p)
    return out[:12]


# ---------------- 수치 유틸 ----------------

def cosine(a, b):
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def norm_cos(sim):
    return (sim + 1.0) / 2.0


def minmax(vals):
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-12:
        return [0.5 for _ in vals]
    return [(v - lo) / (hi - lo) for v in vals]


def _age_range(s):
    m = re.findall(r"\d+", s or "")
    if len(m) >= 2:
        return int(m[0]), int(m[1])
    return None


def _gender_ratio(s):
    out = {"F": 0.5, "M": 0.5}
    for part in re.findall(r"([FM])\s*(\d+)", (s or "").upper()):
        out[part[0]] = int(part[1]) / 100.0
    return out


def audience_fit(inf, prod):
    """상품 타겟 인구통계와 인플루언서 오디언스 겹침 (0~1)."""
    # 연령: 구간 IoU
    age = 0.5
    ir, pr = _age_range(inf["audience_age_group"]), _age_range(prod["target_age_group"])
    if ir and pr:
        lo, hi = max(ir[0], pr[0]), min(ir[1], pr[1])
        inter = max(0, hi - lo)
        union = max(ir[1], pr[1]) - min(ir[0], pr[0])
        age = inter / union if union else 0.0
    # 성별
    tg = (prod["target_gender"] or "A").upper()[:1]
    if tg == "A":
        gender = 1.0
    else:
        gender = _gender_ratio(inf["audience_gender_ratio"]).get(tg, 0.5)
    return 0.5 * age + 0.5 * gender


def hard_filter(inf, prod):
    """(excluded, reasons) — 경쟁 협찬 충돌/오디언스 명백 불일치는 제외."""
    reasons = []
    excluded = False
    comps = {c.strip() for c in (prod["competitor_brands"] or "").split(",") if c.strip()}
    sponsored = {c.strip() for c in (inf["recent_sponsor_brands"] or "").split(",") if c.strip()}
    conflict = comps & sponsored
    if conflict:
        excluded = True
        reasons.append(f"경쟁 브랜드 협찬 이력({', '.join(sorted(conflict))})")
    if audience_fit(inf, prod) < 0.15:
        excluded = True
        reasons.append("오디언스 인구통계 불일치")
    return excluded, reasons


# ---------------- 매칭 ----------------

def match(product_id, conn, backend, weights=None, use_semantic=True):
    weights = weights or DEFAULT_WEIGHTS
    prod = conn.execute("SELECT * FROM products WHERE product_id=?", (product_id,)).fetchone()
    infs = conn.execute("SELECT * FROM influencers").fetchall()

    ptext = product_text(prod)
    itexts = [influencer_text(i) for i in infs]

    # 근거용 구(phrase)까지 한 번에 임베딩(캐시)
    all_phrases = []
    phrase_map = {}
    for i in infs:
        ph = influencer_phrases(i)
        phrase_map[i["influencer_id"]] = ph
        all_phrases += ph
    to_embed = [ptext] + itexts + list(dict.fromkeys(all_phrases))
    vecs = embed_cached(backend, to_embed, conn)
    pvec = vecs[0]
    ivecs = vecs[1:1 + len(infs)]
    phrase_vecs = dict(zip(dict.fromkeys(all_phrases), vecs[1 + len(infs):]))

    sems = [norm_cos(cosine(pvec, iv)) for iv in ivecs]
    eng = minmax([(i["engagement_rate"] or 0) for i in infs])

    rows = []
    for idx, inf in enumerate(infs):
        excluded, freasons = hard_filter(inf, prod)
        aud = audience_fit(inf, prod)
        semantic = sems[idx]
        engagement = eng[idx]
        if use_semantic:
            final = (weights["w1"] * semantic + weights["w2"] * engagement
                     + weights["w3"] * aud)
        else:
            # 정형 필터만(기존 툴 방식): 의미 제외, 나머지 재정규화
            wsum = weights["w2"] + weights["w3"]
            final = (weights["w2"] * engagement + weights["w3"] * aud) / wsum if wsum else 0.0

        # 매칭 근거: 인플루언서 구 중 상품과 유사도 상위 3 (문구 + 유사도 점수)
        reasons = []
        if use_semantic:
            scored = [(p, norm_cos(cosine(pvec, phrase_vecs[p]))) for p in phrase_map[inf["influencer_id"]]]
            scored.sort(key=lambda x: x[1], reverse=True)
            reasons = [{"text": p, "score": round(s, 3)} for p, s in scored[:3]]

        rows.append(dict(
            influencer_id=inf["influencer_id"], name=inf["name"], handle=inf["handle"],
            tier=inf["tier"], niche_category=inf["niche_category"],
            follower_count=inf["follower_count"], engagement_rate=inf["engagement_rate"],
            semantic=round(semantic, 4), engagement=round(engagement, 4),
            audience_fit=round(aud, 4), final=round(final, 4),
            excluded=excluded, filter_reasons=freasons, reasons=reasons,
        ))

    rows.sort(key=lambda r: (not r["excluded"], r["final"]), reverse=True)
    return dict(product=dict(prod), product_terms=product_terms(prod),
                rows=rows, backend=backend.name, weights=weights)
