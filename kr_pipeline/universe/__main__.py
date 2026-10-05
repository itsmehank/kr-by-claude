import argparse
import json
import os
from datetime import date, datetime, timedelta
import logging

import pandas as pd

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.common.security_group import UNRESOLVED
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.universe.guards import UniverseGuardError, count_active, preflight_exclusion_diff, verify_universe_after_load
from kr_pipeline.universe.report import report_last_failed
from kr_pipeline.universe.transform import split_universe
from kr_pipeline.universe.store import MAX_DELIST_RATIO, upsert_stocks, mark_delisted, save_universe_raw_snapshot


log = logging.getLogger("kr_pipeline.universe")

SYSTEMIC_SECURITY_GROUP_UNAVAILABLE = "security_group_unavailable"


class UniverseRawIncomplete(ValueError):
    """이번 원본(raw)이 직전 원본 대비 시장별 MAX_DELIST_RATIO 넘게 줄었다 — KRX 부분 응답 의심, 어떤 쓰기(upsert·mark_delisted·스냅샷)도 전에 fail-closed."""


# ── KRX 접촉 함수는 지연 import — `--report-last-failed` 경로(및 이 모듈 import)가 pykrx 로그인(import 시 POST)을 유발하지 않게(리뷰 #223 3차).
#    모듈 속성으로 둬 테스트가 monkeypatch 할 수 있다.
def fetch_universe(d: date) -> pd.DataFrame:
    from kr_pipeline.universe.fetch import fetch_universe as f
    return f(d)


def fetch_sectors(d: date, market: str) -> pd.DataFrame:
    from kr_pipeline.universe.fetch import fetch_sectors as f
    return f(d, market)


def fetch_security_groups(d: date) -> dict[str, str]:
    from kr_pipeline.universe.fetch import fetch_security_groups as f
    return f(d)


def _security_groups_fail_open(today: date, warnings: list[str]) -> dict[str, str]:
    """최근 5일 중 첫 성공 응답. 전부 실패 = 빈 dict(기존 값 유지·신규는 UNRESOLVED) + 경고."""
    for back in range(5):
        d = today - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        try:
            return fetch_security_groups(d)
        except Exception as e:  # noqa: BLE001 — fail-open 지속화(Q-1)
            log.warning(f"security_group fetch failed for {d}: {e}")
    warnings.append("security_group_fetch_failed: 5일 내 응답 없음 — 기존 값 유지, 신규 종목 UNRESOLVED")
    return {}


class _Evidence:
    """운영 규칙 5(회신 16): KRX 응답은 적재 성공과 무관하게 적재 전 파일 보존 — 가드 실패 시 run_tracking 이 raw 스냅샷·stocks 쓰기를 롤백하므로.
    universe·security_group·sector 세 응답을 같은 파일에 누적(fetch 직후마다 갱신). 파일명은 날짜+시각 — 같은 날 재실행이 첫 응답을 덮지 않게
    (ohlcv/provisional 과 동일). 위치 = $KR_VERIFICATION_DIR(기본 data/verification). 실패는 경고만."""

    def __init__(self, today: date):
        d = os.environ.get("KR_VERIFICATION_DIR") or "data/verification"
        self.path = os.path.join(d, f"universe_raw_{today:%Y%m%d}_{datetime.now():%H%M%S}.json")
        self.doc: dict = {"fetched_for": today.isoformat()}

    def save(self, **parts) -> str | None:
        try:
            for k, v in parts.items():
                self.doc[k] = json.loads(v.to_json(orient="records", force_ascii=False)) if isinstance(v, pd.DataFrame) else v
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.doc, f, ensure_ascii=False)
            return self.path
        except Exception as e:  # noqa: BLE001
            log.warning("universe 응답 파일 보존 실패: %s", e)
            return None


def _raw_complete(conn, df: pd.DataFrame, today: date) -> None:
    """시장별 원본 종목 수가 직전 universe_raw_snapshot 대비 MAX_DELIST_RATIO(store.mark_delisted 와 같은 상수) 넘게 줄면 부분 응답 의심 →
    UniverseRawIncomplete(쓰기 전 fail-closed, 리뷰 #223 3·4차). 직전 스냅샷이 없으면 통과."""
    with conn.cursor() as cur:
        cur.execute("SELECT market, COUNT(*) FROM universe_raw_snapshot WHERE snapshot_date = "
                    "(SELECT MAX(snapshot_date) FROM universe_raw_snapshot WHERE snapshot_date < %s) GROUP BY market", (today,))
        prev = {m: n for m, n in cur.fetchall()}
    now = df["market"].value_counts().to_dict()
    for m, n_prev in prev.items():
        n_now = now.get(m, 0)
        if n_prev > 0 and (n_prev - n_now) / n_prev > MAX_DELIST_RATIO:
            raise UniverseRawIncomplete(
                f"universe raw 급감: {m} {n_prev} → {n_now} ({100 * (n_prev - n_now) / n_prev:.1f}% > {MAX_DELIST_RATIO:.0%}) — "
                f"KRX 부분 응답 의심, 적재 전 중단(재실행으로 재조회)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.universe")
    g = p.add_mutually_exclusive_group()     # (리뷰 #223) 둘 다 주면 strict 가 무시되고 전부 수용되던 함정
    g.add_argument("--accept-exclusion-diff", action="store_true",
                   help="배제 집합 스냅샷 변동을 설명된 것으로 수용(원인 확인 후에만 — 잔여분이 있을 때; #199 유형은 수용 불가)")
    g.add_argument("--strict-exclusion-diff", action="store_true",
                   help="(#221) 상폐·신규 상장 배제의 자동 수용을 끈다(모든 변동을 사람 확인으로)")
    g.add_argument("--report-last-failed", action="store_true",
                   help="(#221) 유니버스 갱신 없이, 마지막 성공 이후 가장 최근 실패 run 의 잔여 변동 조사 보고서를 Slack 으로 전송(KRX 접촉 0)")
    return p.parse_args()


def run_universe(conn, *, today: date, accept_exclusion_diff: bool = False, strict: bool = False) -> dict:
    """유니버스 갱신 1회. (#221) 배제 집합 판정은 **어떤 쓰기보다 먼저**(preflight) — 잔여가 있으면 upsert·mark_delisted·스냅샷 없이 실패해
    판정 전체(+이번 원본 행 사본)를 실패 run 의 details 에 남긴다(롤백할 쓰기 자체가 없음 — 리뷰 #223 4차: sub-2% 부분 응답이 오폐지를
    커밋하던 경로 축소). 적재 후 verify_universe_after_load 가 같은 판정을 재확인하고 스냅샷을 쓴다. 조사 보고서(LLM·Slack)는 이 함수 밖
    (`--report-last-failed`)."""
    if accept_exclusion_diff and strict:
        raise ValueError("--accept-exclusion-diff 와 --strict-exclusion-diff 는 동시 지정 불가(의미 충돌)")   # KRX 접촉 전에 거른다
    with run_tracking(conn, pipeline="universe", mode="full", params={"on_date": today.isoformat()}) as state:
        return _run_universe_inner(conn, state, today=today, accept_exclusion_diff=accept_exclusion_diff, strict=strict)


def _run_universe_inner(conn, state: dict, *, today: date, accept_exclusion_diff: bool, strict: bool) -> dict:
    ev = _Evidence(today)
    log.info(f"Fetching universe for {today}")
    df = fetch_universe(today)
    log.info(f"Fetched {len(df)} raw tickers")
    raw_path = ev.save(universe=df)                      # 운영 규칙 5 — 어떤 판정·쓰기보다 먼저 보존
    raw_tickers = set(df["ticker"])                      # (#221) 필터 전 원본 — removed 가 상폐인지(원본에도 없음) 판정
    _raw_complete(conn, df, today)                       # 부분 응답 의심이면 여기서 끝(쓰기 0)

    groups = _security_groups_fail_open(today, state["warnings"])
    ev.save(security_groups=groups)
    sg_unavailable = not groups
    df["security_group"] = df["ticker"].map(groups).fillna(UNRESOLVED)
    raw_by_ticker = {r.ticker: {"name": r.name, "market": r.market, "security_group": r.security_group}
                     for r in df[["ticker", "name", "market", "security_group"]].itertuples(index=False)}
    kept, excluded = split_universe(df)
    log.info(f"After pre-load exclusion: {len(kept)} kept / {len(excluded)} excluded "
             f"{excluded['axis'].value_counts().to_dict() if not excluded.empty else {}}")

    # (#221) 쓰기 전 배제 집합 판정 — 잔여(또는 strict 변동)면 아래 upsert/mark_delisted 를 타지 않는다.
    try:
        preflight_exclusion_diff(conn, snapshot_date=today, excluded=excluded, raw_tickers=raw_tickers,
                                 accept_exclusion_diff=accept_exclusion_diff, auto_accept=not strict)
    except UniverseGuardError as e:
        _record_failed_diff(state, e, sg_unavailable=sg_unavailable, raw_by_ticker=raw_by_ticker, raw_path=raw_path, strict=strict)
        raise

    # (#195 커밋2 부수) 필터 전 원본 전량 저장 — #191 판정 전제(KRX 재접촉 없이 차집합 계산).
    raw_saved = save_universe_raw_snapshot(conn, today, df)
    log.info(f"Saved raw universe snapshot: {raw_saved} rows (file: {raw_path})")

    # 섹터 머지
    sectors = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            sectors.append(fetch_sectors(today, market))
        except Exception as e:
            log.warning(f"Sector fetch failed for {market}: {e}")
    if sectors:
        sec = pd.concat(sectors, ignore_index=True)
        ev.save(sectors=sec)
        kept = kept.merge(sec, on="ticker", how="left")
    else:
        kept["sector"] = None

    active_before = count_active(conn)
    affected = upsert_stocks(conn, kept)
    log.info(f"Upserted {affected} stocks")

    # [#199 사실 기록, 전문가 회신 10 — 보류(C)] (1) mark_delisted 비교 대상 = 이 df = 적재 전 배제 **후** 목록.
    #   따라서 적재 전 배제 축에 새 구분을 넣으면 기존 활성 종목이 "상장 원본에 없음"과 같은 취급으로 폐지 처리된다
    #   (의미 정정 필요: 원본 목록 기준). (2) 시세 수집 대상은 stocks.delisted_at IS NULL 기반(ohlcv/modes._load_active_tickers)
    #   → "상장 중·대상 아님" 상태는 기존 필드 전용이 아니라 컬럼 추가 방향. 둘은 동시에만 가능.
    #   (#221) 배제 집합 스냅샷 가드가 "기존 포함 → 신규 배제" 차분을 잡으면 exclusion_diff 가 kind='199'(확정 그룹이던 행)·'late_resolution'(UNRESOLVED 이던 행) 잔여로 분류해 자동 수용하지 않고
    #   --accept-exclusion-diff 로도 거부한다(preflight, 쓰기 전) — 의미 정정 + 상태 컬럼 동시 착수 전까지 그 달의 universe 는 멈춘다(설계된 멈춤).
    delisted = mark_delisted(conn, current_tickers=set(kept["ticker"]), on_date=today)
    log.info(f"Marked {delisted} as delisted")

    try:
        info = verify_universe_after_load(conn, snapshot_date=today, excluded=excluded, raw_tickers=raw_tickers,
                                          accept_exclusion_diff=accept_exclusion_diff, auto_accept=not strict)
    except UniverseGuardError as e:   # preflight 와 같은 입력이라 여기서는 (a)/(b) 가드만 실제 발생 — 방어적으로 동일 기록
        _record_failed_diff(state, e, sg_unavailable=sg_unavailable, raw_by_ticker=raw_by_ticker, raw_path=raw_path, strict=strict)
        raise
    info["active_before"] = active_before
    if info.get("exclusion_accepted_unexplained"):
        msg = f"exclusion_accepted_unexplained: 잔여 변동을 사람 수용(--accept-exclusion-diff) — {info['exclusion_unexplained']}"
        log.warning(msg)
        state["warnings"].append(msg)
    # (c) 종목 수 변동 기록 — 임계 없음(별도 판정 사안). UNRESOLVED 건수 = 유니버스 무음 축소 감지용.
    auto = info["exclusion_auto_accepted"]
    log.info(f"universe {active_before} -> {info['active_after']} | qualifying_pool {info['qualifying_pool']} "
             f"| row_kept_excluded {info['row_kept_excluded']} | UNRESOLVED {info['unresolved']} "
             f"| exclusion +{len(info['exclusion_added'])} -{len(info['exclusion_removed'])} "
             f"(auto: 상폐 {len(auto['removed_delisted'])}·신규배제 {len(auto['added_new_listing'])})")
    if info["unresolved"]:
        state["warnings"].append(f"security_group_unresolved: {info['unresolved']}종목")
    info["raw_file"] = raw_path
    state["details"] = info
    state["rows_affected"] = affected
    state["total_count"] = info["active_after"]
    return info


def _record_failed_diff(state: dict, e: UniverseGuardError, *, sg_unavailable: bool, raw_by_ticker: dict, raw_path: str | None, strict: bool) -> None:
    """(리뷰 #223) 실패 행에도 판정 전체를 성공 행과 같은 키 모양으로 남긴다(오류 문자열은 20개 절단) — 보고서·사람 수용의 근거.
    잔여 티커분 원본 행 사본 보존(롤백·미저장 대비). security_group 조회 실패는 구조적 원인(복수 누적)."""
    if e.diff is None:
        return
    if sg_unavailable and e.diff.unexplained and SYSTEMIC_SECURITY_GROUP_UNAVAILABLE not in e.diff.systemic:
        e.diff.systemic.append(SYSTEMIC_SECURITY_GROUP_UNAVAILABLE)
    state["details"] = {**e.diff.summary(),
                        "snapshot_prev_date": e.prev_date.isoformat() if e.prev_date else None,
                        "exclusion_raw_now": {t: raw_by_ticker[t] for t in e.diff.unexplained_tickers if t in raw_by_ticker},
                        "raw_file": raw_path, "strict": strict}


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    with connect(cfg.database_url) as conn:
        if args.report_last_failed:
            outcome = report_last_failed(conn)
            log.info(f"exclusion report: {outcome}")
            return 1 if outcome == "failed" else 0
        run_universe(conn, today=date.today(), accept_exclusion_diff=args.accept_exclusion_diff, strict=args.strict_exclusion_diff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
