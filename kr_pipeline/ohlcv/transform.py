import numpy as np
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

    # 거래정지/무거래일(raw open=high=low=0 AND close>0 AND volume=0):
    # adj_open/high/low/volume → NaN(NULL). raw 0 은 보존(halt 마커),
    # close/adj_close 는 직전가 carry 유지. → w52_low(rolling min)·avg_volume(mean)
    # 가 0 을 흡수하지 않음. volume>0(실거래 mis-fetch)은 제외.
    halt = (
        (merged["open"] == 0) & (merged["high"] == 0) & (merged["low"] == 0)
        & (merged["close"] > 0) & (merged["volume"] == 0)
    )
    merged.loc[halt, ["adj_open", "adj_high", "adj_low", "adj_volume"]] = np.nan
    return merged


def to_price_rows(ticker: str, merged: pd.DataFrame) -> list[tuple]:
    """daily_prices executemany 용 tuple 리스트.

    adj_* 는 halt 정규화로 NaN 일 수 있음 → None(NULL). raw open/high/low/volume·close 는
    NOT NULL 이며 halt 에서도 0/close 값을 유지(0 은 halt 마커).
    """
    def _adj(v):
        return None if pd.isna(v) else float(v)

    return [
        (
            ticker,
            r["date"],
            int(r["open"]),
            int(r["high"]),
            int(r["low"]),
            int(r["close"]),
            _adj(r["adj_close"]),
            _adj(r["adj_high"]),
            _adj(r["adj_low"]),
            _adj(r["adj_open"]),
            _adj(r["adj_volume"]),
            int(r["volume"]),
            int(r["value"]),
        )
        for _, r in merged.iterrows()
    ]


def to_index_rows(index_code: str, idx_df: pd.DataFrame) -> list[tuple]:
    """index_daily.executemany 용 tuple 리스트.

    OHLC 는 소수 2자리(NUMERIC(12,2)) — int() 절단 금지. KOSDAQ(~900pt)에서
    절단 시 일일 등락률 오차가 최대 ±0.2%p 로, market_context 의
    distribution day(-0.2%)/follow-through 임계 판정이 경계일에 플립된다.
    volume/value 는 nullable bigint → NaN 은 None.
    """
    return [
        (
            index_code,
            r["date"],
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            int(r["volume"]) if not pd.isna(r.get("volume")) else None,
            int(r["value"]) if not pd.isna(r.get("value")) else None,
        )
        for _, r in idx_df.iterrows()
    ]
