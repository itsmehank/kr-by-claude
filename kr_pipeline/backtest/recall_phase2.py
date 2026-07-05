"""Phase 2 — recall 감사 트리거층 귀속 (spec §5, 거의 결정론).

에피소드(표본 120)별:
  1. Phase 1 백필 행(recall_audit_classification) 로드.
  2. entry 존재 → caught (결정론 종결, LLM 0회).
  3. watch 행: 각 행의 pivot_price 에 대해 anchor 이후 ~ 에피소드 말까지
     adj 고가 ≥ pivot 돌파 여부 결정론 확인 + production trigger_gate 결정론부
     재적용(fresh cross·거래량·watch_reason — 기록용 컬럼).
  4. 첫 돌파 건: LLM 트리거 확인 감사 — build_for_5b(prior_row=해당 watch 행 주입),
     evaluate_pivot_trigger_v1.md, as_of=돌파일. go_now → caught / wait·abort →
     trigger_miss. 저장 = data/backtest/recall_trigger_audit_20260702.json
     (production trigger_evaluation_log 쓰기 0건, 멱등 resume).
  5. watch 존재 + 돌파 없음 → pivot_miss. 전부 ignore → classification_miss.

실행:
  uv run python -m kr_pipeline.backtest.recall_phase2 --deterministic  # LLM 0회, 견적
  uv run python -m kr_pipeline.backtest.recall_phase2                  # 5b 감사 + 버킷 확정
출력: data/backtest/recall_phase2_buckets_20260705.csv
"""
from __future__ import annotations

import csv
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, time as dt_time
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import Connection

from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as gate_evaluate
from kr_pipeline.llm_runner.llm.claude_cli import call_claude, UsageLimitError

log = logging.getLogger("kr_pipeline.backtest.recall_phase2")

TABLE = "recall_audit_classification"
BACKFILL_CAP = 12
LOOKBACK_START = date(2024, 1, 1)
WINDOW_END = date(2026, 6, 30)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "backtest"
SAMPLE_CSV = DATA_DIR / "recall_phase1_sample_20260703.csv"
AUDIT_PATH = DATA_DIR / "recall_trigger_audit_20260702.json"  # spec §5 명명
OUT_CSV = DATA_DIR / "recall_phase2_buckets_20260705.csv"


def _connect() -> psycopg.Connection:
    load_dotenv()
    return psycopg.connect(os.environ["DATABASE_URL"])


def load_anchors(conn: Connection) -> list[date]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date FROM index_daily WHERE index_code='1001'"
            " AND date BETWEEN %s AND %s ORDER BY date",
            (LOOKBACK_START, WINDOW_END),
        )
        days = [r[0] for r in cur.fetchall()]
    by_week: dict[tuple, date] = {}
    for d in days:
        iso = d.isocalendar()
        by_week[(iso[0], iso[1])] = max(d, by_week.get((iso[0], iso[1]), d))
    return sorted(by_week.values())


def load_episodes(conn: Connection) -> list[dict]:
    """표본 120 에피소드 + 백필 anchor 목록(recall_backfill 과 동일 재계산)."""
    with open(SAMPLE_CSV) as f:
        eps = list(csv.DictReader(f))
    anchors = load_anchors(conn)
    tickers = sorted({e["ticker"] for e in eps})
    gate: dict[str, set[date]] = defaultdict(set)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.ticker, i.date
              FROM daily_indicators i
              JOIN stocks s ON s.ticker = i.ticker
             WHERE i.ticker = ANY(%s) AND i.date = ANY(%s)
               AND i.minervini_pass = TRUE
               AND i.rs_line_not_declining_7m = TRUE
               AND s.delisted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1 FROM daily_prices p
                    WHERE p.ticker = i.ticker AND p.date = i.date AND p.adj_low IS NULL)
            """,
            (tickers, anchors),
        )
        for t, d in cur.fetchall():
            gate[t].add(d)
    out = []
    for e in eps:
        first_tt = date.fromisoformat(e["first_tt"])
        peak = date.fromisoformat(e["peak_date"])
        peak_anchor = next((a for a in reversed(anchors) if a <= peak), None)
        bf = [a for a in anchors if first_tt <= a <= peak_anchor and a in gate[e["ticker"]]]
        e["bf_anchors"] = bf[:BACKFILL_CAP]
        e["ep_end"] = date.fromisoformat(e["last_win_anchor"])
        out.append(e)
    return out


def load_bars(conn: Connection, tickers: list[str]) -> dict[str, list[dict]]:
    """일별 adj close/high + raw volume + 50d 평균 volume + sma_50 (게이트 입력)."""
    bars: dict[str, list[dict]] = defaultdict(list)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.ticker, p.date, p.adj_close, p.adj_high, p.volume,
                   AVG(p.volume) OVER (PARTITION BY p.ticker ORDER BY p.date
                                       ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS vol50,
                   i.sma_50
              FROM daily_prices p
              LEFT JOIN daily_indicators i ON i.ticker = p.ticker AND i.date = p.date
             WHERE p.ticker = ANY(%s) AND p.date >= %s
             ORDER BY p.ticker, p.date
            """,
            (tickers, LOOKBACK_START),
        )
        for t, d, c, h, v, v50, sma in cur.fetchall():
            bars[t].append({
                "date": d,
                "adj_close": float(c) if c is not None else None,
                "adj_high": float(h) if h is not None else None,
                "volume": int(v or 0), "vol50": float(v50 or 0),
                "sma_50": float(sma) if sma is not None else None,
            })
    return bars


def load_phase1_rows(conn: Connection, ep: dict) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT analyzed_for_date, classification, pattern, pivot_price,
                   pivot_basis, base_high, base_low, base_depth_pct, risk_flags,
                   reasoning, watch_reason
              FROM {TABLE}
             WHERE symbol = %s AND analyzed_for_date = ANY(%s)
             ORDER BY analyzed_for_date
            """,
            (ep["ticker"], ep["bf_anchors"]),
        )
        cols = ["analyzed_for_date", "classification", "pattern", "pivot_price",
                "pivot_basis", "base_high", "base_low", "base_depth_pct",
                "risk_flags", "reasoning", "watch_reason"]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def find_breakout(row: dict, bars: list[dict], ep_end: date) -> dict | None:
    """watch 행 pivot 의 첫 돌파일 (anchor 이후 ~ ep_end, adj 고가 ≥ pivot — spec §5).

    게이트 결정론부 재적용 결과(fresh cross·거래량 조건)도 기록용으로 산출.
    """
    if row["pivot_price"] is None:
        return None
    pivot = float(row["pivot_price"])
    anchor = row["analyzed_for_date"]
    prev_close = None
    for b in bars:
        if b["date"] <= anchor:
            prev_close = b["adj_close"]
            continue
        if b["date"] > ep_end:
            break
        if b["adj_high"] is not None and b["adj_high"] >= pivot:
            gate = None
            if b["adj_close"] is not None and b["sma_50"] is not None and b["vol50"]:
                gate = gate_evaluate(
                    close=b["adj_close"], pivot_price=pivot, volume=b["volume"],
                    avg_volume_50d=b["vol50"], stop_loss=None, sma_50=b["sma_50"],
                    classification="watch", prev_close=prev_close,
                    watch_reason=row["watch_reason"],
                )
            return {"breakout_date": b["date"], "gate_result": gate}
        prev_close = b["adj_close"]
    return None


def prior_row_from(row: dict) -> dict:
    """Phase 1 백필 watch 행 → build_for_5b prior_row (classified_at=anchor, §5)."""
    return {
        "classified_at": datetime.combine(row["analyzed_for_date"], dt_time.min),
        "classification": row["classification"], "pattern": row["pattern"],
        "pivot_price": float(row["pivot_price"]) if row["pivot_price"] is not None else None,
        "pivot_basis": row["pivot_basis"],
        "base_high": float(row["base_high"]) if row["base_high"] is not None else None,
        "base_low": float(row["base_low"]) if row["base_low"] is not None else None,
        "base_depth_pct": float(row["base_depth_pct"]) if row["base_depth_pct"] is not None else None,
        "risk_flags": row["risk_flags"], "reasoning": row["reasoning"],
        "watch_reason": row["watch_reason"],
    }


def analyze_episodes(conn: Connection) -> list[dict]:
    """결정론 패스: 에피소드별 잠정 버킷 + LLM 감사 대상(첫 돌파) 산출."""
    eps = load_episodes(conn)
    bars_all = load_bars(conn, sorted({e["ticker"] for e in eps}))
    out = []
    for ep in eps:
        rows = load_phase1_rows(conn, ep)
        entry_rows = [r for r in rows if r["classification"] == "entry"]
        watch_rows = [r for r in rows if r["classification"] == "watch"]
        rec = {
            "ticker": ep["ticker"], "ep_start": ep["ep_start"],
            "first_win_anchor": ep["first_win_anchor"],
            "last_win_anchor": ep["last_win_anchor"], "peak_date": ep["peak_date"],
            "tertile": ep["tertile"], "ep_excess_pct": ep["ep_excess_pct"],
            "truncated": ep["truncated"], "censored": ep["censored"],
            "n_rows": len(rows), "n_entry": len(entry_rows),
            "n_watch": len(watch_rows),
            "n_ignore": sum(1 for r in rows if r["classification"] == "ignore"),
            "breakout_date": None, "gate_result": None, "audited_anchor": None,
            "decision": None,
        }
        if entry_rows:
            rec["bucket"] = "caught"
            rec["caught_via"] = "weekend_entry"
            rec["audited_anchor"] = str(entry_rows[0]["analyzed_for_date"])
        elif watch_rows:
            bko, bko_row = None, None
            for r in watch_rows:  # anchor 순 — 첫 돌파 시그널이 production 경로
                b = find_breakout(r, bars_all[ep["ticker"]], ep["ep_end"])
                if b:
                    bko, bko_row = b, r
                    break
            if bko:
                rec["bucket"] = "llm_audit_pending"  # go_now/wait 로 확정
                rec["breakout_date"] = str(bko["breakout_date"])
                rec["gate_result"] = bko["gate_result"]
                rec["audited_anchor"] = str(bko_row["analyzed_for_date"])
                rec["_audit_row"] = bko_row
            else:
                rec["bucket"] = "pivot_miss"
        else:
            rec["bucket"] = "classification_miss"
        out.append(rec)
    return out


def _load_audit(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"spec": "2026-07-02-missed-winners-recall-audit-design.md §5", "results": []}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    deterministic_only = "--deterministic" in sys.argv
    dry_run = "--dry-run" in sys.argv
    conn = _connect()
    recs = analyze_episodes(conn)

    from collections import Counter
    pend = [r for r in recs if r["bucket"] == "llm_audit_pending"]
    uniq_calls = {(r["ticker"], r["breakout_date"]) for r in pend}
    print(f"[phase2-결정론] 버킷 잠정: {dict(Counter(r['bucket'] for r in recs))}")
    print(f"[phase2-결정론] LLM 감사 대상: 에피소드 {len(pend)}건 / 고유 (ticker,돌파일) {len(uniq_calls)}건")
    if deterministic_only:
        return 0

    doc = _load_audit(AUDIT_PATH)
    done = {(r["ticker"], r["breakout_date"]): r for r in doc["results"]}
    for r in pend:
        key = (r["ticker"], r["breakout_date"])
        if key in done:
            r["decision"] = done[key].get("decision")
            continue
        payload = build_for_5b(
            conn, r["ticker"], trigger_type="breakout_from_watch",
            as_of=date.fromisoformat(r["breakout_date"]),
            prior_row=prior_row_from(r["_audit_row"]),
        )
        llm_io: dict = {}
        try:
            result = call_claude(
                prompt_file="evaluate_pivot_trigger_v1.md",
                attachments=[], payload_inline=payload, dry_run=dry_run,
                meta_out=llm_io,
            )
        except UsageLimitError:
            log.warning("usage limit — clean abort (%d done), 같은 명령 resume", len(done))
            break
        except Exception as e:
            log.warning("audit fail %s %s: %s", r["ticker"], r["breakout_date"], e)
            continue
        if dry_run:
            r["decision"] = result.get("decision")
            continue
        rec_out = {
            "ticker": r["ticker"], "breakout_date": r["breakout_date"],
            "audited_anchor": r["audited_anchor"], "gate_result": r["gate_result"],
            "watch_reason": r["_audit_row"]["watch_reason"],
            "decision": result.get("decision"),
            "confidence": result.get("confidence"),
            "reasoning": result.get("reasoning"),
            "abort_reason": result.get("abort_reason"),
            "llm_model": llm_io.get("model"),
            "input_tokens": llm_io.get("input_tokens"),
            "output_tokens": llm_io.get("output_tokens"),
        }
        doc["results"].append(rec_out)
        done[key] = rec_out
        AUDIT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        r["decision"] = rec_out["decision"]
        log.info("5b %s %s → %s (%d/%d)", r["ticker"], r["breakout_date"],
                 r["decision"], len(done), len(uniq_calls))

    # 버킷 확정 (spec §5 우선순위)
    for r in recs:
        if r["bucket"] == "llm_audit_pending":
            if r["decision"] == "go_now":
                r["bucket"] = "caught"
                r["caught_via"] = "watch_breakout_go_now"
            elif r["decision"] in ("wait", "abort"):
                r["bucket"] = "trigger_miss"
            else:
                r["bucket"] = "llm_audit_pending"  # 미완(한도) — resume 대상
        r.pop("_audit_row", None)

    with open(OUT_CSV, "w", newline="") as f:
        fields = [k for k in recs[0].keys()]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(recs)
    print(f"[phase2] 최종 버킷: {dict(Counter(r['bucket'] for r in recs))}")
    print(f"CSV: {OUT_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
