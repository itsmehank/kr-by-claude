# kr_pipeline/indicators/store.py
"""daily_indicators / weekly_indicators UPSERT + Phase 단위 UPDATE."""
from datetime import date
from psycopg import Connection

from kr_pipeline.common.thresholds import C8_RS_RATING_MIN


PHASE_A_COLUMNS_DAILY = [
    "ticker", "date", "adj_close",
    "sma_10", "sma_21", "sma_50", "sma_150", "sma_200",
    "w52_high", "w52_low", "pct_from_52w_high", "pct_from_52w_low",
    "rs_line", "rs_line_52w_high", "rs_line_52w_high_date",
    "rs_line_at_52w_high", "rs_line_uptrend_6w", "rs_line_uptrend_13w",
    "rs_line_not_declining_7m",
    "minervini_c1", "minervini_c2", "minervini_c3",
    "minervini_c4", "minervini_c5", "minervini_c6", "minervini_c7",
    # V2: 거래량 지표
    "volume",
    "avg_volume_50d",
    "volume_ratio_50d",
    "pocket_pivot_flag",
    "volume_dry_up_flag",
    "up_down_volume_ratio_50d",
    "distribution_day_flag",
]


def upsert_daily_indicators_phase_a(conn: Connection, rows: list[dict]) -> int:
    """Phase A 결과 UPSERT. rs_rating, c8, pass 는 건드리지 않음."""
    if not rows:
        return 0

    cols = PHASE_A_COLUMNS_DAILY
    placeholders = ", ".join(["%s"] * len(cols))
    cols_sql = ", ".join(cols)
    update_sql = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ("ticker", "date")])

    sql = f"""
        INSERT INTO daily_indicators ({cols_sql}, updated_at)
        VALUES ({placeholders}, NOW())
        ON CONFLICT (ticker, date) DO UPDATE
           SET {update_sql}, updated_at = NOW()
    """

    tuples = [tuple(r.get(c) for c in cols) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, tuples)
        return cur.rowcount


def update_daily_indicators_rs_rating(conn: Connection, rows: list[tuple]) -> int:
    """rs_rating 만 UPDATE.

    rows: [(ticker, date, rs_rating_int_or_None), ...]
    """
    if not rows:
        return 0

    with conn.cursor() as cur:
        # TEMP TABLE + JOIN UPDATE (Fix #3 패턴, 빠름)
        cur.execute("""
            CREATE TEMP TABLE _rs_updates (
                ticker VARCHAR(10),
                date DATE,
                rs_rating SMALLINT,
                PRIMARY KEY (ticker, date)
            ) ON COMMIT DROP
        """)
        cur.executemany(
            "INSERT INTO _rs_updates (ticker, date, rs_rating) VALUES (%s, %s, %s)",
            rows,
        )
        cur.execute("""
            UPDATE daily_indicators d
               SET rs_rating = u.rs_rating, updated_at = NOW()
              FROM _rs_updates u
             WHERE d.ticker = u.ticker AND d.date = u.date
        """)
        return cur.rowcount


def update_daily_indicators_minervini_pass(
    conn: Connection,
    start_date: date,
    end_date: date,
) -> int:
    """단일 SQL UPDATE 로 c8 (rs_rating >= C8_RS_RATING_MIN) 와 minervini_pass (c1..c8 ALL TRUE) 계산."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daily_indicators
               SET minervini_c8 = (rs_rating >= %s),
                   minervini_pass = (
                       minervini_c1 IS TRUE AND minervini_c2 IS TRUE AND
                       minervini_c3 IS TRUE AND minervini_c4 IS TRUE AND
                       minervini_c5 IS TRUE AND minervini_c6 IS TRUE AND
                       minervini_c7 IS TRUE AND (rs_rating >= %s)
                   ),
                   updated_at = NOW()
             WHERE date BETWEEN %s AND %s
            """,
            (C8_RS_RATING_MIN, C8_RS_RATING_MIN, start_date, end_date),
        )
        return cur.rowcount


# Weekly 동일 패턴
PHASE_A_COLUMNS_WEEKLY = [
    "ticker", "week_end_date", "adj_close",
    "sma_10w", "sma_30w", "sma_40w",
    "w52_high", "w52_low", "pct_from_52w_high", "pct_from_52w_low",
    "rs_line", "rs_line_52w_high", "rs_line_52w_high_date",
    "rs_line_at_52w_high", "rs_line_uptrend_6w", "rs_line_uptrend_13w",
    "rs_line_not_declining_7m",
    "minervini_c1", "minervini_c2", "minervini_c3",
    "minervini_c4", "minervini_c5", "minervini_c6", "minervini_c7",
    # V2: 거래량 지표
    "volume",
    "avg_volume_10w",
    "volume_ratio_10w",
    "up_down_volume_ratio_10w",
]


def upsert_weekly_indicators_phase_a(conn: Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = PHASE_A_COLUMNS_WEEKLY
    placeholders = ", ".join(["%s"] * len(cols))
    cols_sql = ", ".join(cols)
    update_sql = ", ".join([f"{c} = EXCLUDED.{c}" for c in cols if c not in ("ticker", "week_end_date")])
    sql = f"""
        INSERT INTO weekly_indicators ({cols_sql}, updated_at)
        VALUES ({placeholders}, NOW())
        ON CONFLICT (ticker, week_end_date) DO UPDATE
           SET {update_sql}, updated_at = NOW()
    """
    tuples = [tuple(r.get(c) for c in cols) for r in rows]
    with conn.cursor() as cur:
        cur.executemany(sql, tuples)
        return cur.rowcount


def update_weekly_indicators_rs_rating(conn: Connection, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TEMP TABLE _rs_updates_w (
                ticker VARCHAR(10),
                week_end_date DATE,
                rs_rating SMALLINT,
                PRIMARY KEY (ticker, week_end_date)
            ) ON COMMIT DROP
        """)
        cur.executemany(
            "INSERT INTO _rs_updates_w (ticker, week_end_date, rs_rating) VALUES (%s, %s, %s)",
            rows,
        )
        cur.execute("""
            UPDATE weekly_indicators w
               SET rs_rating = u.rs_rating, updated_at = NOW()
              FROM _rs_updates_w u
             WHERE w.ticker = u.ticker AND w.week_end_date = u.week_end_date
        """)
        return cur.rowcount


def update_weekly_indicators_minervini_pass(
    conn: Connection,
    start_date: date,
    end_date: date,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE weekly_indicators
               SET minervini_c8 = (rs_rating >= 70),
                   minervini_pass = (
                       minervini_c1 IS TRUE AND minervini_c2 IS TRUE AND
                       minervini_c3 IS TRUE AND minervini_c4 IS TRUE AND
                       minervini_c5 IS TRUE AND minervini_c6 IS TRUE AND
                       minervini_c7 IS TRUE AND (rs_rating >= 70)
                   ),
                   updated_at = NOW()
             WHERE week_end_date BETWEEN %s AND %s
            """,
            (start_date, end_date),
        )
        return cur.rowcount


def update_daily_rs_gate_from_weekly(
    conn: Connection, start_date: date, end_date: date
) -> int:
    """각 daily 행의 rs_line_not_declining_7m 을 최신 week_end_date ≤ date 의 weekly 값으로 미러.

    게이트는 주봉에서 계산(D3) → 후보 쿼리(daily 단일 테이블) 가 읽도록 daily 에 복사.
    weekly_indicators 가 먼저 적재돼 있어야 함.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE daily_indicators d
               SET rs_line_not_declining_7m = (
                     SELECT w.rs_line_not_declining_7m
                       FROM weekly_indicators w
                      WHERE w.ticker = d.ticker AND w.week_end_date <= d.date
                      ORDER BY w.week_end_date DESC
                      LIMIT 1
                   ),
                   updated_at = NOW()
             WHERE d.date BETWEEN %s AND %s
            """,
            (start_date, end_date),
        )
        return cur.rowcount
