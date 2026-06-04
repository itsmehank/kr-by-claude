import pandas as pd


def merge_raw_and_adjusted(raw: pd.DataFrame, adjusted: pd.DataFrame) -> pd.DataFrame:
    """raw(원가 OHLCV) + adjusted(수정 OHLC) → raw + adj_close/adj_high/adj_low/adj_open/adj_volume.

    adjusted 에 high/low/open/volume 가 있으면 보존(KRX 수정값), 없으면 raw 값으로 fallback.
    adjusted 가 누락된 날짜도 raw 로 fallback.
    """
    if raw.empty:
        return raw.assign(
            adj_close=pd.Series(dtype=float),
            adj_high=pd.Series(dtype=float),
            adj_low=pd.Series(dtype=float),
            adj_open=pd.Series(dtype=float),
            adj_volume=pd.Series(dtype=float),
        )

    rename = {"close": "adj_close"}
    if "high" in adjusted.columns:
        rename["high"] = "adj_high"
    if "low" in adjusted.columns:
        rename["low"] = "adj_low"
    if "open" in adjusted.columns:
        rename["open"] = "adj_open"
    if "volume" in adjusted.columns:
        rename["volume"] = "adj_volume"
    adj = adjusted.rename(columns=rename)[["date"] + list(rename.values())]
    merged = raw.merge(adj, on="date", how="left")

    merged["adj_close"] = merged["adj_close"].fillna(merged["close"]).astype(float)
    if "adj_high" not in merged.columns:
        merged["adj_high"] = merged["high"]
    merged["adj_high"] = merged["adj_high"].fillna(merged["high"]).astype(float)
    if "adj_low" not in merged.columns:
        merged["adj_low"] = merged["low"]
    merged["adj_low"] = merged["adj_low"].fillna(merged["low"]).astype(float)
    if "adj_open" not in merged.columns:
        merged["adj_open"] = merged["open"]
    merged["adj_open"] = merged["adj_open"].fillna(merged["open"]).astype(float)
    if "adj_volume" not in merged.columns:
        merged["adj_volume"] = merged["volume"]
    merged["adj_volume"] = merged["adj_volume"].fillna(merged["volume"]).astype(float)
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
            float(r["adj_high"]),
            float(r["adj_low"]),
            float(r["adj_open"]),
            float(r["adj_volume"]),
            int(r["volume"]),
            int(r["value"]),
        )
        for _, r in merged.iterrows()
    ]
