"""승자 프로파일링(관찰 라벨 — 채택 판정 아님): 진입 시점 특징 vs 결과.

풀링 A+B breakout 트레이드(refinement 산출)를 승자/패자로 나눠 진입일 특징
(rs_rating·RS선 6주추세·52주고가 이격·돌파일 거래량배수)을 비교한다.

  전제: A 트레이드 JSON 재생성 후 실행
    uv run python -m kr_pipeline.backtest.refinement > /tmp/refinement_a.json
    uv run python scripts/explore_winner_profile.py
"""
from __future__ import annotations

import json

import psycopg

A_PATH = "/tmp/refinement_a.json"
B_PATH = "data/backtest/refinement_sample_b_20260721.json"


def load_features(trades: list[dict]) -> None:
    with psycopg.connect("postgresql://localhost/kr_pipeline") as conn, conn.cursor() as cur:
        for t in trades:
            cur.execute("""
                SELECT i.rs_rating, i.pct_from_52w_high, i.rs_line_uptrend_6w,
                       p.adj_volume::float / NULLIF((
                           SELECT AVG(x.adj_volume) FROM (
                               SELECT adj_volume FROM daily_prices
                               WHERE ticker = i.ticker AND date < i.date
                               ORDER BY date DESC LIMIT 50) x), 0)
                FROM daily_indicators i
                JOIN daily_prices p ON p.ticker = i.ticker AND p.date = i.date
                WHERE i.ticker = %s AND i.date = %s""", (t["ticker"], t["entry_date"]))
            r = cur.fetchone()
            t["rs"] = float(r[0]) if r and r[0] is not None else None
            t["pct52h"] = float(r[1]) if r and r[1] is not None else None
            t["rs6w"] = r[2] if r else None
            t["volx"] = float(r[3]) if r and r[3] is not None else None


def bucket(trades: list[dict], pred, label: str) -> dict:
    grp = [t for t in trades if pred(t)]
    if not grp:
        return {"label": label, "n": 0}
    w = sum(1 for t in grp if t["excess_net"] > 0)
    return {"label": label, "n": len(grp),
            "win_rate_pct": round(w / len(grp) * 100, 1),
            "mean_excess_net": round(sum(t["excess_net"] for t in grp) / len(grp), 2)}


def main() -> int:
    a = json.load(open(A_PATH))["trades"]
    b = json.load(open(B_PATH))["trades"]
    trades = a + b
    load_features(trades)
    out = {"label": "탐색/관찰 — 채택 판정 아님 (다중비교 주의)", "buckets": []}
    checks = [
        (lambda t: t.get("rs") is not None and t["rs"] >= 90, "RS>=90"),
        (lambda t: t.get("rs") is not None and 80 <= t["rs"] < 90, "RS 80-89"),
        (lambda t: t.get("rs") is not None and t["rs"] < 80, "RS<80"),
        (lambda t: t.get("pct52h") is not None and t["pct52h"] >= -5, "52주고가 -5% 이내"),
        (lambda t: t.get("pct52h") is not None and t["pct52h"] < -5, "52주고가 -5% 밖"),
        (lambda t: t.get("volx") and t["volx"] >= 3, "돌파일 거래량>=3x"),
        (lambda t: t.get("volx") and 1.5 <= t["volx"] < 3, "거래량 1.5-3x"),
        (lambda t: t.get("volx") and t["volx"] < 1.5, "거래량<1.5x"),
        (lambda t: t.get("rs6w") is True, "RS선 6주상승 True"),
        (lambda t: t.get("rs6w") is False, "RS선 6주상승 False"),
    ]
    for pred, label in checks:
        out["buckets"].append(bucket(trades, pred, label))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
