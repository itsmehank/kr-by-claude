# kr_pipeline/ohlcv/delisted_adj.py
"""#114 P0 — 상폐 종목 수정주가 생산 (동결 v5 체인 소비자).

참조(pykrx adj) 부재 구간이므로 산출 = raw × factor_curve(v3_events_prov, v5)
를 최종 관측일 앵커(마지막 날 adj = raw)로 계산한다. 거래정지 0값 행은
미생산(행 없음) — nullify_halt_adj 관례 상속(스펙 §3-4). 품질 층화(flags·
provenance census)를 함께 산출해 소비 측이 비정밀 구간을 제외할 수 있게 한다.
소비(지표·RS 투입)는 RS 재계산 설계 문서 승인 전 금지.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

from kr_pipeline.ohlcv.adj_reconstruct import factor_curve, v3_events_prov

CHAIN_VERSION = "v5"


def produce_delisted_adj(
    closes: list[tuple[date, float]], shares: dict[date, int],
    details: list[dict], *, stkdp_unresolved: bool = False,
) -> tuple[dict[date, float], list[tuple[date, float, str]], dict, dict]:
    """상폐 종목 1개의 수정주가 산출.

    반환 (adj, events_prov, provenance, flags):
    - adj: {거래일: 수정 종가} — close>0 행만, 최종 관측일 앵커.
    - events_prov: v3_events_prov 원본(감사 추적).
    - provenance: 이벤트 출처 census {gap_share, gap_fallback, fric, piic_gap, stkdp}.
    - flags: 층화 {stkdp_unresolved(주식배당 공시 실재·비율 미확보 — 호출자 원장
      유래), has_gap_fallback, has_piic_gap} — true 면 해당 구간 비정밀.
    """
    pos = [(d, c) for d, c in closes if c > 0]
    if not pos:
        return {}, [], {}, {"stkdp_unresolved": bool(stkdp_unresolved),
                            "has_gap_fallback": False, "has_piic_gap": False}
    ev_prov = v3_events_prov(pos, shares, details)
    dates = [d for d, _ in pos]
    f = factor_curve(dates, [(d, r) for d, r, _ in ev_prov])
    adj = {d: c * f[d] for d, c in pos}
    provenance = dict(Counter(p for _, _, p in ev_prov))
    flags = {
        "stkdp_unresolved": bool(stkdp_unresolved),
        "has_gap_fallback": provenance.get("gap_fallback", 0) > 0,
        "has_piic_gap": provenance.get("piic_gap", 0) > 0,
    }
    return adj, ev_prov, provenance, flags
