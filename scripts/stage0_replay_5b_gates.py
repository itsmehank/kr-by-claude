"""0단계 층① — #37 B(5b) computed_gates 과거 재생 실측 (#44 착수 전 검증).

backtest_classification 의 entry/watch 행(피벗 보유)을 유효 주간(분류 토요일
다음 거래주)에 재생한다: 실제 production 경로와 동일하게
  trigger_gate.evaluate (결정론 트리거 검출, 행당 첫 발동일만 — production 은
  trigger_evaluation_log 로 같은 주 재평가를 막으므로)
  → build_for_5b(as_of=발동일, prior_row=해당 백테스트 행)  [look-ahead 차단]
  → payload["computed_gates"] 수집.
LLM 호출 없음. production DB 는 read-only (SELECT 만).

집계(판독 기준은 리포트 문서에):
  - 트리거 유형별 건수
  - 게이트 키별: null 비율 / boolean 발화율 / 수치 게이트 요약
  - ohlcv_last_date != as_of 건수 (halt 소스 불일치 노출 규약)
  - build 실패 건수(예외 유형별)

stop_loss 는 미주입(None) — 백테스트 행에는 entry_params 스탑이 없어
invalidation 은 close<sma_50 경로만 측정된다(리포트에 한계로 명시).
"""
from __future__ import annotations

import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path

from kr_pipeline.db.connection import connect
from kr_pipeline.llm_runner.compute.payload_lite import build_for_5b
from kr_pipeline.llm_runner.compute.trigger_gate import evaluate as evaluate_gate

log = logging.getLogger("stage0.replay_5b")

OUT_PATH = Path("data/verification/2026-07-17-stage0/5b_gate_replay.json")

_PRIOR_SQL = """
SELECT symbol, analyzed_for_date, classification, pattern, pivot_price,
       pivot_basis, base_high, base_low, base_depth_pct, risk_flags,
       reasoning, watch_reason
  FROM backtest_classification
 WHERE classification IN ('entry', 'watch')
   AND pivot_price IS NOT NULL
 ORDER BY analyzed_for_date, symbol
"""

# 유효 주간의 일별 지표 + 전일 종가 (LAG 는 창 밖 전일도 필요해 하루 여유)
_DAYS_SQL = """
SELECT date, adj_close, volume, avg_volume_50d, sma_50,
       LAG(adj_close) OVER (ORDER BY date) AS prev_close
  FROM daily_indicators
 WHERE ticker = %s AND date BETWEEN %s AND %s
 ORDER BY date
"""


def _prior_row(r: tuple) -> dict:
    sat: date = r[1]
    return {
        "classified_at": datetime.combine(sat, dt_time.min),
        "classification": r[2],
        "pattern": r[3],
        "pivot_price": float(r[4]),
        "pivot_basis": r[5],
        "base_high": float(r[6]) if r[6] is not None else None,
        "base_low": float(r[7]) if r[7] is not None else None,
        "base_depth_pct": float(r[8]) if r[8] is not None else None,
        "risk_flags": r[9],
        "reasoning": r[10],
        "watch_reason": r[11],
    }


def _first_trigger(conn, row: dict) -> tuple[date, str] | None:
    """분류 토요일 다음 거래주(토+1 ~ 토+7)에서 첫 트리거 발동일. 없으면 None."""
    sat = row["classified_at"].date()
    with conn.cursor() as cur:
        cur.execute(_DAYS_SQL, (row["_symbol"], sat - timedelta(days=6),
                                sat + timedelta(days=7)))
        days = cur.fetchall()
    for d, close, volume, avg_vol, sma_50, prev_close in days:
        if d <= sat:
            continue
        if close is None or volume is None or avg_vol is None or sma_50 is None:
            continue
        trig = evaluate_gate(
            close=float(close),
            pivot_price=row["pivot_price"],
            volume=int(volume),
            avg_volume_50d=float(avg_vol),
            stop_loss=None,
            sma_50=float(sma_50),
            classification=row["classification"],
            prev_close=float(prev_close) if prev_close is not None else None,
            watch_reason=row["watch_reason"],
        )
        if trig is not None:
            return d, trig
    return None


def _classify_value(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return "numeric"
    return "string"  # 날짜·라벨 등 (예: ohlcv_last_date)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    agg = {
        "rows_total": 0,
        "rows_triggered": 0,
        "trigger_types": Counter(),
        "build_errors": Counter(),
        "ohlcv_last_date_mismatch": 0,
        "gate_values": defaultdict(Counter),   # key → {null|true|false|numeric: n}
        "numeric_samples": defaultdict(list),  # key → [float] (분포 요약용)
    }
    records = []

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(_PRIOR_SQL)
            rows = cur.fetchall()
        if limit:
            rows = rows[:limit]
        agg["rows_total"] = len(rows)

        for i, r in enumerate(rows):
            prior = _prior_row(r)
            prior["_symbol"] = r[0]
            hit = _first_trigger(conn, prior)
            if hit is None:
                continue
            as_of, trig = hit
            agg["rows_triggered"] += 1
            agg["trigger_types"][trig] += 1
            prior.pop("_symbol")
            try:
                payload = build_for_5b(conn, r[0], trigger_type=trig,
                                       as_of=as_of, prior_row=prior)
            except Exception as e:  # 측정 대상: 실데이터에서의 build 실패 유형
                agg["build_errors"][f"{type(e).__name__}: {e}"] += 1
                continue
            gates = payload.get("computed_gates") or {}
            flat = {}
            for k, v in gates.items():
                if isinstance(v, dict):
                    for k2, v2 in v.items():
                        flat[f"{k}.{k2}"] = v2
                else:
                    flat[k] = v
            for k, v in flat.items():
                kind = _classify_value(v)
                agg["gate_values"][k][kind] += 1
                if kind == "numeric":
                    agg["numeric_samples"][k].append(float(v))
            if gates.get("ohlcv_last_date") and str(gates["ohlcv_last_date"]) != str(as_of):
                agg["ohlcv_last_date_mismatch"] += 1
            records.append({
                "symbol": r[0], "sat": str(r[1]), "as_of": str(as_of),
                "trigger": trig, "computed_gates": flat,
            })
            if (i + 1) % 200 == 0:
                log.info("progress %d/%d (triggered %d)", i + 1, len(rows),
                         agg["rows_triggered"])

    def _num_summary(vals: list[float]) -> dict:
        vs = sorted(vals)
        n = len(vs)
        return {"n": n, "min": vs[0], "p50": vs[n // 2], "max": vs[-1]}

    out = {
        "generated_at": None,  # 커밋 시점 기록은 리포트 문서가 담당
        "rows_total": agg["rows_total"],
        "rows_triggered": agg["rows_triggered"],
        "trigger_types": dict(agg["trigger_types"]),
        "build_errors": dict(agg["build_errors"]),
        "ohlcv_last_date_mismatch": agg["ohlcv_last_date_mismatch"],
        "gate_value_counts": {k: dict(v) for k, v in sorted(agg["gate_values"].items())},
        "numeric_summaries": {k: _num_summary(v)
                              for k, v in sorted(agg["numeric_samples"].items())},
        "records": records,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")

    print(json.dumps({k: out[k] for k in
                      ("rows_total", "rows_triggered", "trigger_types",
                       "build_errors", "ohlcv_last_date_mismatch")},
                     ensure_ascii=False, indent=2))
    print("\n[gate_value_counts]")
    for k, v in out["gate_value_counts"].items():
        print(f"  {k}: {v}")
    print(f"\nsaved → {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
