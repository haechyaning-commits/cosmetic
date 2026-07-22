# 인플루언서-제품 매칭 스코어링 — MVP 스펙

> 기획서(`docs/matching-기획서.md`)를 구현 착수 가능한 스펙으로 정제.
> 상태: MVP v1 · DB: SQLite(시작, PostgreSQL 호환) · 임베딩: 교체형 백엔드(API 키 제공)

## 0. TL;DR
상품 하나를 고르면 → **정형 필터로 후보를 거른 뒤 → 의미(임베딩) 유사도로 순위화**하여 상위 인플루언서를 **매칭 근거와 함께** 랭킹. 가중치 슬라이더로 캠페인 목표(전환형/인지도형)에 맞춰 재정렬.

## 1. 스코어 구성

세 하위 점수(0~1)를 가중 합산.

| 하위 점수 | 정의 | 계산 |
|---|---|---|
| `semantic` | 콘텐츠 의미 적합성 (핵심 차별점) | 인플루언서 텍스트 임베딩 ↔ 상품 텍스트 임베딩 코사인 유사도 |
| `engagement` | 참여율 | 후보군 내 `engagement_rate` min-max 정규화 |
| `audience_fit` | 오디언스 적합성 | 상품 타겟 연령·성별과 인플루언서 오디언스 겹침(0~1) |

```
final = w1·semantic + w2·engagement + w3·audience_fit   (w1+w2+w3 = 1)
```
- 기본 가중치 `w1=0.6, w2=0.2, w3=0.2` (매출 전환형 프리셋). 인지도형 프리셋 `0.3/0.5/0.2`.
- 코사인 유사도(-1~1)는 `(sim+1)/2`로 0~1 정규화해 합산.

## 2. 정형 필터 (Hard Filter)
후보를 거르는 1단계. 통과한 후보만 의미 매칭으로 순위화.

| 필터 | 규칙(MVP) | 기본값 |
|---|---|---|
| 팔로워 티어 | 캠페인 목표 티어 집합에 포함되는지 | 전체 허용 |
| 가격대 적합성 | `avg_sponsorship_price`가 상품가 기반 허용 밴드 내인지 | 소프트(감점) |
| 오디언스 인구통계 | 상품 타겟 연령·성별과 최소 겹침 이상인지 | 겹침 0이면 제외 |
| 협찬 이력 충돌 | 경쟁 브랜드 협찬 이력 있으면 제외 | 하드 제외 |

MVP는 **협찬 충돌 = 하드 제외**, 나머지는 감점(soft)으로 두어 후보가 과도하게 사라지지 않게 함. 필터 사유는 결과에 함께 표기.

## 3. 임베딩 백엔드 (교체형)
`app/embeddings.py`에 인터페이스 `EmbeddingBackend.embed(texts) -> vectors`.
- `openai` — `text-embedding-3-small`, `OPENAI_API_KEY`
- `voyage` — `voyage-3`(한국어 포함 다국어), `VOYAGE_API_KEY`
- `hashing` — 오프라인 폴백(결정론적 bag-of-words 해시). 키 없이 파이프라인·테스트 구동용. **의미 인접성은 약함**(렉시컬 위주) — 실검증은 API 백엔드로.
- 선택: 환경변수 `EMBEDDING_BACKEND`(기본 자동: 키 있으면 해당 API, 없으면 hashing).
- 임베딩 캐시: `(backend, text_hash) → vector`를 DB/파일에 캐시해 재계산·API 비용 절감.

## 4. 매칭 근거 (Why matched)
상위 인플루언서마다 "왜 매칭됐나"를 제시.
- 인플루언서 텍스트를 키워드/구 단위로 분해 → 각 구를 임베딩 → **상품 벡터와 유사도 상위 2~3개 구**를 근거로 노출.
- 예: 상품=콜라겐 파우더, 근거="피부 탄력 / 속당김 완화 / 이너뷰티 루틴".

## 5. 데이터 모델 (SQLite)
```sql
influencers(influencer_id PK, name, handle, follower_count, tier, niche_category,
  recent_captions TEXT, comment_keywords TEXT, engagement_rate REAL,
  avg_sponsorship_price INT, audience_age_group TEXT, audience_gender_ratio TEXT,
  recent_sponsor_brands TEXT)   -- 협찬 이력(콤마구분)
products(product_id PK, name, category, price INT,
  ingredients TEXT, efficacy_description TEXT, usage_scenario TEXT,
  target_age_group TEXT, target_gender TEXT, competitor_brands TEXT)
match_results(match_id PK, influencer_id FK, product_id FK,
  semantic_score REAL, engagement_score REAL, audience_fit_score REAL,
  final_score REAL, created_at)
embedding_cache(backend TEXT, text_hash TEXT, vector TEXT, PRIMARY KEY(backend,text_hash))
```

## 6. 화면 (MVP)
- **상품 선택** → 후보 인플루언서 랭킹 테이블: 최종점수, semantic/engagement/audience 하위 막대, 티어, 매칭 근거 칩, 필터 사유.
- **가중치 슬라이더**(w1/w2/w3) + 프리셋(전환형/인지도형) → 클라이언트에서 즉시 재정렬(하위 점수는 서버 선계산).
- **정형 필터만 vs 의미 추가** 토글로 랭킹 차이를 보여 인접 니치 발굴을 시연(검증 §8 대응).

## 7. 검증 케이스 (시드에 내장)
- **콜라겐 파우더**(건강 니치 상품 성격) → "건강/이너뷰티" 라벨 인플루언서와 "스킨케어(피부 탄력)" 라벨 인플루언서가 **둘 다** 상위에 오르는지.
- 라벨만 보면 안 맞지만 캡션에 "피부 탄력/속당김" 있는 인플루언서가 의미 매칭으로 부상하는지.

## 8. 범위 밖 (v1.5+/v2)
CSV 업로드 UI(초기엔 시드/직접 입력), 매칭 이력 저장·정확도 보정, 실시간 대량 벡터검색(FAISS/pgvector), 발굴·가짜팔로워 검증.

## 9. 열린 결정
1. 임베딩 제공자: OpenAI vs Voyage (Voyage가 한국어 뷰티 용어에 유리할 수 있음). 키 제공 시 확정.
2. `audience_fit` 계산 정밀도(단순 겹침 vs 가중).
