"""장 마감·확정 시각 — #207 회신 21 Q-5a ①. 단일 정의(trading_calendar 가 재수출).

CLOSE_BUFFER: "이 시각 이후면 오늘 봉이 확정값"으로 보는 KST 시각. 두 소비처가 같은 기준을 쓴다.
  - trading_calendar.expected_latest_trading_day: 오늘이 거래일이고 now ≥ CLOSE_BUFFER → ELTD = 오늘(그 전엔 직전 거래일).
  - ohlcv.modes.compute_date_range(INCREMENTAL): now < CLOSE_BUFFER → 수집 창 종료일 = 어제(오늘 봉 제외, 경로 무관 기본값).
근거(measurement-based): KRX 전종목시세는 애프터마켓(16:00~20:00, 2026-09-14 개장) 중 20분 지연 잠정값을 반환(09-28~ 관측,
화면 표기 "20분 지연 정보, 애프터마켓") → 확정 하한 20:20. 20:25 = 하한 + 여유(design-judgment, 단일 기준).
구 17:00(pykrx EOD 안정화)은 09-28 부터 부적합(09-28 18:30·09-29 17:19 잠정 종가 260·257종목).
개정: 09-30 20:30 첫 정규 발화가 잠정값이면 20:55(21:08 최종 실측 기준, 회신 21 Q-5b). checklist 이력 1줄 + 전문가 승인.
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Final

CLOSE_BUFFER: Final[time] = time(20, 25)


def today_bar_final(now: datetime | None = None) -> bool:
    """지금 시각에 오늘 봉을 확정값으로 볼 수 있는가(now ≥ CLOSE_BUFFER)."""
    now = now or datetime.now()
    return now.time() >= CLOSE_BUFFER
