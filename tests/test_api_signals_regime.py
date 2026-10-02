"""#207 회신 21 — signals API 가 volume_regime_flag 를 노출한다."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.deps import get_conn
from api.main import app
from kr_pipeline.common.data_regimes import VOLUME_REGIME_BOUNDARY
from tests.test_llm_runner_store import _s9_result


def test_signals_api_exposes_volume_regime_flag(db):
    from kr_pipeline.llm_runner.store import insert_entry_params

    def override():
        yield db
    app.dependency_overrides[get_conn] = override
    try:
        now = datetime.now(timezone.utc)
        with db.cursor() as cur:
            cur.execute("INSERT INTO stocks (ticker, name, market) VALUES ('VRA1','VRA1','KOSPI') ON CONFLICT (ticker) DO NOTHING")
            cur.execute("DELETE FROM entry_params WHERE symbol='VRA1'")
            cur.execute("DELETE FROM daily_prices WHERE ticker='VRA1'")
            # (PR-3) flag 는 창 유도 — 경계 전후 일봉을 깔아 일간 50봉 창이 경계에 걸치게 한다(close=pivot 1000, sanity 중립)
            cur.executemany("INSERT INTO daily_prices (ticker, date, open, high, low, close, adj_close, volume, value) "
                            "VALUES ('VRA1', %s, 1000,1000,1000,1000,1000,1,1)",
                            [(VOLUME_REGIME_BOUNDARY + timedelta(days=k),) for k in range(-10, 1) if (VOLUME_REGIME_BOUNDARY + timedelta(days=k)).weekday() < 5])
        insert_entry_params(db, symbol="VRA1", signal_at=now, result=_s9_result(), trigger_evaluation_at=now, prior_classification_at=now,
                            llm_meta={"duration_s": 1.0, "input_tokens": None, "output_tokens": None}, analyzed_for_date=VOLUME_REGIME_BOUNDARY)
        r = TestClient(app).get("/api/signals", params={"ticker": "VRA1", "days": 3650})
        assert r.status_code == 200, r.text
        row = next(s for s in r.json() if s["symbol"] == "VRA1")
        assert row["volume_regime_flag"] == "mixed"
        assert "volume_regime_unverified_#207" not in row["known_warnings"]
    finally:
        app.dependency_overrides.pop(get_conn, None)
