# kr_pipeline/market_context/compute/breadth.py
"""시장 Breadth 계산 (해당 시장의 활성 종목 중 SMA200 위 비율).

입력: 특정 (시장, 날짜) 의 daily_indicators 행들 ({adj_close, sma_200, ...}).
sma_200 NULL 종목은 lookback 부족으로 제외 (상장 1년 미만).
"""


def compute_breadth(rows: list[dict]) -> float | None:
    """% (소수 1자리). 유효 종목 0개면 None."""
    valid = [r for r in rows if r.get("sma_200") is not None]
    if not valid:
        return None
    above = sum(1 for r in valid if float(r["adj_close"]) > float(r["sma_200"]))
    return round(above / len(valid) * 100, 1)
