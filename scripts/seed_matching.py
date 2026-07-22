"""매칭 스코어링 샘플 데이터.

검증 케이스를 의도적으로 심는다:
 - 콜라겐 파우더(건강/이너뷰티 성격 상품)에 대해
   · 건강/이너뷰티 인플루언서(콜라겐 직접 언급)뿐 아니라
   · 스킨케어 인플루언서(피부 탄력/속당김 언급)도 상위로 올라오는지  → 인접 니치 발견
   · 반대로 같은 '건강' 라벨이라도 운동/단백질 위주 인플루언서는 낮게  → 라벨만으론 안 됨
 - 경쟁 브랜드 협찬 이력 인플루언서는 정형 필터에서 제외되는지
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.db import get_conn, init_db  # noqa: E402

INFLUENCERS = [
    # name, handle, followers, tier, niche, captions, comment_keywords, eng, price, age, gender, sponsors
    ("윤채원", "chaewon.skin", 42000, "micro", "스킨케어",
     "요즘 피부 탄력이 부쩍 떨어져서 콜라겐 관리 시작했어요. 속당김 없는 촉촉한 마무리 앰플 추천. 나이보다 어려보이는 피부 루틴 공유",
     "피부 탄력, 속당김 완화, 안티에이징, 촉촉함, 이너뷰티 루틴", 0.061, 900000, "25-39", "F88/M12", ""),

    ("한지우", "jiwoo.innerbeauty", 88000, "mid", "건강",
     "이너뷰티는 먹는 것부터. 저분자 콜라겐 파우더로 피부 탄력 챙기는 중. 아침 공복 루틴, 콜라겐 물에 타먹기",
     "콜라겐, 이너뷰티, 피부 탄력, 영양제 루틴, 저분자", 0.052, 1500000, "25-44", "F80/M20", ""),

    ("박도현", "dohyun.fit", 210000, "mid", "건강",
     "오늘도 헬스장 직진. 단백질 보충제 리뷰, 벌크업 식단, 유산소 루틴. 운동으로 만드는 몸",
     "단백질, 운동 루틴, 다이어트, 벌크업, 헬스", 0.048, 1800000, "20-34", "F35/M65", ""),

    ("이서아", "seoa.makeup", 61000, "micro", "메이크업",
     "데일리 메이크업 튜토리얼. 매트한 립 틴트 발색 비교, 지속력 좋은 색조 추천, 데일리 룩",
     "립 틴트, 색조, 발색, 데일리 메이크업, 지속력", 0.070, 950000, "18-29", "F92/M8", ""),

    ("최유나", "yuna.beauty", 320000, "mega", "뷰티",
     "스킨케어부터 메이크업까지 종합 뷰티. 신제품 하울, 수분 앰플 후기, 톤업 베이스",
     "수분, 앰플, 하울, 톤업, 스킨케어", 0.031, 3200000, "20-39", "F85/M15", ""),

    ("정민서", "minseo.care", 27000, "micro", "스킨케어",
     "건조한 겨울철 속당김 완화가 최대 고민. 수분 진정 앰플, 히알루론산 성분 좋아함, 저자극 루틴",
     "수분, 속당김 완화, 진정, 히알루론산, 저자극", 0.066, 700000, "20-34", "F90/M10", ""),

    ("강하린", "harin.glow", 51000, "micro", "스킨케어",
     "피부 탄력과 주름 개선에 진심. 콜라겐 앰플 꾸준히 사용 후기, 탄탄한 피부 루틴",
     "피부 탄력, 주름 개선, 콜라겐, 안티에이징", 0.058, 850000, "30-49", "F86/M14", "뉴트리원"),

    ("서지호", "jiho.daddy", 140000, "mid", "육아",
     "두 아이 육아 브이로그. 유아 간식, 가족 나들이, 아기 스킨케어 꿀템",
     "육아, 아기, 가족, 살림", 0.044, 1200000, "30-44", "F70/M30", ""),
]

PRODUCTS = [
    # name, category, price, ingredients, efficacy, usage, target_age, target_gender, competitors
    ("이너글로우 콜라겐 파우더", "건강/이너뷰티", 39000,
     "저분자 피쉬 콜라겐, 비타민C, 엘라스틴",
     "피부 탄력 개선, 수분 유지, 속당김 완화에 도움을 주는 먹는 이너뷰티",
     "아침 공복 물에 타먹는 이너뷰티 루틴, 안티에이징 관리",
     "25-45", "F", "뉴트리원"),

    ("수분광 진정 앰플", "스킨케어", 28000,
     "히알루론산, 판테놀, 마데카소사이드",
     "건조한 피부 속당김 완화, 진정, 수분 장벽 강화",
     "건조한 겨울철 저녁 스킨케어 마지막 단계, 저자극 진정 루틴",
     "20-39", "F", "라운드랩"),

    ("벨벳 매트 립 틴트", "메이크업", 19000,
     "호호바 오일, 비타민E 코팅 피그먼트",
     "매트하지만 촉촉한 발색, 하루 종일 지속되는 색조",
     "데일리 메이크업 포인트, 지속력 필요한 색조 룩",
     "18-32", "F", "롬앤"),
]


def main():
    dbp = os.environ.get("MATCH_DB", os.path.join(os.path.dirname(__file__), "..", "matching.db"))
    if os.path.exists(dbp):
        os.remove(dbp)
    init_db()
    conn = get_conn()
    for i, r in enumerate(INFLUENCERS, start=1):
        conn.execute(
            """INSERT INTO influencers(influencer_id,name,handle,follower_count,tier,niche_category,
               recent_captions,comment_keywords,engagement_rate,avg_sponsorship_price,
               audience_age_group,audience_gender_ratio,recent_sponsor_brands)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (i,) + r,
        )
    for j, r in enumerate(PRODUCTS, start=1):
        conn.execute(
            """INSERT INTO products(product_id,name,category,price,ingredients,
               efficacy_description,usage_scenario,target_age_group,target_gender,competitor_brands)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (j,) + r,
        )
    conn.commit()
    n_i = conn.execute("SELECT COUNT(*) FROM influencers").fetchone()[0]
    n_p = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    print(f"seeded: influencers={n_i}, products={n_p}")


if __name__ == "__main__":
    main()
