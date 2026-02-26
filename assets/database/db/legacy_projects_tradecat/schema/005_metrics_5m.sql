-- Binance Futures Metrics 5m (aligned with candles_1m metadata)

CREATE SCHEMA IF NOT EXISTS market_data;

CREATE TABLE IF NOT EXISTS market_data.binance_futures_metrics_5m (
    create_time                      TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    symbol                           TEXT                        NOT NULL,
    sum_open_interest                NUMERIC,
    sum_open_interest_value          NUMERIC,
    count_toptrader_long_short_ratio NUMERIC,
    sum_toptrader_long_short_ratio   NUMERIC,
    count_long_short_ratio           NUMERIC,
    sum_taker_long_short_vol_ratio   NUMERIC,
    exchange                         TEXT NOT NULL DEFAULT 'binance_futures_um',
    source                           TEXT NOT NULL DEFAULT 'binance_zip',
    is_closed                        BOOLEAN NOT NULL DEFAULT TRUE,
    ingested_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        create_time = date_trunc('minute', create_time)
        AND (EXTRACT(MINUTE FROM create_time)::int % 5 = 0)
    )
);

-- Hypertable
SELECT create_hypertable(
    'market_data.binance_futures_metrics_5m',
    'create_time',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- 唯一约束防重（需在导入前确保无重复）
DO $$
BEGIN
    ALTER TABLE market_data.binance_futures_metrics_5m
        ADD CONSTRAINT uq_metrics_5m UNIQUE (symbol, create_time);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- 索引
CREATE INDEX IF NOT EXISTS idx_metrics_5m_symbol_time
    ON market_data.binance_futures_metrics_5m(symbol, create_time DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_5m_exchange_symbol_time
    ON market_data.binance_futures_metrics_5m(exchange, symbol, create_time DESC);

-- 压缩策略（按 symbol 分段，时间倒序压缩）
ALTER TABLE IF EXISTS market_data.binance_futures_metrics_5m
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'symbol',
         timescaledb.compress_orderby = 'create_time DESC');

DO $$
BEGIN
    PERFORM add_compression_policy('market_data.binance_futures_metrics_5m', INTERVAL '7 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- 可选：保留策略，按需启用
-- DO $$
-- BEGIN
--     PERFORM add_retention_policy('market_data.binance_futures_metrics_5m', INTERVAL '730 days');
-- EXCEPTION WHEN duplicate_object THEN NULL;
-- END$$;

