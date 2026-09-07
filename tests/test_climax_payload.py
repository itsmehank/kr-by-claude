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

    # (#44 Task 5 리뷰) climax/topping 병합 충돌 수리 — bare quality_flag 는
    # 노출하지 않고 quality_flag_climax/_topping 로만 분리 노출
    assert "quality_flag" not in gates
    assert gates["quality_flag_climax"] is False
    assert gates["quality_flag_topping"] is False

    # 기존 키 보존 (additive 확인)
    assert "conditions_summary" in payload
    assert "market_direction_gate" in payload
    assert "current_metrics" in payload
    # (#99) 시계열 사본 키는 payload 에서 제거 — daily.csv/weekly_ohlcv.csv 로 이동.
    # daily_ohlcv 는 open/high/low 가 고유하므로 유지.
    assert "weekly_ohlcv_recent_104w" not in payload
    assert "indicators_recent_60d" not in payload
    assert "daily_ohlcv_recent_60d" in payload


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


def test_build_payload_quality_flag_climax_topping_split(db):
    """(#44 Task 5 리뷰) left_censored(<50 주) 종목: compute_climax_gates 는
    quality_flag 포함 전체 키를 None 으로 반환(anchor 계약)하지만
    compute_topping_gates 의 quality_flag 는 anchor 와 무관하게 항상 계산되는
    bool — payload_builder 가 이 둘을 quality_flag_climax/_topping 로 분리
    노출해야 하고, 충돌 원인이던 bare 'quality_flag' 키는 노출하지 않아야 한다."""
    ticker = "CLPD4"
    _seed_stock(db, ticker)

    start = date(2018, 1, 5)
    weekly = _weekly_rows(_drift(40, 1000.0, 980.0), start)  # 40주 < 50 → left_censored
    _seed_weekly(db, ticker, weekly)
    on_date = weekly[-1]["week_end"]

    _seed_daily_indicators(db, ticker, on_date, 25, [False] * 25)

    payload = build_payload(db, ticker, on_date=on_date)
    gates = payload["climax_topping_gates"]

    assert gates["left_censored"] is True
    assert "quality_flag" not in gates
    assert gates["quality_flag_climax"] is None
    assert isinstance(gates["quality_flag_topping"], bool)


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


# ===== 항목 ① (2026-09-07): 일간 극값 신호 T5·T6·TA-d payload 통합 =====

from api.services.payload_builder import _anchor_baseline_start, _fetch_daily_since  # noqa: E402


def _seed_daily_prices(db, ticker, rows: list[tuple[date, float, float, float, int]]):
    """(date, high, low, close, volume) — open=close 로 시드. volume=0 이고 high=low=0 이면
    zero-bar(거래정지) 행."""
    with db.cursor() as cur:
        for d, h, l, c, v in rows:
            o = c if c else 0.0
            cur.execute(
                """INSERT INTO daily_prices
                     (ticker, date, open, high, low, close, adj_close, volume, value)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT DO NOTHING""",
                (ticker, d, o, h, l, c, c, v, int(v * c)),
            )
    db.commit()


def test_anchor_baseline_start_is_iso_week_monday():
    assert _anchor_baseline_start("2018-04-06") == date(2018, 4, 2)   # 금요일 → 월요일
    assert _anchor_baseline_start("2018-04-05") == date(2018, 4, 2)   # 목요일(금 휴장) → 같은 월요일
    assert _anchor_baseline_start("2018-04-02") == date(2018, 4, 2)   # 월요일 자기 자신


def test_fetch_daily_since_includes_one_prior_row_and_skips_zero_bar(db):
    ticker = "CLPD5"
    _seed_stock(db, ticker)
    d0 = date(2020, 3, 2)  # 월
    rows = [
        (d0 - timedelta(days=7), 101.0, 99.0, 100.0, 1000),   # 전주 월 — 직전 1행 후보(더 오래됨)
        (d0 - timedelta(days=3), 103.0, 101.0, 102.0, 1000),  # 전주 금 — 직전 1행(채택)
        (d0, 0.0, 0.0, 0.0, 0),                                # 월 zero-bar → 제외
        (d0 + timedelta(days=1), 110.0, 104.0, 108.0, 1000),  # 화 = baseline 첫 실거래일
        (d0 + timedelta(days=2), 111.0, 107.0, 109.0, 1000),
        (d0 + timedelta(days=9), 120.0, 110.0, 119.0, 1000),  # on_date 이후 → look-ahead 제외
    ]
    _seed_daily_prices(db, ticker, rows)
    got = _fetch_daily_since(db, ticker, d0, on_date=d0 + timedelta(days=2))
    assert [r["date"] for r in got] == [
        (d0 - timedelta(days=3)).isoformat(),
        (d0 + timedelta(days=1)).isoformat(),
        (d0 + timedelta(days=2)).isoformat(),
    ]
    assert got[0]["close"] == 102.0


def test_build_payload_daily_extremes_anchored_matches_direct_compute(db):
    """anchored: payload 의 T5/T6/TA-d 가 (anchor 주 월요일 이후 일봉 + 직전 1행) 을
    compute_daily_extremes 에 직접 넣은 결과와 일치. 기존 T3/T4 입력(마지막 20행) 불변."""
    ticker = "CLPD6"
    _seed_stock(db, ticker)
    start = date(2018, 1, 5)
    wrows = _drift(65, 1000.0, 980.0) + [(1100.0, 260_000)] \
        + [(1100.0 + 15 * i, 110_000) for i in range(1, 20)]
    weekly = _weekly_rows(wrows, start)
    _seed_weekly(db, ticker, weekly)
    on_date = weekly[-1]["week_end"]
    anchor_week = find_anchor([{**w, "week_end": w["week_end"].isoformat()} for w in weekly])
    assert anchor_week["anchor_week"] == weekly[65]["week_end"].isoformat()

    # anchor 주 월요일 −5일 ~ on_date 까지 연속 일봉(주말 포함 — 날짜 비교만 쓰임).
    # anchor 주 첫날(월) +20% 돌파일, 이후 완만 상승, 오늘 +5%.
    monday = _anchor_baseline_start(anchor_week["anchor_week"])
    days = [(monday - timedelta(days=5 - k)) for k in range(5)] + \
           [monday + timedelta(days=k) for k in range((on_date - monday).days + 1)]
    closes = []
    c = 1000.0
    for i, d in enumerate(days):
        if d == monday:
            c *= 1.20
        elif d == on_date:
            c *= 1.05
        elif i > 0:
            c *= 1.002
        closes.append(c)
    # 오늘만 스프레드를 ±10% 로 넓혀 T6 발화 조건을 만든다(다른 날은 ±1%).
    drows = [(d, c * (1.10 if d == on_date else 1.01), c * (0.90 if d == on_date else 0.99),
              c, 100_000) for d, c in zip(days, closes)]
    _seed_daily_prices(db, ticker, drows)
    # td_dist 입력용 지표 25행(daily_prices 는 ON CONFLICT 로 기존 행 유지)
    _seed_daily_indicators(db, ticker, on_date, 25, [False] * 25)

    payload = build_payload(db, ticker, on_date=on_date)
    gates = payload["climax_topping_gates"]
    assert gates["baseline"] == "anchored"

    # 시드에서 직접 도출한 기대값(구현 helper 재호출 아님 — 동어반복 방지):
    # - T5 False: 돌파일(월, +20%) 이 baseline 에 포함되고 그 prev_close 가 baseline 이전 행
    #   에서 공급되어야만 성립. anchor_week(금) 를 시작일로 쓰거나 직전 1행을 빠뜨리면
    #   +20% 가 빠져 오늘 +5% 가 최대 → True 로 뒤집힌다.
    # - T6 True: 오늘 스프레드 20%×1.05 vs 돌파일 2%×1.2 — 오늘이 최대.
    # - TA-d False: 오늘은 상승일.
    assert gates["t5_daily_max_up_now"] is False
    assert gates["t6_daily_max_spread_now"] is True
    assert gates["ta_d_daily_max_decline_now"] is False
    # 기존 T3/T4 는 마지막 20행 경로 그대로(연속 상승 → t4 up 비율 100%)
    assert gates["t4_up_days_pct_max"] == 100.0
    assert len(payload["daily_ohlcv_recent_60d"]) <= 60


def test_build_payload_daily_extremes_none_when_left_censored(db):
    ticker = "CLPD7"
    _seed_stock(db, ticker)
    weekly = _weekly_rows(_drift(40, 1000.0, 980.0), date(2019, 1, 4))
    _seed_weekly(db, ticker, weekly)
    on_date = weekly[-1]["week_end"]
    _seed_daily_indicators(db, ticker, on_date, 25, [False] * 25)
    gates = build_payload(db, ticker, on_date=on_date)["climax_topping_gates"]
    assert gates["left_censored"] is True
    assert gates["t5_daily_max_up_now"] is None
    assert gates["t6_daily_max_spread_now"] is None
    assert gates["ta_d_daily_max_decline_now"] is None
