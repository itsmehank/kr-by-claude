import argparse
import json
import os
from datetime import date, timedelta
import logging

import pandas as pd

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.common.security_group import UNRESOLVED
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.universe.exclusion_diff import SYSTEMIC_RAW_SHRUNK
from kr_pipeline.universe.guards import UniverseGuardError, count_active, verify_universe_after_load
from kr_pipeline.universe.report import report_last_failed
from kr_pipeline.universe.transform import split_universe
from kr_pipeline.universe.store import upsert_stocks, mark_delisted, save_universe_raw_snapshot


log = logging.getLogger("kr_pipeline.universe")

SYSTEMIC_SECURITY_GROUP_UNAVAILABLE = "security_group_unavailable"
# 이번 원본이 직전 원본(universe_raw_snapshot)보다 시장별로 이 비율 넘게 줄면 부분 응답 의심 → 상폐 자동 수용 보류(exclusion_diff raw_complete).
# 값은 store.mark_delisted 의 _MAX_DELIST_RATIO(2%) 와 동일 근거(한 달 상폐 규모 상한) — 별도 수치 아님.
RAW_SHRINK_MAX_RATIO = 0.02


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


def _persist_raw_response(df: pd.DataFrame, today: date) -> str | None:
    """운영 규칙 5: KRX 응답은 적재 성공과 무관하게 적재 전 파일 보존(가드 실패 시 run_tracking 이 raw 스냅샷 행을 롤백하므로).
    위치 = $KR_VERIFICATION_DIR(기본 data/verification). 실패는 경고만."""
    try:
        d = os.environ.get("KR_VERIFICATION_DIR") or "data/verification"
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"universe_raw_{today:%Y%m%d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"fetched_for": today.isoformat(), "rows": json.loads(df.to_json(orient="records", force_ascii=False))}, f, ensure_ascii=False)
        return path
    except Exception as e:  # noqa: BLE001
        log.warning("universe raw 응답 파일 보존 실패: %s", e)
        return None


def _raw_complete(conn, df: pd.DataFrame, today: date) -> bool:
    """시장별 원본 종목 수가 직전 universe_raw_snapshot 대비 RAW_SHRINK_MAX_RATIO 넘게 줄지 않았는가(부분 응답 2차 신호, 리뷰 #223 3차)."""
    with conn.cursor() as cur:
        cur.execute("SELECT market, COUNT(*) FROM universe_raw_snapshot WHERE snapshot_date = "
                    "(SELECT MAX(snapshot_date) FROM universe_raw_snapshot WHERE snapshot_date < %s) GROUP BY market", (today,))
        prev = {m: n for m, n in cur.fetchall()}
    if not prev:
        return True
    now = df["market"].value_counts().to_dict()
    for m, n_prev in prev.items():
        n_now = now.get(m, 0)
        if n_prev > 0 and (n_prev - n_now) / n_prev > RAW_SHRINK_MAX_RATIO:
            log.warning("universe raw 급감: %s %d → %d (%.1f%%) — 상폐 자동 수용 보류", m, n_prev, n_now, 100 * (n_prev - n_now) / n_prev)
            return False
    return True


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
    """유니버스 갱신 1회. (#221) guard(snapshot) 잔여분이 있으면 판정 전체(+이번 원본 행 사본)를 실패 run 의 details 에 남기고 예외.
    조사 보고서(LLM·Slack)는 이 함수 밖 — `--report-last-failed`(monthly_chain 이 data 락 해제 후 호출)가 커밋된 상태에서 수행."""
    if accept_exclusion_diff and strict:
        raise ValueError("--accept-exclusion-diff 와 --strict-exclusion-diff 는 동시 지정 불가(의미 충돌)")   # KRX 접촉 전에 거른다
    with run_tracking(conn, pipeline="universe", mode="full", params={"on_date": today.isoformat()}) as state:
        return _run_universe_inner(conn, state, today=today, accept_exclusion_diff=accept_exclusion_diff, strict=strict)


def _run_universe_inner(conn, state: dict, *, today: date, accept_exclusion_diff: bool, strict: bool) -> dict:
    log.info(f"Fetching universe for {today}")
    df = fetch_universe(today)
    log.info(f"Fetched {len(df)} raw tickers")
    raw_tickers = set(df["ticker"])          # (#221) 필터 전 원본 — removed 가 상폐인지(원본에도 없음) 판정
    raw_path = _persist_raw_response(df, today)          # 운영 규칙 5(회신 16) — 가드 실패로 롤백돼도 응답은 파일에
    raw_complete = _raw_complete(conn, df, today)

    groups = _security_groups_fail_open(today, state["warnings"])
    sg_unavailable = not groups
    df["security_group"] = df["ticker"].map(groups).fillna(UNRESOLVED)
    # (#195 커밋2 부수) 필터 전 원본 전량 저장 — #191 판정 전제(KRX 재접촉 없이 차집합 계산).
    raw_saved = save_universe_raw_snapshot(conn, today, df)
    log.info(f"Saved raw universe snapshot: {raw_saved} rows (file: {raw_path})")
    raw_by_ticker = {r.ticker: {"name": r.name, "market": r.market, "security_group": r.security_group}
                     for r in df[["ticker", "name", "market", "security_group"]].itertuples(index=False)}
    df, excluded = split_universe(df)
    log.info(f"After pre-load exclusion: {len(df)} kept / {len(excluded)} excluded "
             f"{excluded['axis'].value_counts().to_dict() if not excluded.empty else {}}")

    # 섹터 머지
    sectors = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            sectors.append(fetch_sectors(today, market))
        except Exception as e:
            log.warning(f"Sector fetch failed for {market}: {e}")
    if sectors:
        df = df.merge(pd.concat(sectors, ignore_index=True), on="ticker", how="left")
    else:
        df["sector"] = None

    active_before = count_active(conn)
    affected = upsert_stocks(conn, df)
    log.info(f"Upserted {affected} stocks")

    # [#199 사실 기록, 전문가 회신 10 — 보류(C)] (1) mark_delisted 비교 대상 = 이 df = 적재 전 배제 **후** 목록.
    #   따라서 적재 전 배제 축에 새 구분을 넣으면 기존 활성 종목이 "상장 원본에 없음"과 같은 취급으로 폐지 처리된다
    #   (의미 정정 필요: 원본 목록 기준). (2) 시세 수집 대상은 stocks.delisted_at IS NULL 기반(ohlcv/modes._load_active_tickers)
    #   → "상장 중·대상 아님" 상태는 기존 필드 전용이 아니라 컬럼 추가 방향. 둘은 동시에만 가능.
    #   (#221) 배제 집합 스냅샷 가드가 "기존 포함 → 신규 배제" 차분을 잡으면 exclusion_diff 가 kind='199' 잔여로 분류해 자동 수용하지 않고
    #   --accept-exclusion-diff 로도 거부한다(guards) — 의미 정정 + 상태 컬럼 동시 착수 전까지 그 달의 universe 는 멈춘다(설계된 멈춤).
    delisted = mark_delisted(conn, current_tickers=set(df["ticker"]), on_date=today)
    log.info(f"Marked {delisted} as delisted")

    try:
        info = verify_universe_after_load(conn, snapshot_date=today, excluded=excluded, raw_tickers=raw_tickers,
                                          accept_exclusion_diff=accept_exclusion_diff, auto_accept=not strict, raw_complete=raw_complete)
    except UniverseGuardError as e:
        if e.diff is not None:
            # (리뷰 #223) 실패 행에도 판정 전체를 성공 행과 같은 키 모양으로 남긴다(오류 문자열은 20개 절단) — 보고서·사람 수용의 근거.
            # 이번 원본 행은 롤백되므로 잔여 티커분만 사본 보존. security_group 조회 실패는 구조적 원인(복수 누적).
            if sg_unavailable and e.diff.unexplained and SYSTEMIC_SECURITY_GROUP_UNAVAILABLE not in e.diff.systemic:
                e.diff.systemic.append(SYSTEMIC_SECURITY_GROUP_UNAVAILABLE)
            state["details"] = {**e.diff.summary(),
                                "snapshot_prev_date": e.prev_date.isoformat() if e.prev_date else None,
                                "exclusion_raw_now": {t: raw_by_ticker[t] for t in e.diff.unexplained_tickers if t in raw_by_ticker},
                                "raw_file": raw_path, "strict": strict}
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
    if SYSTEMIC_RAW_SHRUNK in info.get("exclusion_systemic", []):
        state["warnings"].append("universe_raw_shrunk: 직전 원본 대비 시장별 급감 — 상폐 자동 수용 보류")
    state["details"] = info
    state["rows_affected"] = affected
    state["total_count"] = info["active_after"]
    return info


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
