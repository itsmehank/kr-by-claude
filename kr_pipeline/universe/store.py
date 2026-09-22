from datetime import date
import pandas as pd
from psycopg import Connection

from kr_pipeline.common.security_group import UNRESOLVED


def upsert_stocks(conn: Connection, df: pd.DataFrame) -> int:
    """security_group 지속화 = fail-open(Q-1): 값 부재/NaN → UNRESOLVED 로 INSERT 하되, 갱신 시
    UNRESOLVED 는 알려진 값을 덮어쓰지 않는다(조회 실패가 기존 판정을 지우지 않게)."""
    if df.empty:
        return 0
    rows = []
    has_sg = "security_group" in df.columns
    for _, r in df.iterrows():
        sector = r.get("sector")
        if pd.isna(sector):
            sector = None
        sg = r.get("security_group") if has_sg else None
        if sg is None or pd.isna(sg) or str(sg) == "":
            sg = UNRESOLVED
        rows.append((r["ticker"], r["name"], r["market"], sector, str(sg)))
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO stocks (ticker, name, market, sector, security_group, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (ticker) DO UPDATE
               SET name = EXCLUDED.name,
                   market = EXCLUDED.market,
                   sector = COALESCE(EXCLUDED.sector, stocks.sector),
                   -- 지속화 fail-open(Q-1): UNRESOLVED 는 알려진 값을 덮어쓰지 않는다
                   security_group = CASE WHEN EXCLUDED.security_group = 'UNRESOLVED'
                                         THEN stocks.security_group ELSE EXCLUDED.security_group END,
                   delisted_at = NULL,
                   updated_at = NOW()
            """,
            rows,
        )
        return cur.rowcount


def save_universe_raw_snapshot(conn: Connection, snapshot_date: date, df: pd.DataFrame) -> int:
    """(#195 커밋2 부수) 필터 전 유니버스 원본 응답 전량 저장 — #191 차집합 계산의 전제(KRX 재접촉 0).

    df 컬럼: ticker, name, market, security_group(없으면 UNRESOLVED). 같은 날짜 재실행은 덮어쓴다.
    """
    if df.empty:
        return 0
    sg = df["security_group"] if "security_group" in df.columns else pd.Series(UNRESOLVED, index=df.index)
    rows = [(snapshot_date, t, n, m, (g if isinstance(g, str) and g else UNRESOLVED))
            for t, n, m, g in zip(df["ticker"], df["name"], df["market"], sg)]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM universe_raw_snapshot WHERE snapshot_date = %s", (snapshot_date,))
        cur.executemany(
            "INSERT INTO universe_raw_snapshot (snapshot_date, ticker, name, market, security_group) VALUES (%s, %s, %s, %s, %s)",
            rows)
    return len(rows)


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
