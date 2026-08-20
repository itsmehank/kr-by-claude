# kr_pipeline/ohlcv/delisted_adj.py
"""#114 P0 — 상폐 종목 수정주가 생산 (체인 v5-d).

**v5-d = 동결 v5 와의 차이 = gap_fallback 미부여 1건**(12차 ① (a) 봉인):
제한폭 부재 구간(정리매매·재개)에서 주식수 비정합 순수 가격 갭은 실제 폭락일
확률이 지배적(실측 하락 91%)이라 조정으로 오인하지 않고 **갭을 보존**한다.
검증 범위(상장 규칙 구간)의 동결 v5 는 무변경 — fallback 유지.

산출 = raw × factor_curve(v3_events_prov(use_gap_fallback=False)) 를 최종
관측일 앵커(마지막 날 adj = raw)로 계산. 거래정지 0값 행은 미생산(행 없음) —
nullify_halt_adj 관례 상속(스펙 §3-4). 억제된 갭은 suppressed 원장으로 반환
(12차 조건 1 상방 갭 감사 입력). 정리매매 창(마지막 관측일 전 14일 달력) 행은
liq_window 로 표시(12차 조건 3 — 소비 측 층화 선택권).
소비는 RS 재계산 파이프라인 한정 허용(12차 ②-②), 그 외 금지.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import NamedTuple

from kr_pipeline.ohlcv.adj_reconstruct import factor_curve, v3_events_prov

CHAIN_VERSION = "v5-d"    # 13차 v5-d′(crDecsn 편입) 시도 → 정지 규칙 기각, 잔류
LIQ_WINDOW_DAYS = 14        # 정리매매 창(달력일) — 12차 ① 진단 실측과 동일 정의
UPWARD_GAP = 1.35           # 상방 갭 감사 임계 = big_gap 동일 [12차 조건 1]


class DelistedAdjResult(NamedTuple):
    adj: dict[date, float]
    events: list[tuple[date, float, str]]        # 적용된 이벤트(provenance 포함)
    provenance: dict                             # 적용 이벤트 census
    flags: dict                                  # 층화 플래그
    suppressed: list[tuple[date, float, str]]    # 미부여 갭 원장(감사 입력)
    liq_window: set[date]                        # 정리매매 창 날짜


def produce_delisted_adj(
    closes: list[tuple[date, float]], shares: dict[date, int],
    details: list[dict], *, stkdp_unresolved: bool = False,
) -> DelistedAdjResult:
    """상폐 종목 1개의 수정주가 산출 (v5-d)."""
    pos = [(d, c) for d, c in closes if c > 0]
    if not pos:
        return DelistedAdjResult({}, [], {}, {
            "stkdp_unresolved": bool(stkdp_unresolved), "has_piic_gap": False,
            "n_suppressed_gaps": 0, "has_suppressed_upward_gap": False,
        }, [], set())
    # v5-d′(use_cr_delisted=True)는 13차 정지 규칙 기각(레거시 p99 4종목
    # 2.0~10.9 악화·극단 factor 15 — 반복/미집행 감자 결정 오적용) → v5-d 잔류.
    ev_used = v3_events_prov(pos, shares, details, use_gap_fallback=False)
    ev_v5 = v3_events_prov(pos, shares, details)
    suppressed = [e for e in ev_v5 if e[2] == "gap_fallback"]
    dates = [d for d, _ in pos]
    f = factor_curve(dates, [(d, r) for d, r, _ in ev_used])
    adj = {d: c * f[d] for d, c in pos}
    provenance = dict(Counter(p for _, _, p in ev_used))
    flags = {
        "stkdp_unresolved": bool(stkdp_unresolved),
        "has_piic_gap": provenance.get("piic_gap", 0) > 0,
        "n_suppressed_gaps": len(suppressed),
        "has_suppressed_upward_gap": any(r > UPWARD_GAP for _, r, _ in suppressed),
    }
    last = dates[-1]
    liq = {d for d in dates if (last - d).days <= LIQ_WINDOW_DAYS}
    return DelistedAdjResult(adj, ev_used, provenance, flags, suppressed, liq)
