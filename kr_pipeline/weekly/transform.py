"""주봉 집계 transform — 순수 함수, 외부 IO 없음."""
from datetime import date
import pandas as pd


WEEKLY_COLUMNS = [
    "week_end_date", "open", "high", "low", "close",
    "adj_close", "adj_high", "adj_low", "adj_open", "adj_volume", "volume", "value", "trading_days",
]


def aggregate_to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 DataFrame 을 주봉으로 집계.

    입력 daily 컬럼: date, open, high, low, close, adj_close, volume, value
    출력 컬럼: WEEKLY_COLUMNS

    주 그룹화: ISO 주 (월~일). max(date) 가 week_end_date.
    pykrx 는 휴장일 빼고 제공하므로 휴장 캘린더 불필요.
    """
    if daily.empty:
        return pd.DataFrame(columns=WEEKLY_COLUMNS)

    df = daily.copy()
    df["date"] = pd.to_datetime(df["date"])

    # None → NaN for volume/value so sum(min_count=1) preserves "all-NULL → NaN"
    # (relevant for indexes where these are nullable in DB)
    for col in ("volume", "value", "adj_volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["_period"] = df["date"].dt.to_period("W-SUN")

    # 각 그룹을 정렬해서 첫/마지막 값 추출
    df = df.sort_values(["_period", "date"])

    grouped = df.groupby("_period")

    agg = pd.DataFrame({
        "week_end_date": grouped["date"].max().dt.date,
        "open":          grouped["open"].first(),
        "high":          grouped["high"].max(),
        "low":           grouped["low"].min(),
        "close":         grouped["close"].last(),
        "adj_close":     grouped["adj_close"].last(),
        "adj_high":      grouped["adj_high"].max(),
        "adj_low":       grouped["adj_low"].min(),
        "adj_open":      grouped["adj_open"].first(),
        "adj_volume":    grouped["adj_volume"].sum(min_count=1),
        "volume":        grouped["volume"].sum(min_count=1),   # all-NaN → NaN
        "value":         grouped["value"].sum(min_count=1),
        "trading_days":  grouped["date"].count(),
    }).reset_index(drop=True)

    return agg[WEEKLY_COLUMNS]


def drop_incomplete_weeks(weekly: pd.DataFrame, today: date) -> pd.DataFrame:
    """현재 진행 중인 주 제외 (week_end_date 가 today 와 같은 ISO 주에 속하면 미완성).

    토·일요일은 거래소가 쉬므로 이미 그 주는 완료된 것으로 간주한다.
    """
    if weekly.empty:
        return weekly

    # 토(5), 일(6)이면 그 주 거래는 완료 → 제거할 미완성 주 없음
    if today.weekday() >= 5:
        return weekly.reset_index(drop=True)

    today_period = pd.Period(today, freq="W-SUN")
    we_period = pd.to_datetime(weekly["week_end_date"]).dt.to_period("W-SUN")
    return weekly[we_period != today_period].reset_index(drop=True)


def to_weekly_rows(ticker: str, weekly: pd.DataFrame) -> list[tuple]:
    """weekly_prices.executemany 용 tuple 리스트.

    adj_* 는 NaN→None 변환 (daily 의 ohlcv/transform._adj 와 동일 처리).
    한 주 전체 halt(일봉 adj_* 전부 NULL)면 집계가 NaN — 무변환 시 psycopg 가
    'NaN'::numeric 으로 적재해 COALESCE(adj_*, raw) 를 통과, payload JSON 오염.
    raw OHLCV 는 NOT NULL(halt 마커 0/유지값)이라 그대로.
    """
    def _adj(v):
        return None if pd.isna(v) else float(v)

    return [
        (
            ticker,
            r["week_end_date"],
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
            int(r["trading_days"]),
        )
        for _, r in weekly.iterrows()
    ]


def to_weekly_index_rows(index_code: str, weekly: pd.DataFrame) -> list[tuple]:
    """weekly_index.executemany 용 tuple 리스트. volume/value NULL 가능.

    OHLC 는 소수 2자리(NUMERIC(12,2)) — int() 절단 금지 (지수 등락률 왜곡).
    """
    rows = []
    for _, r in weekly.iterrows():
        vol = r.get("volume")
        val = r.get("value")
        rows.append((
            index_code,
            r["week_end_date"],
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            int(vol) if vol is not None and not pd.isna(vol) else None,
            int(val) if val is not None and not pd.isna(val) else None,
            int(r["trading_days"]),
        ))
    return rows
