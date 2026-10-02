"""(#207 회신 21 Q-5c 1) 전일 대비 거래량 비교의 정의 정합.

2026-09-28 부터 KRX 일별 거래량은 애프터마켓 합산(extended)이라 전일(regular)과 "많다/적다" 비교가 무의미하다.
today/yesterday 의 volume_regime 이 다르면 분배일·정체일·FTD 판정에서 그 날을 비교 불가로 건너뛴다.
"""
from __future__ import annotations


def regime_comparable(today, yesterday) -> bool:
    """행에 volume_regime 이 없거나 NULL 이면(구 호출처·리플레이) 비교 허용."""
    try:
        a, b = today["volume_regime"], yesterday["volume_regime"]
    except (KeyError, IndexError, TypeError):
        return True
    if a is None or b is None:
        return True
    try:
        if a != a or b != b:   # NaN
            return True
    except TypeError:
        pass
    return a == b
