"""(#44 Task 5) payload_builder climax/topping 통합 — TDD."""
from datetime import date, timedelta

from api.services.payload_builder import build_payload, _dist_count_25s
from kr_pipeline.llm_runner.compute.climax_topping import find_anchor


def _seed_stock(db, ticker):
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market, sector) "
            "VALUES (%s, 'P', 'KOSPI', '전기·전자') ON CONFLICT DO NOTHING",
            (ticker,),
        )
    db.commit()


def _drift(n: int, top: float, bot: float, vol: int = 100_000) -> list[tuple[float, int]]:
    """(kr_pipeline.llm_runner.compute.climax_topping 테스트와 동일 원칙) 완만한
    하락 드리프트 — close<SMA 엄격 부등호가 항상 성립하게 정확 상수 평탄 구간을
    피한다."""
    step = (top - bot) / max(n - 1, 1)
    return [(top - step * i, vol) for i in range(n)]


def _weekly_rows(rows: list[tuple[float, int]], start: date) -> list[dict]:
    return [
        {
            "week_end": start + timedelta(weeks=i),
            "open": p, "high": p * 1.02, "low": p * 0.98, "close": p, "volume": v,
        }
        for i, (p, v) in enumerate(rows)
    ]


def _seed_weekly(db, ticker, rows: list[dict]):
    with db.cursor() as cur:
        for r in rows:
            cur.execute(
                """INSERT INTO weekly_prices
                     (ticker, week_end_date, open, high, low, close, adj_close,
                      volume, value, trading_days)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,5)
                   ON CONFLICT DO NOTHING""",
                (ticker, r["week_end"], r["open"], r["high"], r["low"], r["close"],
                 r["close"], r["volume"], r["volume"] * r["close"]),
            )
    db.commit()


def _seed_daily_indicators(db, ticker, on_date: date, n: int, dist_flags: list):
    """마지막(=on_date) 부터 거슬러 n일 연속 daily_prices+daily_indicators 시드.
    dist_flags 는 오래된→최신 순(길이 n)의 distribution_day_flag 값(None 허용)."""
    assert len(dist_flags) == n
    with db.cursor() as cur:
        for i in range(n):
            d = on_date - timedelta(days=(n - 1 - i))
            close = 80000.0 + i * 10
            cur.execute(
                """INSERT INTO daily_prices
                     (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, close, close * 1.01, close * 0.99, close, close,
                 1_000_000, 1_000_000 * close),
            )
            flag = dist_flags[i]
            sma_200 = 70000.0 if i == n - 1 else None
            cur.execute(
                """INSERT INTO daily_indicators
                     (ticker, date, adj_close, volume, sma_200, distribution_day_flag)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, close, 1_000_000, sma_200, flag),
            )
    db.commit()


def test_build_payload_climax_topping_gates_anchor_consistent(db):
    """anchored 케이스: 시드한 주봉으로 직접 find_anchor 를 돌린 결과와
    payload 의 climax_topping_gates 가 anchor_week/left_censored/no_transition
    전부 일치해야 한다 — payload_builder 가 실제로 climax_topping 모듈을
    호출해 통합했는지 검증."""
    ticker = "CLPD1"
    _seed_stock(db, ticker)

    start = date(2018, 1, 5)
    rows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
        + [(1100.0 + 15 * i, 110_000) for i in range(1, 20)]
    weekly = _weekly_rows(rows, start)
    _seed_weekly(db, ticker, weekly)

    on_date = weekly[-1]["week_end"]
    expected = find_anchor([
        {**w, "week_end": w["week_end"].isoformat()} for w in weekly
    ])
    assert expected["left_censored"] is False and expected["no_transition"] is False

    # dist 결측 없는 25행(td_dist_ok/sma200 은 별도 테스트에서 검증)
    _seed_daily_indicators(db, ticker, on_date, 25, [False] * 25)

    payload = build_payload(db, ticker, on_date=on_date)

    assert "climax_topping_gates" in payload
    gates = payload["climax_topping_gates"]
    assert gates["anchor_week"] == expected["anchor_week"]
    assert gates["left_censored"] == expected["left_censored"]
    assert gates["no_transition"] == expected["no_transition"]
    assert gates["baseline"] == "anchored"

    # 기존 키 보존 (additive 확인)
    assert "conditions_summary" in payload
    assert "weekly_ohlcv_recent_104w" in payload
    assert "market_direction_gate" in payload
    assert "current_metrics" in payload


def test_build_payload_dist_count_partial_missing_yields_none(db):
    """마지막 25행 중 distribution_day_flag None 이 하나라도 있으면
    td_dist_ok 는 None(보수) — 조용한 과소계수 금지."""
    ticker = "CLPD2"
    _seed_stock(db, ticker)

    start = date(2018, 1, 5)
    # left_censored 유도(40주 <= 50주) — anchor 탐색 자체가 불가한 단순 케이스로
    # dist 게이트 독립성만 검증
    weekly = _weekly_rows(_drift(40, 1000.0, 980.0), start)
    _seed_weekly(db, ticker, weekly)
    on_date = weekly[-1]["week_end"]

    flags = [True] * 12 + [None] + [False] * 12  # 길이 25, 결측 1개 포함
    _seed_daily_indicators(db, ticker, on_date, 25, flags)

    payload = build_payload(db, ticker, on_date=on_date)
    gates = payload["climax_topping_gates"]

    assert gates["left_censored"] is True
    assert gates["td_dist_ok"] is None


def test_build_payload_supporting_ext_sma200_pct_from_indicators(db):
    """supporting_ext_sma200_pct 는 indicators_recent_60d 마지막 행의
    sma_200·adj_close 로 계산 — compute_climax_gates 의 None 을 override."""
    ticker = "CLPD3"
    _seed_stock(db, ticker)

    start = date(2018, 1, 5)
    weekly = _weekly_rows(_drift(40, 1000.0, 980.0), start)
    _seed_weekly(db, ticker, weekly)
    on_date = weekly[-1]["week_end"]

    _seed_daily_indicators(db, ticker, on_date, 25, [False] * 25)
    # 마지막 행 close=80000+24*10=80240, sma_200=70000 (helper 고정)
    expected_close = 80000.0 + 24 * 10
    expected_sma200 = 70000.0
    expected_pct = (expected_close / expected_sma200 - 1) * 100

    payload = build_payload(db, ticker, on_date=on_date)
    gates = payload["climax_topping_gates"]

    assert gates["supporting_ext_sma200_pct"] == expected_pct


def test_dist_count_25s_none_below_25_rows():
    rows = [{"distribution_day_flag": True} for _ in range(24)]
    assert _dist_count_25s(rows) is None


def test_dist_count_25s_none_when_any_flag_missing():
    rows = [{"distribution_day_flag": True} for _ in range(24)] + [{"distribution_day_flag": None}]
    assert _dist_count_25s(rows) is None


def test_dist_count_25s_counts_true_over_last_25():
    rows = [{"distribution_day_flag": False} for _ in range(10)] \
        + [{"distribution_day_flag": True} for _ in range(5)] \
        + [{"distribution_day_flag": False} for _ in range(20)]
    # last 25 rows: 5(True) 중 앞 5행이 25행 window 안에 포함되는지 계산
    last_25 = rows[-25:]
    expected = sum(1 for r in last_25 if r["distribution_day_flag"] is True)
    assert _dist_count_25s(rows) == expected
