-- TimescaleDB schema for market data ingestion (1m base only)
-- Higher intervals are derived by continuous aggregates (see 004_continuous_aggregates.sql).

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS market_data;

-- 1m candles ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_data.candles_1m (
    exchange            TEXT        NOT NULL,
    symbol              TEXT        NOT NULL,
    bucket_ts           TIMESTAMPTZ NOT NULL,
    open                NUMERIC(38, 12) NOT NULL,
    high                NUMERIC(38, 12) NOT NULL,
    low                 NUMERIC(38, 12) NOT NULL,
    close               NUMERIC(38, 12) NOT NULL,
    volume              NUMERIC(38, 12) NOT NULL,
    quote_volume        NUMERIC(38, 12),
    trade_count         BIGINT,
    taker_buy_volume        NUMERIC(38, 12),
    taker_buy_quote_volume  NUMERIC(38, 12),
    is_closed           BOOLEAN     NOT NULL DEFAULT FALSE,
    source              TEXT        NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (bucket_ts = date_trunc('minute', bucket_ts)),
    PRIMARY KEY (exchange, symbol, bucket_ts)
);

SELECT create_hypertable(
    'market_data.candles_1m',
    'bucket_ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

ALTER TABLE IF EXISTS market_data.candles_1m
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'exchange,symbol',
         timescaledb.compress_orderby = 'bucket_ts');

DO $$
BEGIN
    PERFORM add_compression_policy('market_data.candles_1m', INTERVAL '3 days');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END$$;

DO $$
BEGIN
    PERFORM add_retention_policy('market_data.candles_1m', INTERVAL '180 days');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END$$;

-- Offset tracking for restarts/differential sync --------------------------
CREATE TABLE IF NOT EXISTS market_data.ingest_offsets (
    exchange            TEXT        NOT NULL,
    symbol              TEXT        NOT NULL,
    interval            TEXT        NOT NULL
                        CHECK (interval IN (
                            '1m','3m','5m','15m','30m',
                            '1h','2h','4h','6h','12h',
                            '1d','1w','1M'
                        )),
    last_closed_ts      TIMESTAMPTZ,
    last_partial_ts     TIMESTAMPTZ,
    last_reconciled_at  TIMESTAMPTZ,
    PRIMARY KEY (exchange, symbol, interval)
);

-- Upsert helper for 1m data -----------------------------------------------
CREATE OR REPLACE FUNCTION market_data.upsert_candle_1m(
    p_exchange      TEXT,
    p_symbol        TEXT,
    p_bucket_ts     TIMESTAMPTZ,
    p_open          NUMERIC,
    p_high          NUMERIC,
    p_low           NUMERIC,
    p_close         NUMERIC,
    p_volume        NUMERIC,
    p_quote_volume  NUMERIC DEFAULT NULL,
    p_trade_count   BIGINT  DEFAULT NULL,
    p_is_closed     BOOLEAN DEFAULT FALSE,
    p_source        TEXT        DEFAULT 'ccxt',
    p_taker_buy_volume       NUMERIC DEFAULT NULL,
    p_taker_buy_quote_volume NUMERIC DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO market_data.candles_1m AS t (
        exchange, symbol, bucket_ts,
        open, high, low, close,
        volume, quote_volume, trade_count,
        taker_buy_volume, taker_buy_quote_volume,
        is_closed, source, ingested_at, updated_at
    ) VALUES (
        p_exchange, p_symbol, p_bucket_ts,
        p_open, p_high, p_low, p_close,
        p_volume, p_quote_volume, p_trade_count,
        p_taker_buy_volume, p_taker_buy_quote_volume,
        p_is_closed, p_source, NOW(), NOW()
    )
    ON CONFLICT (exchange, symbol, bucket_ts)
    DO UPDATE SET
        open        = CASE WHEN t.is_closed AND NOT EXCLUDED.is_closed THEN t.open ELSE EXCLUDED.open END,
        high        = GREATEST(t.high, EXCLUDED.high),
        low         = LEAST(t.low, EXCLUDED.low),
        close       = EXCLUDED.close,
        volume      = EXCLUDED.volume,
        quote_volume= COALESCE(EXCLUDED.quote_volume, t.quote_volume),
        trade_count = COALESCE(EXCLUDED.trade_count, t.trade_count),
        taker_buy_volume = COALESCE(EXCLUDED.taker_buy_volume, t.taker_buy_volume),
        taker_buy_quote_volume = COALESCE(EXCLUDED.taker_buy_quote_volume, t.taker_buy_quote_volume),
        is_closed   = t.is_closed OR EXCLUDED.is_closed,
        source      = EXCLUDED.source,
        updated_at  = NOW();
END;
$$;
