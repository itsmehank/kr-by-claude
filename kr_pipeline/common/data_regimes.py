"""데이터 정의 경계(regime) — #207 회신 20 (ii)/(Q-4c). design-judgment 상수(책-유래 임계가 아니므로 thresholds.py 와 분리).

배경: KRX 정보데이터시스템 일별 거래량이 2026-09-28 부터 KRX 애프터마켓(16:00~20:00, 09-14 개장) 체결을 합산하는 것으로
추정된다(09-23 까지는 18:30 값 = 최종 = Yahoo, 09-28 은 최종 > 18:30 값). 거래량 규칙(HMMS Ch.20 규칙 11, "최근 봉 ÷
과거 평균")은 정의가 섞이면 비율이 위로만 왜곡돼 가짜 돌파를 만든다. 정규장 거래량을 사후에 구할 경로가 없어(#207 (iii)
조사 중) 값은 그대로 두고, **09-28 이후 봉을 입력으로 쓴 판정 행에 표지**를 붙인다(덮어쓰기 금지, 파이프라인 계속).

- VOLUME_REGIME_UNVERIFIED_FROM: 이 날짜 이상의 analyzed_for_date 를 가진 분류·트리거·진입파라미터 행에 VOLUME_REGIME_TAG.
  소비처: llm_runner/store.py insert_classification·insert_trigger_evaluation·insert_entry_params. 앵커 C3(climax_topping)는
  LLM payload 에 새 키를 넣게 되어(프롬프트 입력 변경) 넣지 않고 분류 행 표지로 덮는다.
- BACKTEST_EXCLUDED_FROM: 백테스트 사용 금지 시작일. 회신 20 Q-4c — 09-14~09-23 은 가격 재산출(A안)·거래량 정규장이라 해제,
  09-28 이후 금지 유지. **강제 지점** = assert_backtest_range_allowed(end): llm_runner/backfill.run · backtest/backfill.run_backtest_backfill ·
  backtest/portfolio.main 이 종료일 ≥ 경계면 거부(우회 = 환경변수 KR_ALLOW_EXCLUDED_REGIME=1, 탐색 전용·holdout 원장 기입 선행).
  표지 문구는 VOLUME_REGIME_TAG 로 통일.
- 같은 계열의 다른 경계: ohlcv/adjust.ADJ_SELF_START(2026-09-14, 수정주가 자체 산출 시임)·security_group.SECURITY_GROUP_GATE_EFFECTIVE_DATE.
- 경로 확보 시 (ii) → 정규장 복원 전환은 별건 판정. 표지 제거도 그때.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Final, Iterable

VOLUME_REGIME_UNVERIFIED_FROM: Final[date] = date(2026, 9, 28)
VOLUME_REGIME_TAG: Final[str] = "volume_regime_unverified_#207"
BACKTEST_EXCLUDED_FROM: Final[date] = date(2026, 9, 28)


def _as_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def volume_regime_warnings(as_of) -> list[str]:
    """analyzed_for_date(판정 입력 봉의 날짜)가 경계 이상이면 [VOLUME_REGIME_TAG], 아니면 []. None(미상)은 표지 없음.
    datetime·ISO 문자열도 받는다(이미 지불한 LLM 결과의 INSERT 를 타입 문제로 막지 않기 위해)."""
    d = _as_date(as_of)
    if d is None or d < VOLUME_REGIME_UNVERIFIED_FROM:
        return []
    return [VOLUME_REGIME_TAG]


def with_volume_regime(warnings: Iterable[str] | None, as_of) -> list[str]:
    """기존 SOFT 경고 목록에 거래량 정의 표지를 덧붙인 새 리스트(중복 없이). store 의 insert 4곳이 공유하는 단일 결합 지점."""
    out = list(warnings or [])
    for w in volume_regime_warnings(as_of):
        if w not in out:
            out.append(w)
    return out


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
