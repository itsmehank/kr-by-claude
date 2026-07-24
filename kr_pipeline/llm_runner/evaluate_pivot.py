"""평일 (5b) evaluate_pivot_trigger.

결정론 트리거 게이트 통과 종목만 LLM 호출.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from psycopg import Connection

from kr_pipeline.common.thresholds import (
    BREAKOUT_VOL_PREFERRED,
    PIVOT_EXTENDED_BAND_MULT,
)
from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as evaluate_gate
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError
from kr_pipeline.llm_runner.load import get_active_with_current
from kr_pipeline.llm_runner.store import insert_trigger_log
from kr_pipeline.trade_management.store import get_open_positions

# (#45) 결정론 extended 게이트의 wait 사유 — 사전등록 코호트 질의 키(동등비교 전용).
# weekly watch_reason='extended'(주 단위)와 별개 값(일 단위 경로) — 리네임 없음.
EXTENDED_WAIT_REASON = "extended_past_buy_range"

# (#45) 인터셉트 대상 = go_now 로 이어질 수 있는 상향 트리거만.
# promotion 은 §3.3 이 go_now 를 전면 금지(매수 위험 0), invalidation 은 하향 — 비대상.
_EXTENDED_INTERCEPT_TRIGGERS = frozenset({"breakout", "breakout_from_watch"})

# (#74) strict 1.5× 거래량 게이트 — cup_without_handle 전용(F4 사전등록 코호트 키).
STRICT_NH_WAIT_REASON = "volume_below_strict_no_handle"

# (#74) 보유 억제(dedupe) — 상향 트리거 전부. invalidation(하향)은 보유자 필수
# 신호라 절대 비억제. 체인 순서 = dedupe → extended → strict (F4 분모 오염 방지).
POSITION_SUPPRESSED_WAIT_REASON = "suppressed_position_held"
_UPWARD_TRIGGERS = frozenset({"breakout", "breakout_from_watch", "promotion"})


log = logging.getLogger("kr_pipeline.llm_runner.evaluate_pivot")


def _already_evaluated_symbols(conn, as_of) -> set:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT symbol FROM trigger_evaluation_log "
            "WHERE COALESCE(analyzed_for_date, (evaluated_at AT TIME ZONE 'UTC')::date) = %s",
            (as_of,),
        )
        return {r[0] for r in cur.fetchall()}


def _aborted_since_classification(conn, active: list[dict]) -> set:
    """현재 분류(classified_at)에 대해 abort 판정난 종목 집합.

    abort 기록 시 store 가 prior_classification_at = 그 시점 classified_at 을 박아두므로,
    abort 행의 prior_classification_at == active 행의 현재 classified_at 이면 "현재 분류에
    대한 abort" 다. 재분류되면 classified_at 이 바뀌어 옛 abort 의 prior 와 불일치 → 자동 해제.
    """
    symbols = [a["symbol"] for a in active]
    if not symbols:
        return set()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol, prior_classification_at "
            "FROM trigger_evaluation_log "
            "WHERE decision = 'abort' AND symbol = ANY(%s)",
            (symbols,),
        )
        abort_pairs = {(r[0], r[1]) for r in cur.fetchall()}
    result = set()
    for a in active:
        cls_at = a.get("classified_at")
        # classified_at None 이면 매칭 안 함(안전 기본값). abort prior 가 NULL 이면 (sym,NULL)
        # 쌍이 어떤 timestamp 와도 불일치 → 자연 skip-안함. .get() 必須(subscript 아님):
        # test_evaluate_pivot_guard 의 mock active 는 classified_at 키가 없어 KeyError 회피.
        if cls_at is not None and (a["symbol"], cls_at) in abort_pairs:
            result.add(a["symbol"])
    return result


def run(
    conn: Connection,
    *,
    dry_run: bool = False,
    as_of: date | None = None,
    limit: int | None = None,
    force: bool = False,
) -> dict:
    if as_of is None:
        as_of = date.today()

    if force and limit:
        raise ValueError("force=True 와 limit 동시 사용 금지: force 는 as_of 전체를 replace 하므로 limit 로 자르면 삭제된 행이 재생성되지 않는다")

    active = get_active_with_current(conn, as_of=as_of)

    # 결정론 트리거 게이트 통과 종목 추출
    triggered: list[tuple[dict, str]] = []
    for a in active:
        if not all(
            a.get(k) is not None
            for k in ("close", "pivot_price", "volume", "avg_volume_50d", "sma_50")
        ):
            continue
        trig = evaluate_gate(
            close=a["close"],
            pivot_price=a["pivot_price"],
            volume=a["volume"],
            avg_volume_50d=a["avg_volume_50d"],
            stop_loss=a["stop_loss"],
            sma_50=a["sma_50"],
            classification=a["classification"],
            prev_close=a.get("prev_close"),
            watch_reason=a.get("watch_reason"),
        )
        if trig is not None:
            triggered.append((a, trig))

    # force=replace(같은 as_of 행 삭제 후 재평가). dry_run 이면 삭제 안 함(무부작용 미리보기).
    # 기본(not force): 이미 as_of 로 평가된 종목 skip(멱등 재개).
    abort_skipped = 0
    if force and not dry_run:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM trigger_evaluation_log "
                "WHERE COALESCE(analyzed_for_date, (evaluated_at AT TIME ZONE 'UTC')::date) = %s",
                (as_of,),
            )
        conn.commit()
    elif not force:
        done = _already_evaluated_symbols(conn, as_of)
        aborted = _aborted_since_classification(conn, active)
        abort_skipped = sum(1 for (a, _t) in triggered if a["symbol"] in aborted)
        triggered = [(a, t) for (a, t) in triggered if a["symbol"] not in (done | aborted)]

    if limit:
        triggered = triggered[:limit]

    log.info(
        "evaluate_pivot: %d triggered out of %d active (abort_skipped=%d)",
        len(triggered), len(active), abort_skipped,
    )

    held = {p["symbol"] for p in get_open_positions(conn)}

    evaluated = 0
    extended_blocked = 0
    strict_vol_blocked = 0
    position_suppressed = 0
    failed = []
    for a, trig in triggered:
        try:
            # (#74) 보유 억제 — 상향 트리거는 보유 중 재트리거가 전부 노이즈
            # (단순 abort 모델·피라미딩 없음). invalidation 은 통과(하향 신호).
            # 체인 최선행: 억제분이 extended/strict(F4 분모) 기록에 안 섞이게.
            if trig in _UPWARD_TRIGGERS and a["symbol"] in held:
                _record_deterministic_wait(
                    conn, a, trig, dry_run=dry_run, as_of=as_of,
                    wait_reason=POSITION_SUPPRESSED_WAIT_REASON,
                    reasoning=("deterministic dedupe: open position held — "
                               "upward re-trigger suppressed (#74 §5)"),
                )
                position_suppressed += 1
                conn.commit()
                continue
            # (#45) 결정론 extended 게이트 — O'Neil 5% 추격 금지의 매수 시점 강제.
            # close > pivot × 1.05 인 상향 트리거는 LLM 없이 wait 기록(결정 3′,
            # plans/2026-07-21-issue45-extended-gate.md §1). buy zone 복귀일에만
            # LLM 평가로 진행. wait 는 abort 와 달리 이후 날짜 재평가를 막지 않는다.
            if (
                trig in _EXTENDED_INTERCEPT_TRIGGERS
                and a["close"] > a["pivot_price"] * PIVOT_EXTENDED_BAND_MULT
            ):
                _record_extended_block(conn, a, trig, dry_run=dry_run, as_of=as_of)
                extended_blocked += 1
                conn.commit()
                continue
            # (#74) strict 1.5× — cup_without_handle 은 grace band(1.2~1.4)·
            # 1.4 floor 비허용. 결측(volume/avg)은 차단 근거로 쓰지 않음(LLM 경로).
            # specs/2026-07-24-issue74-cup-without-handle.md §3.
            if trig in _EXTENDED_INTERCEPT_TRIGGERS \
                    and a.get("pattern") == "cup_without_handle":
                vol, avg = a.get("volume"), a.get("avg_volume_50d")
                if vol is not None and avg is not None and float(avg) > 0:
                    ratio = float(vol) / float(avg)
                    if ratio < BREAKOUT_VOL_PREFERRED:
                        _record_deterministic_wait(
                            conn, a, trig, dry_run=dry_run, as_of=as_of,
                            wait_reason=STRICT_NH_WAIT_REASON,
                            reasoning=(
                                f"deterministic strict volume gate (#74): ratio "
                                f"{ratio:.2f} < {BREAKOUT_VOL_PREFERRED} — "
                                f"no-handle breakout requires strict 1.5x"
                            ),
                        )
                        strict_vol_blocked += 1
                        conn.commit()
                        continue
            _process_one(conn, a, trig, dry_run=dry_run, as_of=as_of)
            evaluated += 1
            conn.commit()
        except UsageLimitError:
            # 사용량 제한 — 남은 종목 순회가 전부 헛호출이므로 즉시 중단.
            # 예외 전파 → run_tracking failed → 재실행 계기 확보. 기평가분은 commit 완료 +
            # _already_evaluated_symbols 가드가 재실행 시 이어하기.
            conn.rollback()
            log.warning("evaluate usage limit at %s — aborting (evaluated=%d/%d)",
                        a["symbol"], evaluated, len(triggered))
            raise
        except Exception as e:
            log.warning("evaluate %s failed: %s", a["symbol"], e)
            failed.append(a["symbol"])
            conn.rollback()

    return {
        "evaluated": evaluated,
        "failures": len(failed),
        "active": len(active),
        "triggered": len(triggered),
        "abort_skipped": abort_skipped,
        "extended_blocked": extended_blocked,
        "strict_vol_blocked": strict_vol_blocked,
        "position_suppressed": position_suppressed,
    }


def _record_deterministic_wait(conn, active_row, trig_type, *, dry_run, as_of,
                               wait_reason, reasoning):
    """결정론 wait 행 기록 공통기 — LLM 비관여(llm_* 전부 NULL).

    close/pivot/volume 원값 보존 — 사후 감사·F4 측정 재료. reasoning 은
    사람용 산식 표시일 뿐, 조회 기준은 wait_reason 동등비교만(사전등록 규약).
    (#45 extended / #74 strict·dedupe 공용.)
    """
    symbol = active_row["symbol"]
    if dry_run:
        log.info("dry-run: deterministic wait %s (%s) %s", symbol, wait_reason,
                 reasoning)
        return
    insert_trigger_log(
        conn,
        symbol=symbol,
        evaluated_at=datetime.now(timezone.utc),
        trigger_type=trig_type,
        close=active_row["close"],
        volume=active_row["volume"],
        pivot_price=active_row["pivot_price"],
        result={
            "decision": "wait",
            "confidence": None,
            "reasoning": reasoning,
            "abort_reason": None,
        },
        # subscript 의도적 — prior_classification_at 은 NOT NULL 컬럼이고 production
        # active 행(get_active_with_current)은 classified_at 을 항상 가진다. 결측이면
        # 여기서 KeyError → 종목 단위 failed 격리가 조용한 NULL INSERT 시도보다 낫다.
        prior_classification_at=active_row["classified_at"],
        llm_meta={},
        analyzed_for_date=as_of,
        wait_reason=wait_reason,
    )


def _record_extended_block(conn, active_row, trig_type, *, dry_run, as_of):
    """(#45) extended 차단 기록 — _record_deterministic_wait 로 위임."""
    close = active_row["close"]
    pivot = active_row["pivot_price"]
    extension_pct = (close / pivot - 1) * 100
    _record_deterministic_wait(
        conn, active_row, trig_type, dry_run=dry_run, as_of=as_of,
        wait_reason=EXTENDED_WAIT_REASON,
        reasoning=(
            f"deterministic extended gate: close {close} > pivot {pivot} × "
            f"{PIVOT_EXTENDED_BAND_MULT} (extension {extension_pct:+.1f}%)"
        ),
    )


def _extension_history(conn, active_row, *, as_of) -> dict | None:
    """(#45) 같은 분류에 대한 extended 차단 이력 → 복귀일 payload 3종. 이력 0건이면 None.

    후속 게이트 개선 트랙의 소급 데이터 확보용 — 프롬프트가 참조하기 전까지
    무해(추가 키일 뿐). max_extension_pct 는 기록된 close/pivot 원값으로 재계산.
    analyzed_for_date < as_of 상한 — force 재생(run --date --force)이 과거 as_of 를
    재평가할 때 미래 차단 행이 새는 look-ahead 차단(payload_lite 의
    recent_evaluation_history evaluated_at 상한과 동일 규율). 경계는 strict —
    같은 날 차단 행과 LLM 평가는 상호 배타(차단 시 continue + 멱등 가드).
    evaluated_at 이 아니라 analyzed_for_date 기준인 이유: force 재생이 과거 차단
    행을 evaluated_at=now() 로 재기록하므로 evaluated_at 상한은 정당한 과거
    이력을 오배제한다.
    """
    cls_at = active_row.get("classified_at")
    if cls_at is None:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT close, pivot_price FROM trigger_evaluation_log "
            "WHERE symbol = %s AND prior_classification_at = %s AND wait_reason = %s "
            "AND analyzed_for_date < %s",
            (active_row["symbol"], cls_at, EXTENDED_WAIT_REASON, as_of),
        )
        rows = cur.fetchall()
    if not rows:
        return None
    max_ext = max(
        (float(c) / float(p) - 1) * 100 for c, p in rows if c is not None and p
    )
    vol, avg = active_row.get("volume"), active_row.get("avg_volume_50d")
    return {
        "max_extension_pct": round(max_ext, 2),
        "days_extended": len(rows),
        "return_day_volume_ratio": (
            round(vol / avg, 2) if vol is not None and avg else None
        ),
    }


def _process_one(conn, active_row, trig_type, *, dry_run, as_of):
    symbol = active_row["symbol"]
    started = datetime.now(timezone.utc)

    payload = build_for_5b(conn, symbol, trigger_type=trig_type, as_of=as_of)
    # (#45) 차단 이력이 있는 종목의 복귀일 평가에만 extension_history 주입.
    history = _extension_history(conn, active_row, as_of=as_of)
    if history is not None:
        payload["extension_history"] = history
    llm_io: dict = {}
    result = call_claude(
        prompt_file="evaluate_pivot_trigger_v1.md",
        attachments=[],
        payload_inline=payload,
        dry_run=dry_run,
        meta_out=llm_io,
    )

    finished = datetime.now(timezone.utc)

    if dry_run:
        log.info("dry-run: skipping DB insert for %s (mock decision %s)",
                 symbol, result.get("decision"))
        return

    insert_trigger_log(
        conn,
        symbol=symbol,
        evaluated_at=finished,
        trigger_type=trig_type,
        close=active_row["close"],
        volume=active_row["volume"],
        pivot_price=active_row["pivot_price"],
        result=result,
        prior_classification_at=active_row["classified_at"],
        llm_meta={"duration_s": (finished - started).total_seconds(),
                  "input_tokens": llm_io.get("input_tokens"),
                  "output_tokens": llm_io.get("output_tokens"),
                  "model": llm_io.get("model")},
        analyzed_for_date=as_of,
    )
