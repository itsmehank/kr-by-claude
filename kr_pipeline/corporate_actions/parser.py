# kr_pipeline/corporate_actions/parser.py
"""DART 공시 제목 → event_type / ratio 파싱 (순수 함수).

한국어 키워드 매칭 + 정규식 비율 추출.
"""
import re


EVENT_TYPE_KEYWORDS = {
    "stock_split": ["주식분할결정", "액면분할"],
    "reverse_split": ["주식병합결정", "액면병합"],
    "spinoff": ["회사분할결정", "분할합병결정", "물적분할", "인적분할"],
    "merger": ["회사합병결정", "타법인합병"],
    # 증자 — 수정주가를 바꿔 drift 를 유발하므로 포함. "유무상증자결정"은 "무상증자결정"
    # 부분일치로 bonus_issue 에 잡힘(둘 다인 공시 — drift 목적엔 충분).
    "rights_offering": ["유상증자결정"],   # 유상증자(주요사항보고)
    "bonus_issue": ["무상증자결정"],        # 무상증자(주요사항보고). 유무상증자결정도 여기
    "dividend_special": [],   # 일반 배당과 구분 어려움 — 본문 파싱 필요, V2 (현금배당은 수정주가 무관)
    "capital_reduction": ["자본감소결정", "감자결정"],
}


def parse_event_type(report_nm: str) -> str | None:
    """report_nm 한국어 키워드 매칭. 첫 매칭 event_type 반환.

    None: 6 종 외 공시 (정기보고서, 주총 안내 등).
    """
    if not report_nm:
        return None
    for event_type, keywords in EVENT_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in report_nm:
                return event_type
    return None


# 비율 추출 정규식: "10:1", "1 : 10", "50:1" 등
RATIO_PATTERN = re.compile(r"(\d+)\s*:\s*(\d+)")


def parse_ratio(report_nm: str, event_type: str) -> str | None:
    """제목에서 N:M 패턴 추출 → "N:M" 형식 (공백 제거).

    찾지 못하면 None. 정확한 비율은 본문 파싱 필요 — 본 함수는 best-effort.
    """
    if not report_nm:
        return None
    m = RATIO_PATTERN.search(report_nm)
    if not m:
        return None
    return f"{m.group(1)}:{m.group(2)}"
