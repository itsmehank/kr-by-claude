from datetime import date
import logging

from kr_pipeline.common.config import Config
from kr_pipeline.common.logging import setup_logging
from kr_pipeline.db.connection import connect
from kr_pipeline.db.runs import run_tracking
from kr_pipeline.universe.fetch import fetch_universe, fetch_sectors
from kr_pipeline.universe.transform import filter_common_stocks
from kr_pipeline.universe.store import upsert_stocks, mark_delisted


log = logging.getLogger("kr_pipeline.universe")


def main() -> int:
    cfg = Config.load()
    setup_logging(cfg.log_level)
    today = date.today()

    with connect(cfg.database_url) as conn:
        with run_tracking(conn, pipeline="universe", mode="full", params={"on_date": today.isoformat()}) as _state:
            log.info(f"Fetching universe for {today}")
            df = fetch_universe(today)
            log.info(f"Fetched {len(df)} raw tickers")

            df = filter_common_stocks(df)
            log.info(f"After filter: {len(df)} common stocks")

            # 섹터 머지
            sectors = []
            for market in ("KOSPI", "KOSDAQ"):
                try:
                    sectors.append(fetch_sectors(today, market))
                except Exception as e:
                    log.warning(f"Sector fetch failed for {market}: {e}")
            if sectors:
                import pandas as pd
                sector_df = pd.concat(sectors, ignore_index=True)
                df = df.merge(sector_df, on="ticker", how="left")
            else:
                df["sector"] = None

            affected = upsert_stocks(conn, df)
            log.info(f"Upserted {affected} stocks")

            delisted = mark_delisted(conn, current_tickers=set(df["ticker"]), on_date=today)
            log.info(f"Marked {delisted} as delisted")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
