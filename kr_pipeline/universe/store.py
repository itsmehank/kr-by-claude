from datetime import date
import pandas as pd
from psycopg import Connection


def upsert_stocks(conn: Connection, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    rows = []
    for _, r in df.iterrows():
        sector = r.get("sector")
        if pd.isna(sector):
            sector = None
        rows.append((r["ticker"], r["name"], r["market"], sector))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO stocks (ticker, name, market, sector, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (ticker) DO UPDATE
               SET name = EXCLUDED.name,
                   market = EXCLUDED.market,
                   sector = COALESCE(EXCLUDED.sector, stocks.sector),
                   delisted_at = NULL,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount


# [design judgment] 1회 폐지 비율 상한 — book 근거 아님. 월 1회 정상 폐지는
# 수십 건 이하(활성 ~2,550 의 1% 미만)라 2% 는 넉넉한 안전마진. 초과는 부분
# fetch(한 시장 누락 등) 의심 → 파괴적 UPDATE 전에 fail-closed.
_MAX_DELIST_RATIO = 0.02


def mark_delisted(conn: Connection, *, current_tickers: set[str], on_date: date) -> int:
    """현재 universe 에 없는, 아직 delisted_at 이 NULL 인 종목을 폐지 처리.

    Safety: ① current_tickers 가 비어 있으면 (fetch 실패 등) 아무것도 하지 않음.
    ② 폐지 대상이 활성 종목의 _MAX_DELIST_RATIO 초과면 UPDATE 전에 ValueError —
    fetch_tickers 의 시장별 하한 가드를 뚫고 온 부분 목록의 심층 방어.
    """
    if not current_tickers:
        return 0
    tickers_list = list(current_tickers)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM stocks WHERE delisted_at IS NULL")
        active = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM stocks WHERE delisted_at IS NULL AND ticker != ALL(%s)",
            (tickers_list,),
        )
        candidates = cur.fetchone()[0]
    if active > 0 and candidates / active > _MAX_DELIST_RATIO:
        raise ValueError(
            f"mass delist blocked: {candidates}/{active} active tickers "
            f"({candidates / active:.1%}) > {_MAX_DELIST_RATIO:.0%} — 부분 fetch 의심"
        )
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE stocks
               SET delisted_at = %s, updated_at = NOW()
             WHERE delisted_at IS NULL
               AND ticker != ALL(%s)
            """,
            (on_date, tickers_list),
        )
        return cur.rowcount
