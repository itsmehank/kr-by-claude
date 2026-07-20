"""DB 쓰기 — weekly_classification, trigger_evaluation_log, entry_params."""
from __future__ import annotations

import copy
import logging
import math
from datetime import date, datetime, timedelta, time as dt_time
import json

from psycopg import Connection

from kr_pipeline.common.thresholds import (
    ENTRY_STOP_PCT_FROM_PIVOT_FLOOR,
    ENTRY_TARGET_PCT_MIN,
    ENTRY_TARGET_PCT_MAX,
    ENTRY_WEIGHT_PCT_MIN,
    ENTRY_WEIGHT_PCT_MAX,
    ENTRY_TRIGGER_BUFFER_MAX,
    GATE_PROMOTION_PRICE_RATIO,
    PIVOT_EXTENDED_BAND_MULT,
    PIVOT_PRICE_OFFSET,
)
from kr_pipeline.common.krx import krx_tick_size
from kr_pipeline.llm_runner.gates import apply_phase1_gates
from kr_pipeline.llm_runner.risk_flags import RISK_FLAGS_TAXONOMY

log = logging.getLogger(__name__)

_VALID_CLASSIFICATIONS = frozenset({"entry", "watch", "ignore"})
_VALID_DECISIONS = frozenset({"go_now", "wait", "abort"})


def _validate_classification(result: dict) -> str:
    c = result.get("classification")
    if c not in _VALID_CLASSIFICATIONS:
        raise ValueError(f"invalid classification: {c!r} (expected entry/watch/ignore)")
    return c


def _validate_decision(result: dict) -> str:
    d = result.get("decision")
    if d not in _VALID_DECISIONS:
        raise ValueError(f"invalid decision: {d!r} (expected go_now/wait/abort)")
    return d


def _clean_risk_flags(flags) -> list[str]:
    """RISK_FLAGS_TAXONOMY 밖 값 drop + log.warning. None/비list → []."""
    if not isinstance(flags, list):
        return []
    cleaned, dropped = [], []
    for f in flags:
        (cleaned if f in RISK_FLAGS_TAXONOMY else dropped).append(f)
    if dropped:
        log.warning("dropped unknown risk_flags: %s", dropped)
    return cleaned


def _measurements_json(result: dict) -> str | None:
    """measurements 블록에 최상위 contraction_count/contraction_depths_pct 를 병합해 JSON 문자열로.

    VCP footprint(최상위 출력)가 버려지지 않게 measurements 감사 블록에 합친다.
    measurements·contraction 둘 다 없으면 None(기존 None 동작 보존).
    """
    m = result.get("measurements")
    cc = result.get("contraction_count")
    cd = result.get("contraction_depths_pct")
    if m is None and cc is None and cd is None:
        return None
    blob = dict(m) if isinstance(m, dict) else {}
    if cc is not None:
        blob["contraction_count"] = cc
    if cd is not None:
        blob["contraction_depths_pct"] = cd
    return json.dumps(blob)


def _watch_reason(result: dict) -> str | None:
    """watch_reason 은 classification=='watch' 일 때만 저장 (그 외 None 강제).

    분류가 watch 가 아니면(혹은 phase1 게이트가 강등했으면) 사유를 비워
    'watch_reason 은 watch 일 때만' 불변식 보장 + breakout_from_watch 오발화 방지.

    (#44 D2-b) 6번째 값 'suspected_climax_stage_indeterminate' 존재(§6.1 climax
    판정 불능 — Task 9 프롬프트 개정). 이 함수는 값을 검증하지 않는 의도적
    pass-through — enum 강제 지점은 여기가 아니라 프롬프트(§8.5 표·출력 스키마)다.
    이 사유는 trigger_gate.ALLOWED_WATCH_REASONS 에 비포함이므로 breakout_from_watch
    가 발화하지 않고 promotion 으로만 흐른다(go_now 금지) — extended 와 동급 취급,
    재트리거 비대상. 회귀 고정: tests/test_climax_shadow_backstop.py.
    """
    if result.get("classification") != "watch":
        return None
    return result.get("watch_reason")


# [design judgment] 분류 pivot/종가 sanity 밴드 — book 근거 아님(자릿수·소수점 오류
# 탐지 휴리스틱)이라 thresholds.py SSOT 비등재. SOFT 전용(저장 차단 안 함).
_PIVOT_CLOSE_BAND = (0.3, 3.0)

# (#1) base_start_date '근접' 관측 분류 폭 (일). 판정 무영향 — 관측 라벨링 전용이라
# thresholds.py SSOT 비등재 (이슈 #1 실측의 그룹핑 기준 재사용).
_BASE_NEAR_DAYS = 10


def _to_date_or_none(v):
    if v is None:
        return None
    # datetime 이 date 의 서브클래스라 순서 중요 — datetime 먼저 (#39 리뷰)
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return None


def _finite_or_none(v) -> float | None:
    """numeric → float, 비유한값(NaN/Inf)은 None — jsonb 는 NaN 토큰을 거부한다(#39 리뷰)."""
    if v is None:
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _pivot_continuity(
    conn, *, symbol: str, result: dict, classified_at, analyzed_for_date,
) -> dict | None:
    """(#1) 직전 활성(entry/watch) 분류 대비 pivot/base 연속성 관측 (dict, 판정 무영향).

    같은 베이스(base_start_date 동일)로 재확인됐는데 pivot 만 재판독되는 현상
    (이슈 #1, 실측 최대 ±22%)을 하위 로직·사람이 인지할 수 있게 기록만 한다.
    모집단 의미론 = get_active_monitoring 과 동치: 이 행 *직전의 최신 분류 1건*
    (분류 무관)을 보고, 그것이 entry/watch 가 아니면(ignore 개재 = 활성 기준선
    단절) None — 오래된 entry/watch 를 건너뛰어 잡으면 재확립 베이스가 주간
    재판독으로 오계수된다(#39 리뷰). 직전 조회는 유효일이 **strictly 이른** 행만 —
    look-ahead(미래 행 참조) 차단과 동시에 **같은 유효일 행도 제외**(#39 재리뷰:
    같은 날 재실행의 LLM 비결정성 편차가 same-base 재판독으로 오계수되면 관측
    분포가 오염되고 재실행 1:1 비교 금지 규율이 데이터에 스며든다). 유효일 폴백
    캐스팅(classified_at::date)은 소비자 get_active_monitoring 과 동일(#39 재리뷰
    — UTC 고정 캐스팅은 레거시 행에서 소비자와 하루 어긋날 수 있었음).
    ★재실행 1:1 비교 금지 규율 비저촉 — 재실행이 아니라 서로 다른 주(as_of)의
    정상 분류 간 관측 (docs/pivot-reanalysis-tradeoff.md).
    """
    effective = analyzed_for_date or classified_at.date()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT classified_at, classification, pivot_price, base_start_date, pattern
              FROM weekly_classification
             WHERE symbol = %s
               AND COALESCE(analyzed_for_date, classified_at::date) < %s
             ORDER BY COALESCE(analyzed_for_date, classified_at::date) DESC,
                      classified_at DESC
             LIMIT 1
            """,
            (symbol, effective),
        )
        prev = cur.fetchone()
    if prev is None:
        return None
    prev_at, prev_cls, prev_pv, prev_bsd, prev_pattern = prev
    if prev_cls not in ("entry", "watch"):
        # 직전 최신 행이 ignore 등 → 활성 기준선 단절. 연속성 비교 대상 아님.
        return None

    new_bsd = _to_date_or_none(result.get("base_start_date"))
    prev_bsd = _to_date_or_none(prev_bsd)
    if prev_bsd is not None and new_bsd is not None:
        delta_days = abs((new_bsd - prev_bsd).days)
        if delta_days == 0:
            continuity = "same"
        elif delta_days <= _BASE_NEAR_DAYS:
            continuity = "near"
        else:
            continuity = "different"
    else:
        delta_days = None
        continuity = "unknown"

    new_pv = _finite_or_none(result.get("pivot_price"))
    prev_pv = _finite_or_none(prev_pv)
    change_pct = (
        round((new_pv - prev_pv) / prev_pv * 100, 4)
        if new_pv is not None and prev_pv is not None and prev_pv != 0
        else None
    )
    new_pattern = result.get("pattern")
    return {
        "prev_classified_at": prev_at.isoformat(),
        "prev_pivot_price": prev_pv,
        "pivot_change_pct": change_pct,
        "base_start_delta_days": delta_days,
        "base_continuity": continuity,
        "prev_pattern": prev_pattern,
        "pattern_changed": (
            new_pattern != prev_pattern
            if new_pattern is not None and prev_pattern is not None
            else None
        ),
    }
# (#23) §4.7 표 기반 pivot_basis — anchor 가 base 내부 고점이라 pivot ≤ base_high+0.1
# 이 성립하고 +0.1 오프셋 규칙이 적용되는 집합. pocket pivot 등 표 밖 basis 는
# base_high 초과가 정당하므로 비대상 (HARD 미검사 사유와 동일 — docstring 참조).
_PIVOT_TABLE_BASES = frozenset(
    {"handle_high", "range_high", "final_T_high", "mid_W_peak"}
)


def _validate_classification_prices(conn, result: dict, *, symbol: str, as_of) -> list[str]:
    """분류 숫자의 부호·대소·범위 sanity (P1-2 Part A).

    HARD(ValueError, fail-closed): present 값이 구조적으로 불가능한 경우만 —
        pivot/base_high/base_low ≤ 0, base_low ≥ base_high, base_low > pivot,
        confidence ∉ [0,1]. 오염 pivot 은 평일 트리거 게이트(close>pivot)의
        상류 입력이라 저장 자체를 거부한다(미저장 시 다음 사이클 재분류로 복구).
        pivot ≤ base_high 는 검사하지 않음 — pocket pivot(포켓피벗일 종가)은
        base_high 초과가 정당하다.
    SOFT(list 반환 → sanity_warnings 컬럼): 단정 불가한 의심값 —
        entry 인데 pivot 없음(watch 는 base_forming 등 pivot NULL 정상이라 비대상),
        pivot 이 as_of 최근 adj_close 대비 밴드 밖. as_of None/종가 부재 시 밴드
        검사만 skip. risk_flags(LLM payload 되먹임)와 분리된 쓰기 전용 컬럼.
    """
    pv = result.get("pivot_price")
    bh = result.get("base_high")
    bl = result.get("base_low")

    hard: list[str] = []
    for k, v in (("pivot_price", pv), ("base_high", bh), ("base_low", bl)):
        if v is not None and v <= 0:
            hard.append(f"{k}={v} (<=0)")
    if bl is not None and bh is not None and bl >= bh:
        hard.append(f"base_low={bl} >= base_high={bh}")
    if bl is not None and pv is not None and bl > pv:
        hard.append(f"base_low={bl} > pivot_price={pv}")
    c = result.get("confidence")
    if c is not None and not (0 <= c <= 1):
        hard.append(f"confidence={c} (not in [0,1])")
    if hard:
        raise ValueError(f"classification sanity violation ({symbol}): " + "; ".join(hard))

    warns: list[str] = []
    if result.get("classification") == "entry" and pv is None:
        warns.append("sanity_missing_pivot_for_actionable")
    if pv is not None and as_of is not None:
        # (#38 리뷰) 비교 종가는 LLM payload 의 current_metrics.close 와 같은 소스
        # (daily_prices 권위, payload_builder._build_current_metrics 와 동일 형태) —
        # daily_indicators 가 지연 적재된 날 어제 종가와 비교하는 오경고 방지.
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(adj_close, close) FROM daily_prices "
                "WHERE ticker = %s AND date <= %s ORDER BY date DESC LIMIT 1",
                (symbol, as_of),
            )
            row = cur.fetchone()
        close = float(row[0]) if row and row[0] else None
        if close is not None:
            ratio = float(pv) / close
            if not (_PIVOT_CLOSE_BAND[0] <= ratio <= _PIVOT_CLOSE_BAND[1]):
                warns.append("sanity_pivot_far_from_price")
            # (#23) §8.5 밴드 정합 — LLM 이 적용한 entry/valid_base/extended 경계가
            # 실제 close/pivot 위치와 맞는지 사후검증 (LLM 산술 실수 탐지, SOFT).
            pos = close / float(pv)
            band_lo = GATE_PROMOTION_PRICE_RATIO
            band_hi = PIVOT_EXTENDED_BAND_MULT
            # watch_reason 은 저장 정규화(_watch_reason)와 동일하게 watch 에만 유효 —
            # 비-watch 의 잔류 watch_reason 으로 오경고 금지 (#38 리뷰).
            wr = _watch_reason(result)
            if result.get("classification") == "entry" and pos > band_hi:
                # 상단 위반만 검사 — 하단(pos < 0.95) entry 는 §4.5 pocket pivot
                # (base 내부 저위치 진입)이 정당해 구분 불가, 오경고 방지 (#38 리뷰).
                warns.append("sanity_band_mismatch_entry")
            elif wr == "valid_base_awaiting_breakout" and pos >= band_lo:
                warns.append("sanity_band_mismatch_valid_base")
            elif wr == "extended" and pos <= band_hi:
                warns.append("sanity_band_mismatch_extended")

    # (#23) §4.7 pivot 산술 사후검증 — 표 기반 basis 한정 (SOFT).
    # 허용 집합은 §4.7 리터럴(+0.1)이 아니라 §7 KR 관례가 기준 (#38 재리뷰):
    # "base high + 1 tick (typically +10 or +100 KRW ... but base_high alone is
    # acceptable)". KRW 는 정수가라 +0.1 만 정답으로 인정하면 §7 준수 출력 대부분이
    # 경고를 받아 사후검증이 노이즈로 포화 — 진짜 이상치가 묻힌다.
    if pv is not None and result.get("pivot_basis") in _PIVOT_TABLE_BASES:
        if bh is not None:
            tick = krx_tick_size(float(bh))
            if float(pv) > float(bh) + tick + 1e-6:
                warns.append("sanity_pivot_above_base_high")
        # 오프셋 관례 검사: 앵커 값을 아는 basis(range_high == base_high, 같은 값)
        # 에서만, 정수 앵커 문맥에 한해 — handle_high 등은 앵커가 base_high 와
        # 다른 가격이라 base_high 정수성이 프록시가 못 된다 (#38 리뷰).
        # 허용: {앵커 그대로, 앵커+0.1(§4.7 리터럴), 앵커+1 tick(§7 관례)}.
        if (
            result.get("pivot_basis") == "range_high"
            and bh is not None
            and abs(float(bh) - round(float(bh))) < 1e-6
        ):
            anchor = float(bh)
            allowed = (anchor, anchor + PIVOT_PRICE_OFFSET, anchor + krx_tick_size(anchor))
            if not any(abs(float(pv) - a) < 1e-3 for a in allowed):
                warns.append("sanity_pivot_offset_rule")

    if warns:
        log.warning("classification sanity warnings %s: %s (pivot=%s)", symbol, warns, pv)
    return warns


def insert_classification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    result: dict,
    source: str,
    llm_meta: dict,
    analyzed_for_date: date | None = None,
) -> None:
    """weekly_classification 에 분류 결과 INSERT.

    저장 직전 Phase 1 2-A 후처리 게이트 적용 (handle_quality 주입 +
    2-E tier 강등 + 2-F 기록). prompt 갱신은 Phase 2 일임.

    source: 'weekend' | 'daily_delta'
    """
    _validate_classification(result)
    _original = copy.deepcopy(result)
    # (#44 Task 7) verdict_original — 게이트 적용 전 LLM 원본 classification.
    verdict_original = _original.get("classification")
    try:
        # SAVEPOINT 격리: 게이트 내부 SQL 오류가 트랜잭션을 aborted 로 만들면
        # 아래 INSERT 가 InFailedSqlTransaction 으로 실패해 LLM 비용을 쓴 분류가
        # 통째로 유실된다. 중첩 transaction(=savepoint)으로 fail-soft 를 실질화.
        with conn.transaction():
            result, triggered_rules = apply_phase1_gates(conn, symbol, classified_at, result)
    except Exception as e:
        log.warning(
            "[phase1-gate] failed symbol=%s — 게이트 미적용 원본 분류 저장 (fail-soft): %s",
            symbol, e,
        )
        result = _original
        triggered_rules = None

    # P1-2 Part A: 게이트 뒤(=최종 저장값) 가격 sanity. HARD 위반은 ValueError 로
    # 저장 거부(fail-closed) — 호출자(weekend 워커/daily_delta 루프)가 종목 단위 격리.
    sanity_warnings = _validate_classification_prices(
        conn, result, symbol=symbol, as_of=analyzed_for_date,
    )

    # (#1) pivot 재판독 연속성 관측 — INSERT 전에 직전 분류를 조회해야 하므로 이 위치.
    # fail-soft: 관측 전용 헬퍼의 어떤 실패도 본 INSERT(LLM 비용 지출분)를 막으면
    # 안 된다 — phase1 게이트와 동일 원칙 (#39 리뷰). try/except 는 Python 예외만
    # 흡수하므로 SAVEPOINT(with conn.transaction())로 서버측 SQL 오류의 트랜잭션
    # 오염까지 격리 (#39 재리뷰 — 격리 없으면 본 INSERT 가 InFailedSqlTransaction).
    try:
        with conn.transaction():
            continuity_info = _pivot_continuity(
                conn, symbol=symbol, result=result,
                classified_at=classified_at, analyzed_for_date=analyzed_for_date,
            )
        pivot_continuity = (
            json.dumps(continuity_info, allow_nan=False)
            if continuity_info is not None
            else None
        )
    except Exception as e:
        log.warning(
            "[pivot-continuity] failed symbol=%s — 관측 생략 (fail-soft): %s",
            symbol, e,
        )
        continuity_info = None
        pivot_continuity = None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO weekly_classification
              (symbol, classified_at, analyzed_for_date, market, classification, pattern,
               pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date,
               risk_flags, confidence, reasoning,
               source,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens, llm_model,
               triggered_rules,
               measurements,
               watch_reason,
               sanity_warnings,
               pivot_continuity,
               verdict_original)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s, %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s)
            ON CONFLICT (symbol, classified_at) DO NOTHING
            """,
            (
                symbol,
                classified_at,
                analyzed_for_date,
                market,
                result["classification"],
                result.get("pattern"),
                result.get("pivot_price"),
                result.get("pivot_basis"),
                result.get("base_high"),
                result.get("base_low"),
                result.get("base_depth_pct"),
                result.get("base_start_date"),
                json.dumps(_clean_risk_flags(result.get("risk_flags", []))),
                result.get("confidence"),
                result.get("reasoning"),
                source,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
                llm_meta.get("model"),
                json.dumps(triggered_rules) if triggered_rules is not None else None,
                _measurements_json(result),
                _watch_reason(result),
                json.dumps(sanity_warnings) if sanity_warnings else None,
                pivot_continuity,
                verdict_original,
            ),
        )
        # (#1) same-base 재판독 경고는 행이 실제 저장된 경우에만 — ON CONFLICT 로
        # 버려진 행에 대한 유령 경고 방지 (#39 리뷰).
        if (
            cur.rowcount == 1
            and continuity_info is not None
            and continuity_info["base_continuity"] == "same"
            and continuity_info["pivot_change_pct"] not in (None, 0.0)
        ):
            log.warning(
                "[pivot-continuity] same-base pivot reread %s: %s -> %s (%+.2f%%)",
                symbol, continuity_info["prev_pivot_price"],
                result.get("pivot_price"), continuity_info["pivot_change_pct"],
            )


def insert_backfill_classification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    result: dict,
    source: str,
    llm_meta: dict,
    analyzed_for_date: date,
    table: str = "classification_backfill",
) -> None:
    """백필 분류 결과를 `table` (기본 classification_backfill) 에 INSERT (멱등: symbol+analyzed_for_date).

    insert_classification 과 동일하게 Phase 1 2-A 후처리 게이트 적용. freeze 는 만들지 않음.
    table 파라미터로 대상 테이블 지정 가능 (allowlist: classification_backfill,
    backtest_classification, recall_audit_classification).
    """
    if table not in ("classification_backfill", "backtest_classification",
                     "recall_audit_classification"):
        raise ValueError(f"insert_backfill_classification: unknown table {table!r}")
    _validate_classification(result)
    _original = copy.deepcopy(result)
    # (#44 Task 7) verdict_original — 게이트 적용 전 LLM 원본 classification.
    verdict_original = _original.get("classification")
    try:
        gate_at = datetime.combine(analyzed_for_date + timedelta(days=1), dt_time.min)
        # SAVEPOINT 격리 — insert_classification 과 동일 (SQL 오류 fail-soft 실질화)
        with conn.transaction():
            result, triggered_rules = apply_phase1_gates(conn, symbol, gate_at, result)
    except Exception as e:
        log.warning(
            "[phase1-gate] backfill failed symbol=%s — 게이트 미적용 원본 저장 (fail-soft): %s",
            symbol, e,
        )
        result = _original
        triggered_rules = None

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {table}
              (symbol, classified_at, analyzed_for_date, market, classification, pattern,
               pivot_price, pivot_basis, base_high, base_low, base_depth_pct, base_start_date,
               risk_flags, confidence, reasoning,
               source,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens, llm_model,
               triggered_rules,
               measurements,
               watch_reason,
               verdict_original)
            VALUES (%s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s,
                    %s, %s, %s, %s,
                    %s,
                    %s,
                    %s,
                    %s)
            ON CONFLICT (symbol, analyzed_for_date) DO NOTHING
            """,
            (
                symbol,
                classified_at,
                analyzed_for_date,
                market,
                result["classification"],
                result.get("pattern"),
                result.get("pivot_price"),
                result.get("pivot_basis"),
                result.get("base_high"),
                result.get("base_low"),
                result.get("base_depth_pct"),
                result.get("base_start_date"),
                json.dumps(_clean_risk_flags(result.get("risk_flags", []))),
                result.get("confidence"),
                result.get("reasoning"),
                source,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
                llm_meta.get("model"),
                json.dumps(triggered_rules) if triggered_rules is not None else None,
                _measurements_json(result),
                _watch_reason(result),
                verdict_original,
            ),
        )


def insert_disqualification(
    conn: Connection,
    *,
    symbol: str,
    classified_at: datetime,
    market: str,
    reason: str = "minervini_pass=false — 미너비니 자격 상실(시스템 강등)",
    analyzed_for_date: date | None = None,
) -> None:
    """시스템 발 강등 행 직접 INSERT (LLM/Phase1 게이트 우회).

    disqualified 는 결정론 이벤트이지 LLM 분류가 아니므로 apply_phase1_gates 를 거치지 않는다.
    pattern/pivot/confidence/triggered_rules 는 NULL.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO weekly_classification
              (symbol, classified_at, analyzed_for_date, market, classification, source, reasoning)
            VALUES (%s, %s, %s, %s, 'disqualified', 'system_disqualify', %s)
            ON CONFLICT (symbol, classified_at) DO NOTHING
            """,
            (symbol, classified_at, analyzed_for_date, market, reason),
        )


def insert_trigger_log(
    conn: Connection,
    *,
    symbol: str,
    evaluated_at: datetime,
    trigger_type: str,
    close: float,
    volume: int,
    pivot_price: float,
    result: dict,
    prior_classification_at: datetime,
    llm_meta: dict,
    analyzed_for_date: date | None = None,
) -> None:
    """trigger_evaluation_log 에 (5b) 결과 INSERT."""
    decision = _validate_decision(result)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO trigger_evaluation_log
              (symbol, evaluated_at, trigger_type,
               close, volume, pivot_price,
               decision, confidence, reasoning, abort_reason,
               analyzed_for_date,
               prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens, llm_model)
            VALUES (%s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s,
                    %s,
                    %s, %s, %s, %s)
            ON CONFLICT (symbol, evaluated_at) DO NOTHING
            """,
            (
                symbol,
                evaluated_at,
                trigger_type,
                close,
                volume,
                pivot_price,
                decision,
                result.get("confidence"),
                result.get("reasoning"),
                result.get("abort_reason"),
                analyzed_for_date,
                prior_classification_at,
                llm_meta.get("duration_s"),
                llm_meta.get("input_tokens"),
                llm_meta.get("output_tokens"),
                llm_meta.get("model"),
            ),
        )


_ENTRY_PARAMS_REQUIRED = (
    "entry_mode", "pivot_price", "trigger_price", "current_price",
    "stop_loss_price", "stop_loss_pct_from_pivot", "stop_loss_pct_from_current_price",
    "suggested_weight_pct", "expected_target_price", "expected_target_pct",
    "pattern_basis", "entry_window_days", "max_chase_pct_from_pivot",
    "breakout_volume_requirement", "observed_breakout_volume_ratio",
)


def _normalize_entry_params(result: dict) -> dict:
    """§9 LLM 출력 → entry_params 저장용 dict.

    리네임(stop_loss_price→stop_loss, suggested_weight_pct→position_size_pct),
    파생(entry_price=trigger_price, risk_reward_ratio 계산), §9 부재 메타는 None.
    필수 §9 키 누락 시 ValueError(조용한 0행 방지).
    """
    for k in _ENTRY_PARAMS_REQUIRED:
        if k not in result:
            raise ValueError(f"entry_params schema drift: missing §9 field '{k}'")
    target_pct = result["expected_target_pct"]
    stop_pct = result["stop_loss_pct_from_current_price"]
    rr = None
    if target_pct is not None and stop_pct not in (None, 0):
        rr = target_pct / abs(stop_pct)
        if abs(rr) >= 1000:  # NUMERIC(5,2) 범위 밖 → 오버플로(=조용한 실패) 방지
            rr = None
    n = {
        "entry_mode": result["entry_mode"],
        "pivot_price": result["pivot_price"],
        "trigger_price": result["trigger_price"],
        "current_price": result["current_price"],
        "entry_price": result["trigger_price"],
        "stop_loss": result["stop_loss_price"],
        "stop_loss_pct_from_pivot": result["stop_loss_pct_from_pivot"],
        "stop_loss_pct_from_current_price": result["stop_loss_pct_from_current_price"],
        "stop_loss_basis": None,
        "expected_target_price": result["expected_target_price"],
        "expected_target_pct": result["expected_target_pct"],
        "risk_reward_ratio": rr,
        "position_size_pct": result["suggested_weight_pct"],
        "position_size_basis": None,
        "pattern_basis": result["pattern_basis"],
        "entry_window_days": result["entry_window_days"],
        "max_chase_pct_from_pivot": result["max_chase_pct_from_pivot"],
        "breakout_volume_requirement": result["breakout_volume_requirement"],
        "observed_breakout_volume_ratio": result["observed_breakout_volume_ratio"],
        "known_warnings": result.get("known_warnings", []),
        # §9 는 other_warnings 를 배열로도 낼 수 있는데 컬럼은 TEXT → list/dict 면 JSON 문자열로
        # 직렬화(PG array-literal 로 어그러지게 저장되는 것 방지, known_warnings 와 일관).
        "other_warnings": _as_text(result.get("other_warnings")),
        "notes": result.get("notes"),
    }
    return _validate_entry_params_sanity(n)


# D-3 sanity 의 책 근거 범위는 SSOT(thresholds.py ENTRY_* — P1-7 승격) 가 정의.
# #21 이후 생산측(entry_params_calc.py)도 같은 SSOT 를 import — 생산·검증 단일 정의.
# (구 프롬프트 calculate_entry_params_v2_0.md 는 RETIRED — 웹 표시용 아카이브만.)


def _validate_entry_params_sanity(n: dict) -> dict:
    """매수계획 숫자의 부호·대소·범위 sanity 검증 (D-3).

    HARD(거부, ValueError): 가격 ≤ 0 / 손절가 ≥ 진입가 / 목표가 ≤ 진입가 /
        stop_pct 양수 / target_pct ≤ 0 — long 돌파 진입에서 항상 깨지는 계획.
    SOFT(경고, known_warnings 에 sanity_* 마커): 책 권장 범위 이탈(방향은 맞음).
    None(미제공)은 비교 불가라 해당 검사 skip — scope=주어진 값의 정합성.

    entry_params 는 go_now 실매수 신호에만 저장되므로 HARD 위반은 fail-closed(저장 안 함).
    """
    entry = n.get("entry_price")
    stop = n.get("stop_loss")
    target = n.get("expected_target_price")

    hard: list[str] = []
    for k in ("pivot_price", "trigger_price", "current_price", "entry_price",
              "stop_loss", "expected_target_price"):
        v = n.get(k)
        if v is not None and v <= 0:
            hard.append(f"{k}={v} (<=0)")
    if stop is not None and entry is not None and stop >= entry:
        hard.append(f"stop_loss={stop} >= entry_price={entry}")
    if target is not None and entry is not None and target <= entry:
        hard.append(f"expected_target_price={target} <= entry_price={entry}")
    sp_pivot = n.get("stop_loss_pct_from_pivot")
    sp_cur = n.get("stop_loss_pct_from_current_price")
    tp = n.get("expected_target_pct")
    if sp_pivot is not None and sp_pivot > 0:
        hard.append(f"stop_loss_pct_from_pivot={sp_pivot} (>0)")
    if sp_cur is not None and sp_cur > 0:
        hard.append(f"stop_loss_pct_from_current_price={sp_cur} (>0)")
    if tp is not None and tp <= 0:
        hard.append(f"expected_target_pct={tp} (<=0)")
    if hard:
        raise ValueError("entry_params sanity violation: " + "; ".join(hard))

    warns: list[str] = []
    if sp_pivot is not None and not (ENTRY_STOP_PCT_FROM_PIVOT_FLOOR <= sp_pivot < 0.0):
        warns.append("sanity_stop_pct_from_pivot_out_of_book_range")
    if tp is not None and not (ENTRY_TARGET_PCT_MIN <= tp <= ENTRY_TARGET_PCT_MAX):
        warns.append("sanity_target_pct_out_of_book_range")
    wt = n.get("position_size_pct")
    if wt is not None and not (ENTRY_WEIGHT_PCT_MIN <= wt <= ENTRY_WEIGHT_PCT_MAX):
        warns.append("sanity_weight_out_of_book_range")
    piv, trg = n.get("pivot_price"), n.get("trigger_price")
    if piv is not None and trg is not None and not (piv < trg <= piv * ENTRY_TRIGGER_BUFFER_MAX):
        warns.append("sanity_trigger_out_of_book_range")
    win = n.get("entry_window_days")
    if win is not None and win < 1:
        warns.append("sanity_entry_window_too_short")
    if warns:
        n["known_warnings"] = list(n.get("known_warnings") or []) + warns
        log.warning("entry_params soft sanity warnings %s (entry=%s stop=%s target=%s)",
                    warns, entry, stop, target)
    return n


def _as_text(v):
    """list/dict 면 JSON 문자열로, 그 외(문자열/None)는 그대로 — TEXT 컬럼 저장용."""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return v


def insert_entry_params(
    conn: Connection,
    *,
    symbol: str,
    signal_at: datetime,
    result: dict,
    trigger_evaluation_at: datetime,
    prior_classification_at: datetime,
    llm_meta: dict,
    analyzed_for_date: date | None = None,
) -> None:
    """entry_params 에 (6) 결과 INSERT (§9 → 정규화 → 저장)."""
    n = _normalize_entry_params(result)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO entry_params
              (symbol, signal_at, analyzed_for_date,
               entry_mode, pivot_price, trigger_price, current_price, entry_price,
               stop_loss, stop_loss_pct_from_pivot, stop_loss_pct_from_current_price, stop_loss_basis,
               expected_target_price, expected_target_pct, risk_reward_ratio,
               position_size_pct, position_size_basis,
               pattern_basis, entry_window_days, max_chase_pct_from_pivot,
               breakout_volume_requirement, observed_breakout_volume_ratio,
               known_warnings, other_warnings, notes,
               trigger_evaluation_at, prior_classification_at,
               llm_call_duration_s, llm_input_tokens, llm_output_tokens, llm_model)
            VALUES (%s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s)
            ON CONFLICT (symbol, signal_at) DO NOTHING
            """,
            (
                symbol, signal_at, analyzed_for_date,
                n["entry_mode"], n["pivot_price"], n["trigger_price"], n["current_price"], n["entry_price"],
                n["stop_loss"], n["stop_loss_pct_from_pivot"], n["stop_loss_pct_from_current_price"], n["stop_loss_basis"],
                n["expected_target_price"], n["expected_target_pct"], n["risk_reward_ratio"],
                n["position_size_pct"], n["position_size_basis"],
                n["pattern_basis"], n["entry_window_days"], n["max_chase_pct_from_pivot"],
                n["breakout_volume_requirement"], n["observed_breakout_volume_ratio"],
                json.dumps(n["known_warnings"]), n["other_warnings"], n["notes"],
                trigger_evaluation_at, prior_classification_at,
                llm_meta.get("duration_s"), llm_meta.get("input_tokens"), llm_meta.get("output_tokens"),
                llm_meta.get("model"),
            ),
        )
