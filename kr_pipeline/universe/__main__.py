import argparse
from datetime import date, timedelta
import logging

import pandas as pd

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.common.security_group import UNRESOLVED
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.universe.fetch import fetch_universe, fetch_sectors, fetch_security_groups
from kr_pipeline.universe.guards import count_active, verify_universe_after_load
from kr_pipeline.universe.transform import split_universe
from kr_pipeline.universe.store import upsert_stocks, mark_delisted, save_universe_raw_snapshot


log = logging.getLogger("kr_pipeline.universe")


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


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m kr_pipeline.universe")
    p.add_argument("--accept-exclusion-diff", action="store_true",
                   help="배제 집합 스냅샷 변동을 설명된 것으로 수용(원인 확인 후에만)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Config.load()
    setup_logging(cfg.log_level)
    today = date.today()

    with connect(cfg.database_url) as conn:
        with run_tracking(conn, pipeline="universe", mode="full", params={"on_date": today.isoformat()}) as state:
            log.info(f"Fetching universe for {today}")
            df = fetch_universe(today)
            log.info(f"Fetched {len(df)} raw tickers")

            groups = _security_groups_fail_open(today, state["warnings"])
            df["security_group"] = df["ticker"].map(groups).fillna(UNRESOLVED)
            # (#195 커밋2 부수) 필터 전 원본 전량 저장 — #191 판정 전제(KRX 재접촉 없이 차집합 계산).
            raw_saved = save_universe_raw_snapshot(conn, today, df)
            log.info(f"Saved raw universe snapshot: {raw_saved} rows")
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
            #   wake: 배제 집합 스냅샷 가드가 "기존 포함 → 신규 배제" 차분을 처음 잡는 시점 — 그 차분은
            #   --accept-exclusion-diff 단독 수용 금지, 의미 정정 + 상태 컬럼 동시 착수.
            delisted = mark_delisted(conn, current_tickers=set(df["ticker"]), on_date=today)
            log.info(f"Marked {delisted} as delisted")

            info = verify_universe_after_load(conn, snapshot_date=today, excluded=excluded,
                                              accept_exclusion_diff=args.accept_exclusion_diff)
            info["active_before"] = active_before
            # (c) 종목 수 변동 기록 — 임계 없음(별도 판정 사안). UNRESOLVED 건수 = 유니버스 무음 축소 감지용.
            log.info(f"universe {active_before} -> {info['active_after']} | qualifying_pool {info['qualifying_pool']} "
                     f"| row_kept_excluded {info['row_kept_excluded']} | UNRESOLVED {info['unresolved']} "
                     f"| exclusion +{len(info['exclusion_added'])} -{len(info['exclusion_removed'])}")
            if info["unresolved"]:
                state["warnings"].append(f"security_group_unresolved: {info['unresolved']}종목")
            state["details"] = info
            state["rows_affected"] = affected
            state["total_count"] = info["active_after"]

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
