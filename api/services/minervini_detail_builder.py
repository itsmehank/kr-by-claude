"""미너비니 8 조건 detail + margin_pct."""
from datetime import date
from psycopg import Connection


CONDITION_DESCRIPTIONS = {
    "c1": "close > SMA(150) > SMA(200)",
    "c2": "SMA(150) > SMA(200)",
    "c3": "SMA(200) 22 영업일 상승 추세",
    "c4": "SMA(50) > SMA(150) > SMA(200)",
    "c5": "close > SMA(50)",
    "c6": "close >= 52w low × 1.25",
    "c7": "close >= 52w high × 0.75",
    "c8": "RS Rating >= 70",
}


def margin_pct_c1(values: dict) -> float | None:
    if values.get("close") is None or values.get("sma_150") is None or values.get("sma_200") is None:
        return None
    return round(min(
        (values["close"] - values["sma_150"]) / values["sma_150"] * 100,
        (values["sma_150"] - values["sma_200"]) / values["sma_200"] * 100,
    ), 2)


def margin_pct_c2(values: dict) -> float | None:
    if values.get("sma_150") is None or values.get("sma_200") is None:
        return None
    return round((values["sma_150"] - values["sma_200"]) / values["sma_200"] * 100, 2)


def margin_pct_c3(values: dict) -> float | None:
    """SMA(200) today vs 22d ago. values 에 sma_200_22d_ago 필요."""
    today_v = values.get("sma_200_today")
    old_v = values.get("sma_200_22d_ago")
    if today_v is None or old_v is None or old_v == 0:
        return None
    return round((today_v - old_v) / old_v * 100, 2)


def margin_pct_c4(values: dict) -> float | None:
    if values.get("sma_50") is None or values.get("sma_150") is None or values.get("sma_200") is None:
        return None
    return round(min(
        (values["sma_50"] - values["sma_150"]) / values["sma_150"] * 100,
        (values["sma_150"] - values["sma_200"]) / values["sma_200"] * 100,
    ), 2)


def margin_pct_c5(values: dict) -> float | None:
    if values.get("close") is None or values.get("sma_50") is None:
        return None
    return round((values["close"] - values["sma_50"]) / values["sma_50"] * 100, 2)


def margin_pct_c6(values: dict) -> float | None:
    if values.get("close") is None or values.get("w52_low") is None:
        return None
    threshold = values["w52_low"] * 1.25
    return round((values["close"] - threshold) / threshold * 100, 2)


def margin_pct_c7(values: dict) -> float | None:
    if values.get("close") is None or values.get("w52_high") is None:
        return None
    threshold = values["w52_high"] * 0.75
    return round((values["close"] - threshold) / threshold * 100, 2)


def margin_pct_c8(values: dict) -> float | None:
    if values.get("rs_rating") is None:
        return None
    return round(values["rs_rating"] - 70, 2)


def build_minervini_detail(conn: Connection, ticker: str, on_date: date) -> dict:
    """daily_indicators 의 최근 행 (on_date) 에서 8 조건 detail + values + margin_pct.

    Return: {"c1": {"passed": bool, "description": str, "values": {...}, "margin_pct": float}, ...}
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT adj_close, sma_50, sma_150, sma_200, w52_high, w52_low, rs_rating,
                   minervini_c1, minervini_c2, minervini_c3, minervini_c4, minervini_c5,
                   minervini_c6, minervini_c7, minervini_c8
              FROM daily_indicators
             WHERE ticker = %s AND date = %s
            """,
            (ticker, on_date),
        )
        row = cur.fetchone()

    if row is None:
        return {
            f"c{i}": {
                "passed": None,
                "description": CONDITION_DESCRIPTIONS[f"c{i}"],
                "values": {},
                "margin_pct": None,
            }
            for i in range(1, 9)
        }

    close, sma_50, sma_150, sma_200, w52_high, w52_low, rs_rating, *passes = row

    base_values = {
        "close": float(close) if close is not None else None,
        "sma_50": float(sma_50) if sma_50 is not None else None,
        "sma_150": float(sma_150) if sma_150 is not None else None,
        "sma_200": float(sma_200) if sma_200 is not None else None,
        "w52_high": float(w52_high) if w52_high is not None else None,
        "w52_low": float(w52_low) if w52_low is not None else None,
        "rs_rating": int(rs_rating) if rs_rating is not None else None,
    }

    detail = {}
    margins = {
        "c1": margin_pct_c1,
        "c2": margin_pct_c2,
        "c3": margin_pct_c3,
        "c4": margin_pct_c4,
        "c5": margin_pct_c5,
        "c6": margin_pct_c6,
        "c7": margin_pct_c7,
        "c8": margin_pct_c8,
    }
    for i, (key, margin_fn) in enumerate(margins.items()):
        if key == "c6":
            values = {
                "close": base_values["close"],
                "w52_low": base_values["w52_low"],
                "threshold": base_values["w52_low"] * 1.25 if base_values["w52_low"] else None,
            }
        elif key == "c7":
            values = {
                "close": base_values["close"],
                "w52_high": base_values["w52_high"],
                "threshold": base_values["w52_high"] * 0.75 if base_values["w52_high"] else None,
            }
        elif key == "c8":
            values = {"rs_rating": base_values["rs_rating"], "threshold": 70}
        elif key == "c3":
            values = {}  # c3 는 sma_200 today + 22d ago 필요. 본 builder 에선 생략 (None margin)
        else:
            values = base_values.copy()

        detail[key] = {
            "passed": bool(passes[i]) if passes[i] is not None else None,
            "description": CONDITION_DESCRIPTIONS[key],
            "values": {k: v for k, v in values.items() if v is not None},
            "margin_pct": margin_fn(values),
        }

    return detail
