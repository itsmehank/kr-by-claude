# kr_pipeline/llm_runner/compute/climax_topping.py
"""(#44 D1) climax/topping anchor 전 이력 탐색 — 순수 함수.

순수 함수 — DB 접근 없음, pandas 미사용(리스트 산술만). 주봉 이력에서 가장 최근
Stage 1→2 전환 주(anchor)를 뒤에서부터 탐색한다. 확정 D1: "전 이력 중 가장 최근"
전환을 anchor 로 채택 — 과거의 오래된 전환은 이후 Stage 4 재하락으로 무효화된 것으로
간주(test_anchor_resets_after_stage4).

null 규약(보수, governance 4-2): 이력이 CLIMAX_ANCHOR_VOL_AVG_WEEKS(50)주 이하 = 탐색 자체가
불가능한 결측 → left_censored=True, 게이트 전부 None. 이력은 충분하나 전환 조건을 만족하는
주가 없으면(예: 줄곧 Stage 2 상승) no_transition=True — anchor 의존 필드는 left_censored 와
동일하게 None(#169, 2026-09-09: 책 정의 "since the beginning of the move" 는 식별된 시작점을
전제하므로 시작점 부재 시 신호 미정의 — 일간 T5/T6/TA-d 의 #157 Q-8 판정을 주간에 일관 적용).
anchor 비의존 게이트(T3·T4·G0·T-B·T-C·td_dist_ok)는 계속 계산된다. 모드 자체는 기록용으로
유지(baseline="no_transition"). 구 #44 규약(P1 충족 간주 + 전체 이력 극값)은 superseded.

탐색 하한 `range(n - 1, W - 1, -1)`: i=W(=50) 포함 — off-by-one 가드. i 를 W-1까지로
좁히면 n=W+1(=51) 부근에서 유효한 i=W 후보를 건너뛰어 no_transition 으로 폴스루하는
회귀가 발생한다(라운드 2 리뷰 N2 발견).

anchor 판정(가장 최근 주 w, index i) — 네 조건 동일 주 동시 성립(#158 Fix α, 2026-09-07):
- C1 Stage1 재형성: 직전 CLIMAX_ANCHOR_STAGE1_MIN_WEEKS(4)주 연속 close < 그 주의 40주 SMA
- C2 40주 SMA 의 TURNUP_WEEKS(4)주 기울기 ≤ +CLIMAX_ANCHOR_FLAT_BAND_PCT(2.0)% (평탄/하락)
- C3 w 에서 volume ≥ BREAKOUT_VOL_FLOOR × 50주 평균 거래량 (돌파 거래량)
- C5 close > s30 AND close > s40 (Stage 2 = 이평 위)
구 C4(s30/s40 이 4주 전 대비 상승, [EXTENDS]) 는 #158 에서 제거 — Stage 1 직후 돌파 주에서
SMA 가 아직 하락 중이라 C1 과 같은 주에 양립 불가, O'Neil 돌파 정의·Minervini 전환 기준에
"돌파 주 동시 성립" 근거 없음. 재진입(옛 돌파 → Stage 1 재형성 → 재돌파) 시 앵커는 재돌파
주로 이동한다(현 사이클의 시작 = 책의 "beginning of the move").
"""
from __future__ import annotations

from kr_pipeline.common.thresholds import (
    BREAKOUT_VOL_FLOOR,
    CLIMAX_ANCHOR_FLAT_BAND_PCT,
    CLIMAX_ANCHOR_STAGE1_MIN_WEEKS,
    CLIMAX_ANCHOR_TURNUP_WEEKS,
    CLIMAX_ANCHOR_VOL_AVG_WEEKS,
    CLIMAX_GAIN_PCT,
    CLIMAX_MATURITY_WEEKS,
    CLIMAX_SCOPE_CORRECTION_PCT,
    CLIMAX_SCOPE_PAST_HIGH_WEEKS,
    CLIMAX_UP_DAYS_PCT,
    CLIMAX_UP_DAYS_WINDOW_MAX,
    CLIMAX_UP_DAYS_WINDOW_MIN,
    STOCK_DISTRIBUTION_COUNT_25D,
    TOPPING_BELOW_10W_WEEKS,
)

_GATE_KEYS = (
    "maturity_weeks", "maturity_ok", "p2_best_roll_pct", "p2_is_steepest",
    "p2_accel_ok", "t1_max_spread_now", "t2_max_volume_now", "t3_gap_up_today",
    "t4_up_days_pct_max", "t4_ok", "supporting_ext_sma200_pct", "scope_active",
    "baseline", "quality_flag",
)


def _sma(vals: list[float], i: int, n: int) -> float | None:
    """vals[i] 를 마지막으로 하는 n 주 단순이동평균. 창이 부족하면 None."""
    return sum(vals[i - n + 1 : i + 1]) / n if i + 1 >= n else None


def find_anchor(weekly: list[dict]) -> dict:
    """주봉 이력(오름차순)에서 가장 최근 Stage 1→2 전환 주를 탐색한다.

    weekly: [{week_end, open, high, low, close, volume}, ...] (adj 전 이력, zero-bar 제외 입력)
    반환: {"anchor_week": str|None, "left_censored": bool, "no_transition": bool,
           "weeks_since": int|None}
    """
    closes = [w["close"] for w in weekly]
    vols = [w["volume"] or 0 for w in weekly]
    n = len(weekly)
    W = CLIMAX_ANCHOR_VOL_AVG_WEEKS
    if n <= W:  # 이력 ≤50주 = 탐색 불가 결측 (실효 경계 문서 일치 — 검토 하 수리)
        return {"anchor_week": None, "left_censored": True,
                "no_transition": False, "weeks_since": None}
    k = CLIMAX_ANCHOR_TURNUP_WEEKS
    s1 = CLIMAX_ANCHOR_STAGE1_MIN_WEEKS
    for i in range(n - 1, W - 1, -1):  # i=W(=50) 포함 — n=51 폴스루가 no_transition 으로 새는 회귀 방지(라운드 2 N2)
        s30, s40 = _sma(closes, i, 30), _sma(closes, i, 40)
        v_avg = sum(vols[i - W : i]) / W
        if None in (s30, s40) or v_avg <= 0:
            continue
        # C1 Stage1 재형성: 직전 s1(4)주 연속 close < 그 주의 40주 SMA (검토 중6)
        stage1 = all(
            (sm := _sma(closes, j, 40)) is not None and closes[j] < sm
            for j in range(i - s1, i))
        # C2 40주 SMA 평탄/하락: 직전 주 기준 k(4)주 기울기 ≤ +FLAT_BAND
        prev_s40, prev_s40k = _sma(closes, i - 1, 40), _sma(closes, i - 1 - k, 40)
        slope_ok = (prev_s40 and prev_s40k
                    and (prev_s40 - prev_s40k) / prev_s40k * 100 <= CLIMAX_ANCHOR_FLAT_BAND_PCT)
        # (#158 Fix α) 구 C4 "s30/s40 이 k주 전 대비 상승" 은 제거 — Stage 1 직후 돌파 주와
        # 시간적으로 양립 불가한 [EXTENDS] 조건(책 근거 없음)이라 전환 89.9% 를 차단했다.
        if (stage1 and slope_ok and vols[i] >= BREAKOUT_VOL_FLOOR * v_avg      # C3
                and closes[i] > s30 and closes[i] > s40):                        # C5
            return {"anchor_week": weekly[i]["week_end"], "left_censored": False,
                    "no_transition": False, "weeks_since": n - 1 - i}
    return {"anchor_week": None, "left_censored": False,
            "no_transition": True, "weeks_since": None}


def _roll_gain(closes: list[float], t: int, k: int, start_idx: int) -> float | None:
    """closes[t] 를 closes[t-k] 대비 % 수익으로 (baseline 구간[start_idx:] 밖 참조 금지)."""
    if t - k < start_idx:
        return None
    prev = closes[t - k]
    if prev is None or prev <= 0:
        return None
    return (closes[t] / prev - 1) * 100


def compute_climax_gates(weekly: list[dict], daily_20d: list[dict], anchor: dict) -> dict:
    """(#44 Task 3) §6.1 climax 게이트 산술 — 순수 함수.

    weekly: [{week_end, open, high, low, close, volume, gap_before?, adj_hl?}, ...] (오름차순,
        find_anchor 와 동일 입력 — zero-bar 주 제외). gap_before(기본 False) = 직전 행과의 사이에
        zero-bar 주가 있었음, adj_hl(기본 True) = high·low 가 adj 소스(payload_builder
        _fetch_weekly_full 규약). 둘 다 T1 유효성에만 쓰인다(#156).
    daily_20d: [{date, open, high, low, close, volume}, ...] (오름차순, 최근 거래일 꼬리)
    anchor: find_anchor(weekly) 의 반환 dict.

    반환 키: maturity_weeks, maturity_ok, p2_best_roll_pct, p2_is_steepest, p2_accel_ok,
    t1_max_spread_now, t2_max_volume_now, t3_gap_up_today, t4_up_days_pct_max, t4_ok,
    supporting_ext_sma200_pct(값만 — 70% 판정은 프롬프트 잔류), scope_active,
    baseline("anchored"|"no_transition"|None), quality_flag.

    모드: left_censored → 전부 None(baseline 포함) / no_transition(#169) → anchor 의존 필드
    (maturity_weeks·maturity_ok·p2_*·t1·t2·scope_active) None, anchor 비의존 t3/t4 는 계산,
    baseline="no_transition"(기록용) / anchored → baseline="anchored",
    maturity_weeks=anchor["weeks_since"].

    quality_flag: 입력 주봉에 close<=0/None 존재 시 True + weekly 값에 의존하는 게이트
    (p2_*, t1/t2, scope_active) 는 None 강등(daily 기반인 t3/t4 는 영향 없음).
    """
    if anchor["left_censored"]:
        return dict.fromkeys(_GATE_KEYS)

    n = len(weekly)
    closes = [w["close"] for w in weekly]
    last_idx = n - 1
    quality_flag = any(c is None or c <= 0 for c in closes)

    if anchor["no_transition"]:
        # (#169) 시작점 부재 = anchor 의존 신호 미정의 — left_censored 와 동일하게 None.
        baseline = "no_transition"
        start_idx = None
        maturity_weeks = None
        maturity_ok = None
    else:
        baseline = "anchored"
        weeks_since = anchor["weeks_since"]
        start_idx = last_idx - weeks_since
        maturity_weeks = weeks_since
        maturity_ok = maturity_weeks >= CLIMAX_MATURITY_WEEKS

    if quality_flag or start_idx is None:
        p2_best_roll_pct = p2_is_steepest = p2_accel_ok = None
        t1_max_spread_now = t2_max_volume_now = None
        scope_active = None
    else:
        # P2: k∈{1,2,3} 풀링 — best_now(마지막 주 종점) ≥ CLIMAX_GAIN_PCT AND
        # best_now ≥ best_ever(baseline 구간 전체 최대, 동률 허용 — 프롬프트보다 엄격=보수)
        best_ever = None
        for t in range(start_idx, n):
            for k in (1, 2, 3):
                g = _roll_gain(closes, t, k, start_idx)
                if g is not None and (best_ever is None or g > best_ever):
                    best_ever = g
        best_now = None
        for k in (1, 2, 3):
            g = _roll_gain(closes, last_idx, k, start_idx)
            if g is not None and (best_now is None or g > best_now):
                best_now = g
        p2_best_roll_pct = best_now
        p2_is_steepest = (best_now is not None and best_ever is not None
                           and best_now >= best_ever)
        p2_accel_ok = bool(p2_is_steepest and best_now is not None
                            and best_now >= CLIMAX_GAIN_PCT)

        # T1 (#156, 2026-09-08): 마지막 주 스프레드 **비율** (high−low)/prev_week_close 가
        # baseline(anchor 주 포함, 각 주의 prev = 직전 주 종가) 최대인가 — 반로그 척도(HMMS
        # Ch.10 #4), 일간 T6 과 동일 분모. 유효성(①의 Q-6·Q-7 준용): 직전 주와의 사이에
        # zero-bar 주가 있으면 그 쌍 제외(gap_before), high·low 가 adj 소스가 아닌 주 제외
        # (adj_hl=False — prev_close=adj_close 는 NOT NULL). 오늘이 그런 주면 T1=None.
        # T2 는 책 정의대로 거래량 절대값(불변).
        sp: dict[int, float] = {}
        for i in range(max(start_idx, 1), n):
            w = weekly[i]
            prev = closes[i - 1]
            if prev is None or prev <= 0 or w.get("gap_before") or not w.get("adj_hl", True):
                continue
            sp[i] = (w["high"] - w["low"]) / prev * 100
        t1_max_spread_now = None if last_idx not in sp else sp[last_idx] >= max(sp.values())
        vols = [w["volume"] or 0 for w in weekly]
        t2_max_volume_now = vols[last_idx] >= max(vols[start_idx:n])

        # scope: 고점 주(baseline 구간 종가 최대, 동률 시 최신 우선) 경과 ≤2주
        # AND 고점 대비 조정 ≤15% — 2주 초과 시 즉시 False(지배 규약, STALE 분기 없음)
        high_idx, high_close = start_idx, closes[start_idx]
        for t in range(start_idx, n):
            if closes[t] >= high_close:
                high_close, high_idx = closes[t], t
        weeks_since_high = last_idx - high_idx
        if weeks_since_high > CLIMAX_SCOPE_PAST_HIGH_WEEKS:
            scope_active = False
        else:
            correction_pct = (high_close - closes[last_idx]) / high_close * 100
            scope_active = correction_pct <= CLIMAX_SCOPE_CORRECTION_PCT

    # T3: daily 마지막 행 open > 직전 행 high (사실만)
    if len(daily_20d) >= 2:
        t3_gap_up_today = daily_20d[-1]["open"] > daily_20d[-2]["high"]
    else:
        t3_gap_up_today = None

    # T4: 종점=마지막 거래일 고정(trailing), 길이 7~15 전부 검사한 상승일 비율의 max.
    # 데이터 부족(7일 미만 비교 가능) → None.
    flags = [daily_20d[i]["close"] > daily_20d[i - 1]["close"]
             for i in range(1, len(daily_20d))]
    num_flags = len(flags)
    if num_flags < CLIMAX_UP_DAYS_WINDOW_MIN:
        t4_up_days_pct_max = None
        t4_ok = None
    else:
        upper = min(CLIMAX_UP_DAYS_WINDOW_MAX, num_flags)
        t4_up_days_pct_max = max(
            sum(flags[-length:]) / length * 100
            for length in range(CLIMAX_UP_DAYS_WINDOW_MIN, upper + 1))
        t4_ok = t4_up_days_pct_max >= CLIMAX_UP_DAYS_PCT

    return {
        "maturity_weeks": maturity_weeks,
        "maturity_ok": maturity_ok,
        "p2_best_roll_pct": p2_best_roll_pct,
        "p2_is_steepest": p2_is_steepest,
        "p2_accel_ok": p2_accel_ok,
        "t1_max_spread_now": t1_max_spread_now,
        "t2_max_volume_now": t2_max_volume_now,
        "t3_gap_up_today": t3_gap_up_today,
        "t4_up_days_pct_max": t4_up_days_pct_max,
        "t4_ok": t4_ok,
        # daily 입력엔 sma200 이 없어 주봉 근사가 불가 — 값 미공급(None). Task 5 payload
        # 통합 시 indicators 로 공급할지 결정(#44 Task 3 report 의 concern 참조).
        "supporting_ext_sma200_pct": None,
        "scope_active": scope_active,
        "baseline": baseline,
        "quality_flag": quality_flag,
    }


_DAILY_KEYS = ("t5_daily_max_up_now", "t6_daily_max_spread_now", "ta_d_daily_max_decline_now")


def compute_daily_extremes(daily_hist: list[dict] | None, baseline_start: str | None,
                           anchor: dict, quality_flag: bool = False) -> dict:
    """(항목 ① 2026-09-07) 일간 climax/topping 극값 신호 3종 — 순수 함수.

    daily_hist: [{date(ISO), open, high, low, close, volume, zero_bar?, adj_hl?}, ...] 오름차순.
        zero-bar(거래정지) 행도 **포함**해 넘긴다(zero_bar=True) — 연속 세션 판정에 쓰이고
        값 자체는 쓰지 않는다. adj_hl(기본 True) = high·low 가 adj 소스인지(payload_builder
        _fetch_daily_since 규약). anchored 모드에서는 baseline 첫날의 prev_close 를 공급하기
        위해 baseline_start **직전 1행**(zero-bar 여부 무관, 최신 1행)을 포함해 넘긴다.
    baseline_start: baseline 첫 거래일(ISO) — anchor 주 첫 거래일(W-SUN 그룹 min(date), Q-1 B).
    anchor: find_anchor(weekly) 반환 dict.
    quality_flag: 주봉 quality_flag(close<=0/None 존재). True 면 anchor 의존 게이트 관례대로
        전부 None(Q-5 판정 A).

    정의(전문가 확정 사양, 분모 전부 prev_close — Q-2):
    - T5  t5_daily_max_up_now      = 오늘 상승일(close>prev) AND up_pct >= baseline 상승일 max
          up_pct = (close−prev_close)/prev_close. [HMMS Ch.10 Climax Tops #1 + TTLC Ch.9]
    - T6  t6_daily_max_spread_now  = 오늘 spread_pct >= baseline 전 거래일 max
          spread_pct = (high−low)/prev_close. [TTLC Ch.9 단독 — HMMS 는 주간판만]
    - TA-d ta_d_daily_max_decline_now = 오늘 하락일(close<prev) AND down_pct >= baseline 하락일 max
          down_pct = (prev_close−close)/prev_close. [TTLC Ch.9 + TLSMW Ch.5]

    규약:
    - 동률 >= (기존 P2/T1/T-A 관례 — 가격제한 동률 실재, 노출 축소 방향). 오늘이 상승일/
      하락일 아니면 T5/TA-d 는 False(자격 없음 — T-A 관례, None 아님).
    - **결측 모드**: left_censored → None. **no_transition → None**(Q-8 판정: 책 정의 "since
      the beginning of the move" 는 식별된 시작점을 전제 — 시작점 부재 시 신호 미정의. #169
      부터 주간 P2/T1/T2/T-A/T-D 거래량도 동일 규약). quality_flag → None(Q-5).
    - **연속 세션만**(Q-6 판정 C): prev 행과 해당 행 사이에 zero-bar 가 있으면 그 쌍은 baseline
      극값·오늘 판정 양쪽에서 제외. 오늘이 재개일(직전 zero-bar) 이면 3신호 None.
    - **T6 공식 유효성 조건**(Q-7 판정 A — 규칙 신설 아님): (high−low)/prev_close 는 세 값이
      같은 조정 기준일 때만 정의된다. prev_close 는 daily_prices.adj_close(NOT NULL) 로 항상
      adj 이므로, high·low 가 raw 대체된 행(adj_hl=False) 은 스프레드 후보에서 제외. 오늘이
      그런 행이면 T6 만 None(T5/TA-d 는 종가만 쓰므로 유지).
    - 비교 가능한 행이 baseline 안에 없거나 오늘을 판정할 수 없으면 None(결측).
    """
    if (anchor["left_censored"] or anchor["no_transition"] or quality_flag
            or not daily_hist or len(daily_hist) < 2):
        return dict.fromkeys(_DAILY_KEYS)

    ups: list[float] = []
    spreads: list[float] = []
    downs: list[float] = []
    today: tuple[float | None, float | None, float | None] | None = None  # (up, spread, down)
    last_idx = len(daily_hist) - 1
    prev_close: float | None = None
    gap = False  # 직전 비-zero-bar 행 이후 zero-bar 를 지났는가
    for i, row in enumerate(daily_hist):
        if row.get("zero_bar"):
            gap = True
            continue
        close = row["close"]
        in_baseline = baseline_start is None or row["date"] >= baseline_start
        computable = (prev_close is not None and prev_close > 0 and close is not None
                      and in_baseline and not gap)
        if computable:
            chg = (close - prev_close) / prev_close * 100
            up = chg if chg > 0 else None
            down = -chg if chg < 0 else None
            spread_pct = ((row["high"] - row["low"]) / prev_close * 100
                          if row.get("adj_hl", True) else None)
            if up is not None:
                ups.append(up)
            if down is not None:
                downs.append(down)
            if spread_pct is not None:
                spreads.append(spread_pct)
            if i == last_idx:
                today = (up, spread_pct, down)
        prev_close = close
        gap = False

    if today is None:  # 오늘이 zero-bar·재개일·baseline 밖·prev 부재 → 판정 불능
        return dict.fromkeys(_DAILY_KEYS)
    up_t, sp_t, down_t = today
    return {
        "t5_daily_max_up_now": up_t is not None and up_t >= max(ups),
        "t6_daily_max_spread_now": None if sp_t is None else sp_t >= max(spreads),
        "ta_d_daily_max_decline_now": down_t is not None and down_t >= max(downs),
    }


def compute_topping_gates(weekly: list[dict], dist_count_25s: int | None, anchor: dict) -> dict:
    """(#44 Task 4) §6.2 topping 게이트 산술 — 순수 함수.

    weekly: find_anchor 와 동일 입력(오름차순, adj 전 이력).
    dist_count_25s: 종목 25세션 분배일 카운트(payload_builder 산출). 결측 시 None.
    anchor: find_anchor(weekly) 의 반환 dict.

    반환 키: g0_below_10w, tb_weeks_below_10w, tb_ok, td_max_down_volume_now,
    td_dist_ok, ta_max_decline_now, tc_sma40_turndown, tc_prolonged_ok, quality_flag.

    anchor 비의존(항상 계산 — 판정 가능한 것을 null 화하지 않음, 라운드 2 N3):
    - G0 = 마지막 주 종가 < 10주 SMA.
    - T-B = G0 기준 SMA 로 마지막 주부터 trailing 연속 close<10주SMA 주수 ≥
      TOPPING_BELOW_10W_WEEKS(8) → tb_ok.
    - T-D 분배일: td_dist_ok = dist_count_25s ≥ STOCK_DISTRIBUTION_COUNT_25D(4).
      dist_count_25s 가 None 이면 td_dist_ok 도 None(null=보수 — g0/tb 와 별개 입력이라
      서로 영향 없음).
    - T-C 턴다운: tc_sma40_turndown = 40주 SMA 가 직전 주 대비 하락.

    anchor 의존(anchored → anchor 이후 baseline, no_transition · left_censored → None —
    #169 부터 두 결측 모드 동일 취급):
    - T-A: 마지막 주 전주比 하락률이 baseline 구간 하락 주 중 최대인가.
    - T-D 거래량: 마지막 주 거래량이 baseline 구간 '하락 주(전주比 종가 하락 — 브리프
      침묵으로 이 정의 채택, 명시)' 중 최대인가. baseline 내 하락 주가 전무하면
      마지막 주도 하락 주가 아니므로 False(최대가 될 자격조차 없음 — None 아님).
    - T-C prolonged(D5② — shadow 관측 전용, would_force 비참여): anchored 전용 —
      maturity(anchor["weeks_since"]) ≥ CLIMAX_MATURITY_WEEKS(18). no_transition/
      left_censored 는 None(고정 기산일이 없어 '경과 주수'가 정의되지 않음).

    quality_flag: 입력 주봉에 close<=0/None 존재 시 True + weekly 값에 의존하는 게이트
    (g0/tb/tc_sma40_turndown/ta/td거래량) None 강등(Task 3 과 동일 규약). td_dist_ok 는
    dist_count_25s 라는 별개 입력에만 의존하므로 quality_flag 와 무관하게 유지.
    """
    closes = [w["close"] for w in weekly]
    vols = [w["volume"] or 0 for w in weekly]
    n = len(weekly)
    last_idx = n - 1
    quality_flag = any(c is None or c <= 0 for c in closes)

    td_dist_ok = (None if dist_count_25s is None
                  else dist_count_25s >= STOCK_DISTRIBUTION_COUNT_25D)

    if quality_flag:
        g0_below_10w = None
        tb_weeks_below_10w = None
        tb_ok = None
        tc_sma40_turndown = None
    else:
        s10_last = _sma(closes, last_idx, 10)
        g0_below_10w = None if s10_last is None else closes[last_idx] < s10_last

        tb_weeks_below_10w = 0
        for i in range(last_idx, -1, -1):
            s10 = _sma(closes, i, 10)
            if s10 is None or not closes[i] < s10:
                break
            tb_weeks_below_10w += 1
        tb_ok = tb_weeks_below_10w >= TOPPING_BELOW_10W_WEEKS

        s40_last = _sma(closes, last_idx, 40)
        s40_prev = _sma(closes, last_idx - 1, 40) if last_idx >= 1 else None
        tc_sma40_turndown = (None if None in (s40_last, s40_prev)
                              else s40_last < s40_prev)

    if quality_flag or anchor["left_censored"] or anchor["no_transition"]:
        ta_max_decline_now = None
        td_max_down_volume_now = None
    else:
        # 하락 주(전주比 종가 하락)만 후보 — 동률 허용(>=, Task 3 P2/T1/T2 와 동일
        # 관례: "엄격 = 보수"). 마지막 주가 하락 주가 아니면 최대일 자격이 없어 False.
        start_idx = last_idx - anchor["weeks_since"]
        declines: dict[int, float] = {}
        down_vols: dict[int, float] = {}
        # anchor 주(i=start_idx) 자체도 후보에 포함하되 하락 판정은 anchor "이전" 주
        # 대비다 — §6.1 baseline 이 anchor 주를 포함하는 관례(P2/T1/T2)와 일관 정렬.
        # anchor 주는 정의상 상승 확정 주라 실발화는 사실상 없음(Task 4 리뷰 확정 해석).
        for i in range(max(start_idx, 1), n):
            prev = closes[i - 1]
            if prev is None or prev <= 0 or closes[i] >= prev:
                continue  # 하락 주가 아님 — T-A/T-D 후보에서 제외
            declines[i] = (prev - closes[i]) / prev * 100
            down_vols[i] = vols[i]
        ta_max_decline_now = (last_idx in declines
                               and declines[last_idx] >= max(declines.values()))
        td_max_down_volume_now = (last_idx in down_vols
                                   and down_vols[last_idx] >= max(down_vols.values()))

    tc_prolonged_ok = None
    if not quality_flag and not anchor["left_censored"] and not anchor["no_transition"]:
        tc_prolonged_ok = anchor["weeks_since"] >= CLIMAX_MATURITY_WEEKS

    return {
        "g0_below_10w": g0_below_10w,
        "tb_weeks_below_10w": tb_weeks_below_10w,
        "tb_ok": tb_ok,
        "td_max_down_volume_now": td_max_down_volume_now,
        "td_dist_ok": td_dist_ok,
        "ta_max_decline_now": ta_max_decline_now,
        "tc_sma40_turndown": tc_sma40_turndown,
        "tc_prolonged_ok": tc_prolonged_ok,
        "quality_flag": quality_flag,
    }
