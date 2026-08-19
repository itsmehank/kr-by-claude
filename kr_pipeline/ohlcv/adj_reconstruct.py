# kr_pipeline/ohlcv/adj_reconstruct.py
"""#114 §4.5 — 상장주식수 기반 수정주가 재구성 (v1 프로토타입).

원리: 조정 이벤트(분할·병합·무상증자·감자)에서 상장주식수가 정확히 그 비율로
변한다. 이벤트일 d 의 비율 r = shares(직전일)/shares(d) 이고, 과거 가격의
수정 계수 F(t) = Π_{이벤트 e: date_e > t} r_e (최신일 = 1),
재구성 수정가 = raw close(t) × F(t).

알려진 한계(설계 §4.5): 유상증자 권리락은 주식수 비율 ≠ 가격 조정 비율(발행가
반영 필요) — 소형 밴드 잔차. 주식수 변동 중 조정이 아닌 것(CB 전환·스톡옵션 등)
은 위양성 후보 — 무이벤트 표본 150 의 사전등록 판정으로 측정.
"""
from __future__ import annotations

from datetime import date

MIN_CHANGE = 0.005   # 주식수 변화 감지 임계 (|ratio-1|)


def share_events(dates: list[date], shares: dict[date, int],
                 min_change: float = MIN_CHANGE) -> list[tuple[date, float]]:
    """관측일 순서로 주식수 변화 이벤트 추출 → [(이벤트일, prev/cur 비율)]."""
    out: list[tuple[date, float]] = []
    prev: date | None = None
    for d in dates:
        if d not in shares:
            continue
        if prev is not None and shares[d] > 0 and shares[prev] > 0:
            r = shares[prev] / shares[d]
            if abs(r - 1) > min_change:
                out.append((d, r))
        prev = d
    return out


def factor_curve(dates: list[date], events: list[tuple[date, float]]) -> dict[date, float]:
    """F(t) = Π_{이벤트일 > t} ratio — 최신일 1.0, 과거로 갈수록 누적."""
    out: dict[date, float] = {}
    f = 1.0
    ei = len(events) - 1
    for d in reversed(dates):
        while ei >= 0 and events[ei][0] > d:
            f *= events[ei][1]
            ei -= 1
        out[d] = f
    return out


def reconstruct(closes: list[tuple[date, float]],
                shares: dict[date, int]) -> dict[date, float]:
    """raw 종가 시계열 → 재구성 수정가 (최신일 기준 앵커)."""
    dates = [d for d, _ in closes]
    ev = share_events(sorted(shares), shares)
    f = factor_curve(dates, ev)
    return {d: c * f[d] for d, c in closes}


def error_stats(recon: dict[date, float], adj_db: dict[date, float]) -> dict:
    """공통 날짜에서 상대오차 분포. 앵커 차이는 마지막 공통일 배율로 정규화."""
    common = sorted(set(recon) & set(adj_db))
    if not common:
        return {"n": 0}
    last = common[-1]
    if recon[last] <= 0 or adj_db[last] <= 0:
        return {"n": 0}
    scale = adj_db[last] / recon[last]
    errs = sorted(abs(recon[d] * scale / adj_db[d] - 1)
                  for d in common if adj_db[d] > 0)
    n = len(errs)
    if n == 0:
        return {"n": 0}

    def pct(p: float) -> float:
        return errs[min(int(p * n), n - 1)]

    return {"n": n, "p50": round(pct(0.50), 6), "p90": round(pct(0.90), 6),
            "p99": round(pct(0.99), 6), "max": round(errs[-1], 6)}


def db_factor_jumps(closes: list[tuple[date, float]], adj_db: dict[date, float],
                    min_change: float = MIN_CHANGE) -> list[tuple[date, float]]:
    """참조(pykrx) 조정 이벤트: factor(adj/raw) 점프 → [(일자, 비율)]."""
    out: list[tuple[date, float]] = []
    prev_f: float | None = None
    for d, c in closes:
        if c <= 0 or d not in adj_db or adj_db[d] <= 0:
            continue
        f = adj_db[d] / c
        if prev_f is not None and abs(f / prev_f - 1) > min_change:
            out.append((d, prev_f / f))
        prev_f = f
    return out


def match_events(db_jumps: list[tuple[date, float]],
                 recon_events: list[tuple[date, float]],
                 tol_days: int = 3) -> dict:
    """참조 이벤트가 재구성 이벤트(±tol_days)와 매칭되는지 — 누락 계수(밴드별)."""
    recon_dates = [d for d, _ in recon_events]
    missed_big = missed_small = matched = 0
    for d, r in db_jumps:
        hit = any(abs((d - rd).days) <= tol_days for rd in recon_dates)
        if hit:
            matched += 1
        elif abs(r - 1) > 0.30:
            missed_big += 1
        else:
            missed_small += 1
    return {"db_jumps": len(db_jumps), "matched": matched,
            "missed_big": missed_big, "missed_small": missed_small}


def reconstruct_v2(closes: list[tuple[date, float]], shares: dict[date, int],
                   disclosures: list[date],
                   big_gap: float = 1.35, match_tol: float = 1.4,
                   window_days: int = 45, discl_days: int = 60) -> dict[date, float]:
    """v2 — 시점은 가격 갭, 크기는 주식수 (v1 진단 반영).

    1) 확정 조정 = raw 종가 갭 |log g| > log(big_gap) (가격제한폭 ±30% 초과):
       배율 = ±window_days 내 갭과 정합(log 거리 < log(match_tol))하는 최근접
       주식수 비율. 정합 없으면 갭 자체(당일 수익률 포함 — 잔차 허용).
    2) 소형 조정 = 미소진 주식수 이벤트 중 조정성 공시(±discl_days) 보유분만
       채택(CB 전환·3자배정 등 비조정 변동 = 위양성 차단). 시점 잔차(권리락↔
       신주상장 시차)는 알려진 한계로 측정에 반영.
    """
    events = v2_events(closes, shares, disclosures, big_gap=big_gap,
                       match_tol=match_tol, window_days=window_days,
                       discl_days=discl_days)
    dates = [d for d, _ in closes]
    f = factor_curve(dates, events)
    return {d: c * f[d] for d, c in closes}


def v2_events(closes: list[tuple[date, float]], shares: dict[date, int],
              disclosures: list[date], *, big_gap: float = 1.35,
              match_tol: float = 1.4, window_days: int = 45,
              discl_days: int = 60) -> list[tuple[date, float]]:
    """v2 이벤트 목록 — reconstruct_v2 의 검출부 (매칭 통계에도 사용)."""
    import math

    se = share_events(sorted(shares), shares)
    events: list[tuple[date, float]] = []
    used: set[int] = set()
    for i in range(1, len(closes)):
        _, c_prev = closes[i - 1]
        d, c = closes[i]
        if c_prev <= 0 or c <= 0:
            continue
        g = c / c_prev
        if abs(math.log(g)) <= math.log(big_gap):
            continue
        best = None
        for j, (ds, rs) in enumerate(se):
            if j in used or rs <= 0 or abs((ds - d).days) > window_days:
                continue
            dist = abs(math.log(rs) - math.log(g))
            if dist < math.log(match_tol) and (best is None or dist < best[0]):
                best = (dist, j, rs)
        if best is not None:
            used.add(best[1])
            events.append((d, best[2]))
        else:
            events.append((d, g))
    for j, (ds, rs) in enumerate(se):
        if j in used:
            continue
        if any(abs((ds - dd).days) <= discl_days for dd in disclosures):
            events.append((ds, rs))
    events.sort()
    return events
