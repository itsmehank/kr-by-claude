"""weekend / daily_delta 단계가 분류 1건마다 freeze 1건을 생성하는지."""
from __future__ import annotations

from datetime import date


def _seed_ticker(db, ticker: str, as_of: date) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO stocks (ticker, name, market) VALUES (%s, %s, 'KOSPI') ON CONFLICT DO NOTHING",
            (ticker, ticker),
        )
        cur.execute(
            """INSERT INTO daily_indicators
               (ticker, date, adj_close, minervini_pass)
               VALUES (%s, %s, 100, TRUE) ON CONFLICT DO NOTHING""",
            (ticker, as_of),
        )
    db.commit()


def test_weekend_run_creates_freeze_per_classification(db, tmp_path, monkeypatch):
    """weekend dry_run=False: 분류 1건 → freeze 1건, stage='weekend', sha256 일치."""
    import hashlib
    from api.services.freeze_store import fetch_latest_freeze, read_artifact_from_uri

    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)

    today = date(2026, 5, 29)
    ticker = "FRWK1"
    _seed_ticker(db, ticker, today)

    fake_zip = b"PK\x03\x04fake_weekend_zip"
    monkeypatch.setattr("kr_pipeline.llm_runner.weekend.build_analysis_inline",
                        lambda *a, **k: ("inline", ["/tmp/_frpng/daily_chart.png", "/tmp/_frpng/weekly_chart.png"], fake_zip))
    monkeypatch.setattr(
        "kr_pipeline.llm_runner.weekend.call_claude",
        lambda **k: {
            "classification": "watch",
            "confidence": 0.7,
            "reasoning": "test",
        },
    )

    from kr_pipeline.llm_runner.weekend import run
    result = run(db, dry_run=False, as_of=today, ticker=ticker)

    assert result["processed"] == 1

    frozen = fetch_latest_freeze(db, ticker, "weekend")
    assert frozen is not None
    assert frozen.stage == "weekend"
    assert frozen.ticker == ticker
    data = read_artifact_from_uri(frozen.artifact_uri)
    assert data == fake_zip
    assert frozen.artifact_sha256 == hashlib.sha256(fake_zip).hexdigest()


def test_weekend_dry_run_creates_freeze(db, tmp_path, monkeypatch):
    """dry_run=True 모드: LLM 결과 DB 저장 없지만 freeze 는 생성됨."""
    from api.services.freeze_store import fetch_latest_freeze

    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)

    today = date(2026, 5, 29)
    ticker = "FRWK2"
    _seed_ticker(db, ticker, today)

    fake_zip = b"PK\x03\x04dry_run_zip"
    monkeypatch.setattr("kr_pipeline.llm_runner.weekend.build_analysis_inline",
                        lambda *a, **k: ("inline", ["/tmp/_frpng/daily_chart.png", "/tmp/_frpng/weekly_chart.png"], fake_zip))
    monkeypatch.setattr(
        "kr_pipeline.llm_runner.weekend.call_claude",
        lambda **k: {"classification": "ignore", "confidence": 0.5, "reasoning": "dry"},
    )

    from kr_pipeline.llm_runner.weekend import run
    result = run(db, dry_run=True, as_of=today, ticker=ticker)

    assert result["processed"] == 1
    frozen = fetch_latest_freeze(db, ticker, "weekend")
    assert frozen is not None
    assert frozen.classification_id is None  # dry_run: no classification row


def test_daily_delta_run_creates_freeze(db, tmp_path, monkeypatch):
    """daily_delta: freeze 1건 생성, stage='daily_delta'."""
    from api.services.freeze_store import fetch_latest_freeze

    monkeypatch.setattr("api.services.freeze_store.FREEZE_ROOT", tmp_path)

    today = date(2026, 5, 29)
    ticker = "FRDD1"
    _seed_ticker(db, ticker, today)

    fake_zip = b"PK\x03\x04fake_delta_zip"
    monkeypatch.setattr("kr_pipeline.llm_runner.daily_delta.build_analysis_inline",
                        lambda *a, **k: ("inline", ["/tmp/_frpng/daily_chart.png", "/tmp/_frpng/weekly_chart.png"], fake_zip))
    monkeypatch.setattr(
        "kr_pipeline.llm_runner.daily_delta.call_claude",
        lambda **k: {"classification": "watch", "confidence": 0.6, "reasoning": "delta"},
    )
    # find_new_tickers returns our test ticker
    monkeypatch.setattr(
        "kr_pipeline.llm_runner.daily_delta.find_new_tickers",
        lambda *a, **k: [ticker],
    )

    from kr_pipeline.llm_runner.daily_delta import run
    result = run(db, dry_run=False, as_of=today, limit=1)

    assert result["processed"] == 1
    frozen = fetch_latest_freeze(db, ticker, "daily_delta")
    assert frozen is not None
    assert frozen.stage == "daily_delta"
