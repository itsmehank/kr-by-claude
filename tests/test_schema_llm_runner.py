"""신규 4 테이블 마이그레이션 검증."""


def test_weekly_classification_schema(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'weekly_classification'
        """)
        cols = {r[0] for r in cur.fetchall()}
    required = {
        "symbol", "classified_at", "market", "classification", "pattern",
        "pivot_price", "pivot_basis", "base_high", "base_low",
        "base_depth_pct", "base_start_date",
        "risk_flags", "confidence", "reasoning",
        "source", "expires_at",
        "llm_call_duration_s", "llm_input_tokens", "llm_output_tokens",
        "created_at",
    }
    assert required.issubset(cols)


def test_trigger_evaluation_log_schema(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'trigger_evaluation_log'
        """)
        cols = {r[0] for r in cur.fetchall()}
    required = {
        "symbol", "evaluated_at", "trigger_type",
        "close", "volume", "pivot_price",
        "decision", "confidence", "reasoning", "abort_reason",
        "prior_classification_at",
    }
    assert required.issubset(cols)
    # 단순 abort 모델 — severity 필드 없음 (spec §6.2)
    assert "abort_severity" not in cols


def test_entry_params_schema(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'entry_params'
        """)
        cols = {r[0] for r in cur.fetchall()}
    # v2.0 의 17 필드 모두 유지 (검토 반영)
    required = {
        "entry_mode", "trigger_price", "entry_price",
        "stop_loss", "stop_loss_pct_from_pivot",
        "stop_loss_pct_from_current_price", "stop_loss_basis",
        "expected_target_price", "expected_target_pct", "risk_reward_ratio",
        "position_size_pct", "position_size_basis",
        "breakout_volume_requirement", "observed_breakout_volume_ratio",
        "known_warnings", "other_warnings", "notes",
    }
    assert required.issubset(cols)


def test_signal_performance_schema(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
             WHERE table_name = 'signal_performance'
        """)
        cols = {r[0] for r in cur.fetchall()}
    required = {
        "symbol", "signal_at", "entry_price",
        "price_1w", "price_2w", "price_4w", "price_8w",
        "return_1w_pct", "return_2w_pct", "return_4w_pct", "return_8w_pct",
        "market_return_1w_pct", "market_return_2w_pct",
        "market_return_4w_pct", "market_return_8w_pct",
    }
    assert required.issubset(cols)
