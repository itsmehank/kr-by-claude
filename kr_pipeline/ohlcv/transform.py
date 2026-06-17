import numpy as np
import pandas as pd

_HALT_ADJ_COLS = ["adj_open", "adj_high", "adj_low", "adj_volume"]


def nullify_halt_adj(df: pd.DataFrame) -> pd.DataFrame:
    """**단일 chokepoint** — 거래정지/무거래일의 수정 OHLV·volume → NaN(NULL).

    검출(adj 기준): adj_open=adj_high=adj_low=0 AND adj_volume=0 AND adj_close>0
    (KRX 가 정지일에 OHLV/거래량 0, 종가만 직전가 carry 로 줌 — raw·adj 동일). adj_close 유지.
    adj_volume>0(실거래 mis-fetch)은 제외 — halt 아님(별도 처리).

    adj_* 를 쓰는 *모든* 경로가 이 함수를 경유해야 한다 — ①daily INSERT(merge_raw_and_adjusted)
    ②adj-refresh(_run_full_refresh._process_ticker) ③드리프트 재적재(drift.reload_ticker)
    세 경로 모두. 한 경로라도 누락하면 다음 적재가 halt 행을 0 으로 되돌린다(weekly 는 daily
    파생이라 상속). 신규 writer 추가 시 필수 경유 — store._warn_unnormalized_halt 트립와이어가
    누락을 로그로 조기 경보한다."""
    halt = (
        (df["adj_open"] == 0) & (df["adj_high"] == 0) & (df["adj_low"] == 0)
        & (df["adj_volume"] == 0) & (df["adj_close"] > 0)
    )
    df.loc[halt, _HALT_ADJ_COLS] = np.nan
    return df


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

    # 단일 chokepoint 경유 — 거래정지일 adj_* → NULL (raw 0 은 halt 마커로 보존).
    return nullify_halt_adj(merged)


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
