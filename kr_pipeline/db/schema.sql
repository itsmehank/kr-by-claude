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
