import pandas as pd


def merge_raw_and_adjusted(raw: pd.DataFrame, adjusted: pd.DataFrame) -> pd.DataFrame:
    """
    raw: 원가 OHLCV (date, open, high, low, close, volume, value)
    adjusted: 수정종가 (date, close)
    return: raw + adj_close. adjusted 가 누락된 날짜는 close 로 fallback.
    """
    if raw.empty:
        return raw.assign(adj_close=pd.Series(dtype=float))

    adj = adjusted.rename(columns={"close": "adj_close"})[["date", "adj_close"]]
    merged = raw.merge(adj, on="date", how="left")
    merged["adj_close"] = merged["adj_close"].fillna(merged["close"]).astype(float)
    return merged


def to_price_rows(ticker: str, merged: pd.DataFrame) -> list[tuple]:
    """daily_prices executemany 용 tuple 리스트."""
    return [
        (
            ticker,
            r["date"],
            int(r["open"]),
            int(r["high"]),
            int(r["low"]),
            int(r["close"]),
            float(r["adj_close"]),
            int(r["volume"]),
            int(r["value"]),
        )
        for _, r in merged.iterrows()
    ]
