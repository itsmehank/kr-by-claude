"""evaluate_pivot 입구 가드 — base_low(stop_loss) NULL 종목이 제외되지 않음."""


def test_run_does_not_skip_null_stop_loss(mocker):
    import kr_pipeline.llm_runner.evaluate_pivot as ep
    active = [{
        "symbol": "X", "classification": "entry",
        "close": 82500, "pivot_price": 80000,
        "volume": 1_500_000, "avg_volume_50d": 1_000_000,
        "sma_50": 78000, "stop_loss": None,
    }]
    mocker.patch.object(ep, "get_active_with_current", return_value=active)
    proc = mocker.patch.object(ep, "_process_one")  # avoid build_for_5b / LLM / DB
    conn = mocker.MagicMock()  # conn.commit() is a no-op mock

    r = ep.run(conn=conn, dry_run=True)

    proc.assert_called_once()   # stop_loss None 이어도 skip 안 되고 처리됨 (breakout)
    assert r["evaluated"] == 1
