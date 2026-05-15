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
