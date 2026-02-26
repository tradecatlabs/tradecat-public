-- 002_taker_buy_and_gap_tracking.sql
--
-- 目的：
-- 1. 在 1m 基础表上追加主动买相关 upsert 能力，支持 VWAP、VPVR 等策略。
-- 2. 建立 missing_intervals 表，用于缺口检测与回填任务的排队与重试。
--
-- 使用说明：
-- - 在执行本脚本前需已运行 001_timescaledb.sql。
-- - 脚本支持幂等执行，所有对象均以 IF NOT EXISTS 或 CREATE OR REPLACE 方式处理。
-- - 若后续已切换为 Timescale 连续聚合（004），缺口表依旧可共存，无需额外操作。

SET search_path TO market_data, public;

-- upsert 函数（主动买可选参数） -----------------------------------------------
DROP FUNCTION IF EXISTS market_data.upsert_candle_1m(TEXT, TEXT, TIMESTAMPTZ, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, BIGINT, BOOLEAN, TEXT, NUMERIC, NUMERIC);
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

DROP FUNCTION IF EXISTS market_data.upsert_candle_1h(TEXT, TEXT, TIMESTAMPTZ, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, BIGINT, BOOLEAN, TEXT);
CREATE OR REPLACE FUNCTION market_data.upsert_candle_1h(
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
    p_source        TEXT    DEFAULT 'ccxt',
    p_taker_buy_volume       NUMERIC DEFAULT NULL,
    p_taker_buy_quote_volume NUMERIC DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
-- 缺口检测表 ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_data.missing_intervals (
    id              BIGSERIAL PRIMARY KEY,
    exchange        TEXT        NOT NULL,
    symbol          TEXT        NOT NULL,
    "interval"     TEXT        NOT NULL,
    gap_start       TIMESTAMPTZ NOT NULL,
    gap_end         TIMESTAMPTZ NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT        NOT NULL DEFAULT 'pending',
    retry_count     INTEGER     NOT NULL DEFAULT 0,
    last_error      TEXT
);

ALTER TABLE market_data.missing_intervals
    DROP CONSTRAINT IF EXISTS missing_intervals_interval_check;

ALTER TABLE market_data.missing_intervals
    ADD CONSTRAINT missing_intervals_interval_check
    CHECK ("interval" IN ('1m','3m','5m','15m','30m','1h','2h','4h','6h','12h','1d','1w','1M'));
