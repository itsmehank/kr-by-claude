"""#207 회신 21 Q-5c 1 — 봉 단위 volume_regime + 판정 행 flag(PR-2 규칙)."""
from datetime import date, datetime, timedelta, timezone

from kr_pipeline.common.data_regimes import (
    FLAG_MIXED, REGIME_EXTENDED, REGIME_MIXED, REGIME_REGULAR, VOLUME_REGIME_BOUNDARY,
    VOLUME_REGIME_UNVERIFIED_FROM, regime_flag_for_as_of, regime_for_date,
)

B = VOLUME_REGIME_BOUNDARY


def test_constants_and_alias():
    assert VOLUME_REGIME_UNVERIFIED_FROM == B
    assert (REGIME_REGULAR, REGIME_EXTENDED, REGIME_MIXED, FLAG_MIXED) == ("regular", "extended", "mixed", "mixed")


def test_regime_for_date_boundary():
    assert regime_for_date(B - timedelta(days=1)) == "regular"
    assert regime_for_date(B) == "extended"


def test_regime_flag_for_as_of_pr2_rule():
    assert regime_flag_for_as_of(None) is None
    assert regime_flag_for_as_of(B - timedelta(days=1)) is None
    assert regime_flag_for_as_of(B) == "mixed"
    assert regime_flag_for_as_of(datetime(B.year, B.month, B.day, 9, tzinfo=timezone.utc)) == "mixed"
    assert regime_flag_for_as_of(B.isoformat()) == "mixed"


def test_schema_columns_exist(db):
    with db.cursor() as cur:
        for table in ("daily_prices", "index_daily", "weekly_prices"):
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name='volume_regime'", (table,))
            assert cur.fetchone(), table
        for table in ("weekly_classification", "trigger_evaluation_log", "entry_params",
                      "position_climax_evaluations", "position_decline_evaluations"):
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s AND column_name='volume_regime_flag'", (table,))
            assert cur.fetchone(), table
