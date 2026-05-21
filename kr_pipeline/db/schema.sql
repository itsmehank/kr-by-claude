CREATE TABLE IF NOT EXISTS stocks (
    ticker        VARCHAR(10)  PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    market        VARCHAR(10)  NOT NULL,
    sector        VARCHAR(100),
    listed_at     DATE,
    delisted_at   DATE,
    is_common     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks(market) WHERE delisted_at IS NULL;

CREATE TABLE IF NOT EXISTS daily_prices (
    ticker        VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    date          DATE          NOT NULL,
    open          NUMERIC(12,2) NOT NULL,
    high          NUMERIC(12,2) NOT NULL,
    low           NUMERIC(12,2) NOT NULL,
    close         NUMERIC(12,2) NOT NULL,
    adj_close     NUMERIC(12,4) NOT NULL,
    volume        BIGINT        NOT NULL,
    value         BIGINT        NOT NULL,
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date);

CREATE TABLE IF NOT EXISTS index_daily (
    index_code    VARCHAR(10)   NOT NULL,
    date          DATE          NOT NULL,
    open          NUMERIC(12,2) NOT NULL,
    high          NUMERIC(12,2) NOT NULL,
    low           NUMERIC(12,2) NOT NULL,
    close         NUMERIC(12,2) NOT NULL,
    volume        BIGINT,
    value         BIGINT,
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code, date)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id            BIGSERIAL PRIMARY KEY,
    pipeline      VARCHAR(50)  NOT NULL,
    mode          VARCHAR(20)  NOT NULL,
    started_at    TIMESTAMPTZ  NOT NULL,
    finished_at   TIMESTAMPTZ,
    status        VARCHAR(20)  NOT NULL,
    rows_affected BIGINT,
    total_count   BIGINT,
    details       JSONB,
    error         TEXT,
    params        JSONB
);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_recent ON pipeline_runs(pipeline, started_at DESC);

-- ====== Weekly (#1.5) ======

CREATE TABLE IF NOT EXISTS weekly_prices (
    ticker          VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    week_end_date   DATE          NOT NULL,
    open            NUMERIC(12,2) NOT NULL,
    high            NUMERIC(12,2) NOT NULL,
    low             NUMERIC(12,2) NOT NULL,
    close           NUMERIC(12,2) NOT NULL,
    adj_close       NUMERIC(12,4) NOT NULL,
    volume          BIGINT        NOT NULL,
    value           BIGINT        NOT NULL,
    trading_days    SMALLINT      NOT NULL,
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, week_end_date)
);
CREATE INDEX IF NOT EXISTS idx_weekly_prices_date ON weekly_prices(week_end_date);

CREATE TABLE IF NOT EXISTS weekly_index (
    index_code      VARCHAR(10)   NOT NULL,
    week_end_date   DATE          NOT NULL,
    open            NUMERIC(12,2) NOT NULL,
    high            NUMERIC(12,2) NOT NULL,
    low             NUMERIC(12,2) NOT NULL,
    close           NUMERIC(12,2) NOT NULL,
    volume          BIGINT,
    value           BIGINT,
    trading_days    SMALLINT      NOT NULL,
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_code, week_end_date)
);

-- ====== Indicators (#2) ======

CREATE TABLE IF NOT EXISTS daily_indicators (
    ticker            VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    date              DATE          NOT NULL,

    adj_close         NUMERIC(12,4) NOT NULL,

    sma_10            NUMERIC(12,4),
    sma_21            NUMERIC(12,4),       -- VCP / 단기 모멘텀 분석용 (Trend Template 외)
    sma_50            NUMERIC(12,4),
    sma_150           NUMERIC(12,4),
    sma_200           NUMERIC(12,4),

    w52_high          NUMERIC(12,4),
    w52_low           NUMERIC(12,4),
    pct_from_52w_high NUMERIC(8,4),
    pct_from_52w_low  NUMERIC(8,4),

    rs_line               NUMERIC(16,8),
    rs_line_52w_high      NUMERIC(16,8),
    rs_line_52w_high_date DATE,
    rs_line_at_52w_high   BOOLEAN,
    rs_line_uptrend_6w    BOOLEAN,
    rs_line_uptrend_13w   BOOLEAN,
    rs_line_in_decline_7m BOOLEAN,

    rs_rating         SMALLINT,

    minervini_c1      BOOLEAN,
    minervini_c2      BOOLEAN,
    minervini_c3      BOOLEAN,
    minervini_c4      BOOLEAN,
    minervini_c5      BOOLEAN,
    minervini_c6      BOOLEAN,
    minervini_c7      BOOLEAN,
    minervini_c8      BOOLEAN,
    minervini_pass    BOOLEAN,

    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_daily_indicators_date ON daily_indicators(date);
CREATE INDEX IF NOT EXISTS idx_daily_indicators_minervini ON daily_indicators(date, minervini_pass)
    WHERE minervini_pass = TRUE;
CREATE INDEX IF NOT EXISTS idx_daily_indicators_rs ON daily_indicators(date, rs_rating)
    WHERE rs_rating >= 70;
CREATE INDEX IF NOT EXISTS idx_daily_indicators_analyst_target ON daily_indicators(date, rs_rating)
    WHERE minervini_pass = TRUE AND rs_rating >= 80;

CREATE TABLE IF NOT EXISTS weekly_indicators (
    ticker            VARCHAR(10)   NOT NULL REFERENCES stocks(ticker),
    week_end_date     DATE          NOT NULL,

    adj_close         NUMERIC(12,4) NOT NULL,

    sma_10w           NUMERIC(12,4),
    sma_30w           NUMERIC(12,4),
    sma_40w           NUMERIC(12,4),

    w52_high          NUMERIC(12,4),
    w52_low           NUMERIC(12,4),
    pct_from_52w_high NUMERIC(8,4),
    pct_from_52w_low  NUMERIC(8,4),

    rs_line               NUMERIC(16,8),
    rs_line_52w_high      NUMERIC(16,8),
    rs_line_52w_high_date DATE,
    rs_line_at_52w_high   BOOLEAN,
    rs_line_uptrend_6w    BOOLEAN,
    rs_line_uptrend_13w   BOOLEAN,
    rs_line_in_decline_7m BOOLEAN,

    rs_rating         SMALLINT,

    minervini_c1      BOOLEAN,
    minervini_c2      BOOLEAN,
    minervini_c3      BOOLEAN,
    minervini_c4      BOOLEAN,
    minervini_c5      BOOLEAN,
    minervini_c6      BOOLEAN,
    minervini_c7      BOOLEAN,
    minervini_c8      BOOLEAN,
    minervini_pass    BOOLEAN,

    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, week_end_date)
);
CREATE INDEX IF NOT EXISTS idx_weekly_indicators_date ON weekly_indicators(week_end_date);
CREATE INDEX IF NOT EXISTS idx_weekly_indicators_minervini ON weekly_indicators(week_end_date, minervini_pass)
    WHERE minervini_pass = TRUE;

-- ====== Indicators V2: Volume (#2-V2) ======

ALTER TABLE daily_indicators
    ADD COLUMN IF NOT EXISTS volume                    NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS avg_volume_50d            NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS volume_ratio_50d          NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS pocket_pivot_flag         BOOLEAN,
    ADD COLUMN IF NOT EXISTS volume_dry_up_flag        BOOLEAN,
    ADD COLUMN IF NOT EXISTS up_down_volume_ratio_50d  NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS distribution_day_flag     BOOLEAN;

CREATE INDEX IF NOT EXISTS idx_daily_indicators_pocket_pivot
    ON daily_indicators(date) WHERE pocket_pivot_flag = TRUE;
CREATE INDEX IF NOT EXISTS idx_daily_indicators_distribution
    ON daily_indicators(date) WHERE distribution_day_flag = TRUE;

ALTER TABLE weekly_indicators
    ADD COLUMN IF NOT EXISTS volume                    NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS avg_volume_10w            NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS volume_ratio_10w          NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS up_down_volume_ratio_10w  NUMERIC(10,4);

-- ====== Market Context (#2.5) ======

CREATE TABLE IF NOT EXISTS market_context_daily (
    date                             DATE          NOT NULL,
    index_code                       VARCHAR(10)   NOT NULL,           -- '1001' (KOSPI) / '2001' (KOSDAQ)
    current_status                   VARCHAR(20)   NOT NULL,           -- confirmed_uptrend / rally_attempt / correction / downtrend
    distribution_day_count_last_25   SMALLINT,
    last_follow_through_day          DATE,
    days_since_follow_through        SMALLINT,
    pct_stocks_above_200d_ma         NUMERIC(5,2),
    computation_notes                TEXT,
    updated_at                       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (date, index_code)
);
CREATE INDEX IF NOT EXISTS idx_market_context_date ON market_context_daily(date);

-- ====== Corporate Actions (#2.6) ======

CREATE TABLE IF NOT EXISTS dart_corp_codes (
    stock_code  VARCHAR(10)  PRIMARY KEY,
    corp_code   VARCHAR(20)  NOT NULL,
    corp_name   VARCHAR(200),
    modify_date DATE,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    id                    BIGSERIAL    PRIMARY KEY,
    ticker                VARCHAR(10)  NOT NULL REFERENCES stocks(ticker),
    event_date            DATE         NOT NULL,
    event_type            VARCHAR(30)  NOT NULL,
    ratio                 VARCHAR(50),
    note                  TEXT,
    dart_rcept_no         VARCHAR(20),
    raw_disclosure_title  TEXT,
    fetched_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, event_date, event_type, dart_rcept_no)
);
CREATE INDEX IF NOT EXISTS idx_corp_actions_ticker_date
    ON corporate_actions(ticker, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_corp_actions_event_type_date
    ON corporate_actions(event_type, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_corp_actions_recent_distress
    ON corporate_actions(event_date DESC)
    WHERE event_type IN ('reverse_split', 'capital_reduction');

-- ─── #4 LLM Runner 스키마 (B v3 갭 1-8 day-1 통합) ───────────────
-- (drawdown_52w_pct / drawdown_filter_pass 컬럼은 2026-05-21 제거 — false
--  negative 80% 사유로 LLM 게이트 폐기 후 완전 정리. 마이그레이션:
--  ALTER TABLE daily_indicators DROP COLUMN drawdown_52w_pct,
--                               DROP COLUMN drawdown_filter_pass;)

-- 주말 (5) + 평일 daily-delta 분류 결과 (append-only)
CREATE TABLE IF NOT EXISTS weekly_classification (
  symbol               VARCHAR(10) NOT NULL,
  classified_at        TIMESTAMPTZ NOT NULL,
  analyzed_for_date    DATE,
  market               VARCHAR(10) NOT NULL,
  classification       VARCHAR(10) NOT NULL,
  pattern              VARCHAR(50),

  pivot_price          NUMERIC(12, 4),
  pivot_basis          VARCHAR(30),
  base_high            NUMERIC(12, 4),
  base_low             NUMERIC(12, 4),
  base_depth_pct       NUMERIC(5, 2),
  base_start_date      DATE,

  risk_flags           JSONB,
  confidence           NUMERIC(3, 2),
  reasoning            TEXT,

  source               VARCHAR(20) NOT NULL,

  llm_call_duration_s  NUMERIC(8, 2),
  llm_input_tokens     INTEGER,
  llm_output_tokens    INTEGER,

  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, classified_at)
);

CREATE INDEX IF NOT EXISTS idx_weekly_classification_active
  ON weekly_classification (symbol)
  WHERE classification IN ('entry', 'watch');

CREATE INDEX IF NOT EXISTS idx_weekly_classification_recent
  ON weekly_classification (classified_at DESC);

-- (5b) 호출 이력 (append-only, 단순 abort 모델 — severity 없음)
CREATE TABLE IF NOT EXISTS trigger_evaluation_log (
  symbol                  VARCHAR(10) NOT NULL,
  evaluated_at            TIMESTAMPTZ NOT NULL,
  trigger_type            VARCHAR(20) NOT NULL,

  close                   NUMERIC(12, 4),
  volume                  BIGINT,
  pivot_price             NUMERIC(12, 4),

  decision                VARCHAR(10) NOT NULL,
  confidence              NUMERIC(3, 2),
  reasoning               TEXT,
  abort_reason            VARCHAR(60),

  prior_classification_at TIMESTAMPTZ NOT NULL,

  llm_call_duration_s     NUMERIC(8, 2),
  llm_input_tokens        INTEGER,
  llm_output_tokens       INTEGER,

  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, evaluated_at)
);

CREATE INDEX IF NOT EXISTS idx_trigger_log_recent
  ON trigger_evaluation_log (evaluated_at DESC);

-- (6) 매수 파라미터 (v2.0 의 17 필드 그대로)
CREATE TABLE IF NOT EXISTS entry_params (
  symbol                                  VARCHAR(10) NOT NULL,
  signal_at                               TIMESTAMPTZ NOT NULL,

  entry_mode                              VARCHAR(30),
  trigger_price                           NUMERIC(12, 4),
  entry_price                             NUMERIC(12, 4),

  stop_loss                               NUMERIC(12, 4),
  stop_loss_pct_from_pivot                NUMERIC(6, 2),
  stop_loss_pct_from_current_price        NUMERIC(6, 2),
  stop_loss_basis                         VARCHAR(30),

  expected_target_price                   NUMERIC(12, 4),
  expected_target_pct                     NUMERIC(6, 2),
  risk_reward_ratio                       NUMERIC(5, 2),

  position_size_pct                       NUMERIC(5, 2),
  position_size_basis                     TEXT,

  breakout_volume_requirement             VARCHAR(30),
  observed_breakout_volume_ratio          NUMERIC(5, 2),

  known_warnings                          JSONB,
  other_warnings                          TEXT,
  notes                                   TEXT,

  trigger_evaluation_at                   TIMESTAMPTZ NOT NULL,
  prior_classification_at                 TIMESTAMPTZ NOT NULL,

  llm_call_duration_s                     NUMERIC(8, 2),
  llm_input_tokens                        INTEGER,
  llm_output_tokens                       INTEGER,

  created_at                              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, signal_at)
);

CREATE INDEX IF NOT EXISTS idx_entry_params_recent ON entry_params (signal_at DESC);

-- 시그널 사후 평가 (cron backfill)
CREATE TABLE IF NOT EXISTS signal_performance (
  symbol               VARCHAR(10) NOT NULL,
  signal_at            TIMESTAMPTZ NOT NULL,
  entry_price          NUMERIC(12, 4) NOT NULL,

  price_1w             NUMERIC(12, 4),
  price_2w             NUMERIC(12, 4),
  price_4w             NUMERIC(12, 4),
  price_8w             NUMERIC(12, 4),

  return_1w_pct        NUMERIC(8, 2),
  return_2w_pct        NUMERIC(8, 2),
  return_4w_pct        NUMERIC(8, 2),
  return_8w_pct        NUMERIC(8, 2),

  market_return_1w_pct NUMERIC(8, 2),
  market_return_2w_pct NUMERIC(8, 2),
  market_return_4w_pct NUMERIC(8, 2),
  market_return_8w_pct NUMERIC(8, 2),

  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (symbol, signal_at),
  FOREIGN KEY (symbol, signal_at) REFERENCES entry_params(symbol, signal_at) ON DELETE CASCADE
);
