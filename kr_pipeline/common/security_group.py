"""증권구분(KRX SECUGRP_NM) 계약 — 유니버스 자격 게이트의 단일 정의 (governance 4-3).

배경(2026-09-12 사건): 이름 휴리스틱(`"리츠" in name`)이 같은 증권구분 안의 이름 변형을 놓쳐
094800 맵스리얼티(투자회사)·415640 KB발해인프라(사회간접자본투융자회사)가 유니버스에 유입·entry 신호 발화.
같은 휴리스틱이 138040 메리츠금융지주·369370 블리츠웨이엔터테인먼트를 부분문자열 오탐으로 부당 배제.
→ 증권 형태 판정을 종목명 문자열에서 발행기관 부여 정식 속성(SECUGRP_NM)으로 대체.

세 집합은 서로 배타적이며, 이 모듈 밖에서 값을 재정의하지 않는다.
- QUALIFYING: 자격 판정 대상(화이트리스트, fail-closed — 밖의 모든 값과 UNRESOLVED·미래 신설 유형은 제외).
- PRELOAD_EXCLUDED: 적재 전 배제(stocks 행 미생성).
- ROW_KEPT_EXCLUDED: stocks 행은 생성하되 자격 게이트에서 제외.

[비대칭 근거 — 전문가 판정 Q-4(수정), 2026-09-15] "수집 비용 대비 감사 가치" 단일 기준, 증권구분 단위 판단.
  부동산투자회사(리츠 23) = 시계열 수집 비용 크고 감사 가치 없음 → 행 미생성.
  사회간접자본투융자회사(2)·투자회사(1) = 신호 발화 이력이 있어 감사 가치 있음 → 행 생성 + 게이트 제외.
  구분 내에서 종목별로 갈리는 처리 금지. 향후 소급 무효화·Pre-Check 검증 완료 후 두 구분도 적재 전
  배제로 이관하는 것이 최종 형태(시점은 별건 판정).

우선주·스팩은 SECUGRP_NM 으로 판별 불가(005935·스팩 70종목 전부 '주권') → `kr_pipeline/universe/transform.py` 의
우선주(종목코드 말미 규칙, #195)·스팩(이름) 2축이 담당. ETF 는 유니버스 원본(pykrx 전종목시세 = 주식 전용)에 구조적으로
없어 축 자체를 제거(#195 커밋2). 두 축의 책임 경계는 이 문서가 정본.

전진 적용(governance 4-4·1-2): 기준일 이전 행의 minervini_pass 는 당시 파이프라인의 판정 기록이자
09-12 신호의 원인이므로 재산출하지 않는다. 게이트는 `date >= SECURITY_GROUP_GATE_EFFECTIVE_DATE` 행에만.
값은 NULL(판정하지 않음) — FALSE("검사했고 떨어짐")로 두면 시스템 강등 경로가 '추세 기준 미달'로 기록해
사실과 어긋난다(governance 4-2).

plan: docs/superpowers/plans/2026-09-15-secugrp-universe-filter.md
"""
from __future__ import annotations

from datetime import date

UNRESOLVED = "UNRESOLVED"

# [book-mandated] HMMS Ch.20 규칙 2~6·8 / TLSMW Ch.3 SEPA 2단계 — 방법론은 실적이 있는 사업회사 개별주를
# 겨냥한다. 외국주권·주식예탁증권은 실적이 존재하는 사업회사(법인 설립지 차이)라 허용(전문가 판정 회신 2).
QUALIFYING_SECURITY_GROUPS: frozenset[str] = frozenset({"주권", "외국주권", "주식예탁증권"})
PRELOAD_EXCLUDED_SECURITY_GROUPS: frozenset[str] = frozenset({"부동산투자회사"})
ROW_KEPT_EXCLUDED_SECURITY_GROUPS: frozenset[str] = frozenset({"사회간접자본투융자회사", "투자회사"})

# 게이트 발효일 — 이 날짜부터의 지표 행에만 적용(전진 적용). 과거 행 재산출 금지.
SECURITY_GROUP_GATE_EFFECTIVE_DATE: date = date(2026, 9, 15)

# [원칙 — 전문가 판정 회신 6, 2026-09-19] 파이프라인 상태 값은 '판정해서 떨어짐'과 '판정 대상이 아님'을
# 절대 같은 값으로 표현하지 않는다.
#   minervini_pass : FALSE vs NULL             (Q-5)
#   종료 사유 문구 : 자격상실 vs 자산유형배제   (Q-6)
#   분류 라벨      : disqualified vs 아래 값   (판정 1)
# 명칭 제약: 'disqualif' 문자열 포함 금지 — 집계·조회가 문자열로 실격을 잡는 함정(문자열 판정 금지 교훈).
#
# [prompt_version NULL 의 의미 — 회신 7 확인, #194 컷오버 = PR #196 머지(2026-09-19) 이후 첫 라이브 실행부터]
#   컷오버 이전 NULL = 값 유실(B6 배선 절단, 2026-09-10~09-19 생성분. 복원·백필 금지).
#   컷오버 이후 NULL = LLM 미호출 행. 기존 컬럼으로 구분 가능하므로 센티널 미도입:
#     trigger_evaluation_log : 결정론 wait 행 = `wait_reason IS NOT NULL` (⇔ llm_call_duration_s IS NULL);
#                              LLM 호출 행 = `llm_call_duration_s IS NOT NULL` (실측 218/218).
#     weekly_classification  : 시스템 행 = `source IN ('system_disqualify', 'system_universe_gate')`;
#                              LLM 행 = source IN ('weekend','daily_delta','backfill').
UNIVERSE_EXCLUSION_CLASSIFICATION = "excluded_by_universe"      # weekly_classification.classification
UNIVERSE_EXCLUSION_SOURCE = "system_universe_gate"              # weekly_classification.source (VARCHAR(20) 상한)
assert "disqualif" not in UNIVERSE_EXCLUSION_CLASSIFICATION and "disqualif" not in UNIVERSE_EXCLUSION_SOURCE

BOOK_MANDATED_EXCLUSION_REASON = (
    "security_group={security_group} — 평가 대상 자산 아님 "
    "(book-mandated: HMMS Ch.20 규칙 2~6·8 / TLSMW Ch.3 SEPA 2단계). "
    "무효화 기준은 성과와 독립적인 사전 속성이므로 순환성 위반 아님."
)


def excluded_reason_text(security_group: str) -> str:
    return BOOK_MANDATED_EXCLUSION_REASON.format(security_group=security_group)


def is_gated_out(security_group: str | None, on_date: date) -> bool:
    """참 = 이 (종목, 날짜)의 minervini_pass 를 NULL 로 둔다. 기준일 이전은 항상 거짓."""
    if on_date < SECURITY_GROUP_GATE_EFFECTIVE_DATE:
        return False
    return security_group not in QUALIFYING_SECURITY_GROUPS


def security_group_gate_sql(alias: str, date_col: str) -> str:
    """UPDATE 문에 넣는 게이트 조건(참 = NULL). named params 필수: security_group_gate_params().

    stocks 행이 없으면 UNRESOLVED 로 간주(fail-closed). alias/date_col 은 코드 상수만 — 외부 입력 금지.
    """
    return (
        f"({alias}.{date_col} >= %(gate_eff)s AND "
        f"COALESCE((SELECT s.security_group FROM stocks s WHERE s.ticker = {alias}.ticker), '{UNRESOLVED}') "
        f"<> ALL(%(gate_allowed)s))"
    )


def security_group_gate_params() -> dict:
    return {"gate_eff": SECURITY_GROUP_GATE_EFFECTIVE_DATE,
            "gate_allowed": sorted(QUALIFYING_SECURITY_GROUPS)}
