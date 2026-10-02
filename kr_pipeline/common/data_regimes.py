"""데이터 정의 경계(regime) — #207 회신 20 (ii)/(Q-4c). design-judgment 상수(책-유래 임계가 아니므로 thresholds.py 와 분리).

배경: KRX 정보데이터시스템 일별 거래량이 2026-09-28 부터 KRX 애프터마켓(16:00~20:00, 09-14 개장) 체결을 합산하는 것으로
추정된다(09-23 까지는 18:30 값 = 최종 = Yahoo, 09-28 은 최종 > 18:30 값). 거래량 규칙(HMMS Ch.20 규칙 11, "최근 봉 ÷
과거 평균")은 정의가 섞이면 비율이 위로만 왜곡돼 가짜 돌파를 만든다. 정규장 거래량을 사후에 구할 경로가 없어(#207 (iii)
조사 중) 값은 그대로 두고, **09-28 이후 봉을 입력으로 쓴 판정 행에 표지**를 붙인다(덮어쓰기 금지, 파이프라인 계속).

- VOLUME_REGIME_BOUNDARY(별칭 VOLUME_REGIME_UNVERIFIED_FROM): 봉 volume_regime(regular/extended) 경계. 판정 행은 전용 컬럼 volume_regime_flag('mixed'|NULL).
  소비처: llm_runner/store.py insert_classification·insert_trigger_evaluation·insert_entry_params. 앵커 C3(climax_topping)는
  LLM payload 에 새 키를 넣게 되어(프롬프트 입력 변경) 넣지 않고 분류 행 표지로 덮는다.
- BACKTEST_EXCLUDED_FROM: 백테스트 사용 금지 시작일. 회신 20 Q-4c — 09-14~09-23 은 가격 재산출(A안)·거래량 정규장이라 해제,
  09-28 이후 금지 유지. **강제 지점** = assert_backtest_range_allowed(end): llm_runner/backfill.run · backtest/backfill.run_backtest_backfill ·
  backtest/portfolio.main 이 종료일 ≥ 경계면 거부(우회 = 환경변수 KR_ALLOW_EXCLUDED_REGIME=1, 탐색 전용·holdout 원장 기입 선행).
  판정 행 표지는 전용 컬럼 volume_regime_flag(회신 21).
- 같은 계열의 다른 경계: ohlcv/adjust.ADJ_SELF_START(2026-09-14, 수정주가 자체 산출 시임)·security_group.SECURITY_GROUP_GATE_EFFECTIVE_DATE.
- 회신 21(09-30): 정규장 복원 전환 **폐기** — KRX 일별 거래량(애프터마켓 합산)을 정의로 수용. 봉에는 volume_regime(regular/extended/
  mixed)만 저장하고 판정 행에는 전용 컬럼 volume_regime_flag 로 mixed 창만 표지(PR-2·PR-3, spec 2026-09-30-volume-regime-design.md).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Final, Iterable

VOLUME_REGIME_BOUNDARY: Final[date] = date(2026, 9, 28)        # KRX 일별 거래량에 애프터마켓 합산 시작(관측 추정, 회신 21)
VOLUME_REGIME_UNVERIFIED_FROM: Final[date] = VOLUME_REGIME_BOUNDARY   # PR #217 호환 별칭
BACKTEST_EXCLUDED_FROM: Final[date] = date(2026, 9, 28)
REGIME_REGULAR: Final[str] = "regular"     # 정규장(09:00~15:30) 거래량
REGIME_EXTENDED: Final[str] = "extended"   # 애프터마켓(16:00~20:00) 합산 거래량(회신 21: 정의로 수용)
REGIME_MIXED: Final[str] = "mixed"         # 주봉: 구성 일봉 혼재
FLAG_MIXED: Final[str] = "mixed"           # 판정 행 volume_regime_flag 값(그 외 NULL)


def _as_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def regime_for_date(d: date) -> str:
    """봉 날짜 → 정의. 일봉·지수 writer(ohlcv/store)가 이 값을 그대로 저장한다(SQL CASE 사본 없음 — 2차 리뷰로 단일화).
    이관 SQL(scripts/sql/issue207_volume_regime_migrate.sql)만 같은 규칙의 SQL 사본이며 날짜 리터럴 == VOLUME_REGIME_BOUNDARY 를
    테스트가 고정한다."""
    return REGIME_EXTENDED if d >= VOLUME_REGIME_BOUNDARY else REGIME_REGULAR


def regime_for_week(week_end: date) -> str:
    """주봉 → 정의(weekly/store 가 저장). 그 주의 달력 월요일(ISO)과 week_end 가 모두 경계 전이면 regular, 월요일 ≥ 경계면 extended,
    그 외 mixed. 달력 월요일 기준이라 그 주 첫 거래일이 휴일이면 mixed 쪽으로 보수적(2차 리뷰 기록; 실제 첫 봉 기준은 PR-3 후보)."""
    if week_end < VOLUME_REGIME_BOUNDARY:
        return REGIME_REGULAR
    monday = week_end - timedelta(days=week_end.weekday())
    return REGIME_EXTENDED if monday >= VOLUME_REGIME_BOUNDARY else REGIME_MIXED


def regime_flag_for_as_of(as_of) -> str | None:
    """판정 행 표지(PR-2 규칙): as_of ≥ 경계 → 'mixed'. PR-3 에서 계산 창 유도로 축소(new → NULL).
    ⚠ 만료 없음(2차 리뷰 기록): 경계 + ~50 세션(≈2026-12-10) 이후에도 'mixed' 를 찍는다 — PR-3 가 그 전에 창 유도로 대체해야 하고,
    되돌림(mixed → NULL)은 이관 SQL 이 하지 않으므로 PR-3 가 별도 UPDATE 를 동반한다."""
    d = _as_date(as_of)
    if d is None or d < VOLUME_REGIME_BOUNDARY:
        return None
    return FLAG_MIXED


ALLOW_EXCLUDED_REGIME_ENV: Final[str] = "KR_ALLOW_EXCLUDED_REGIME"


def assert_backtest_range_allowed(end) -> None:
    """백테스트·백필 종료일이 BACKTEST_EXCLUDED_FROM 이상이면 ValueError(회신 20 Q-4c). 우회 = KR_ALLOW_EXCLUDED_REGIME=1."""
    d = _as_date(end)
    if d is None or d < BACKTEST_EXCLUDED_FROM:
        return
    if os.environ.get(ALLOW_EXCLUDED_REGIME_ENV) == "1":
        return
    raise ValueError(
        f"backtest/backfill end={d} ≥ BACKTEST_EXCLUDED_FROM {BACKTEST_EXCLUDED_FROM}: 09-28 이후 봉은 거래량 정의 미확정(#207 회신 20 Q-4c) — "
        f"사용 금지. 탐색 전용으로 강행하려면 {ALLOW_EXCLUDED_REGIME_ENV}=1 (holdout 원장 기입 선행)."
    )
