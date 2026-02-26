-- 003_add_all_intervals.sql
--
-- 目标：
-- 1. 扩展 ingest_offsets 可追踪的周期范围（3m~1M）。
-- 2. 引入 Timescale 月线表及对应 upsert 函数，允许直接写入 1M 数据。
-- 3. 为 12h/1w 等长周期提供带主动买参数的 upsert 函数，兼容未来需要的直写路径。
-- 4. 预留 bybit 数据清理 DO 块，用于一键清除指定 exchange 的历史。
--
-- 注意：若系统已启用 004 连续聚合并以视图命名 (candles_3m...candles_1M)，
--       再次执行本脚本将因命名冲突而失败；此文件主要用于备份/回滚参考。

SET search_path TO market_data, public;

-- ingest_offsets 支持更多周期 -------------------------------------------------
ALTER TABLE IF EXISTS market_data.ingest_offsets
    DROP CONSTRAINT IF EXISTS ingest_offsets_interval_check;

ALTER TABLE IF EXISTS market_data.ingest_offsets
    ADD CONSTRAINT ingest_offsets_interval_check
    CHECK ("interval" IN (
        '1m','3m','5m','15m','30m',
        '1h','2h','4h','6h','12h',
        '1d','1w','1M'
    ));

-- 说明：当前生产环境已通过 004 连续聚合提供 candles_1M 视图，
--       此处物理表仅在回滚或离线导入场景需要，可按需跳过。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'market_data' AND table_name = 'candles_1M'
    ) THEN
        CREATE TABLE market_data."candles_1M" (
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
            taker_buy_volume       NUMERIC(38, 12),
            taker_buy_quote_volume NUMERIC(38, 12),
            is_closed           BOOLEAN     NOT NULL DEFAULT FALSE,
            source              TEXT        NOT NULL DEFAULT 'ccxt',
            ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (bucket_ts = date_trunc('month', bucket_ts)),
            PRIMARY KEY (exchange, symbol, bucket_ts)
        );

        PERFORM create_hypertable(
            'market_data.candles_1M',
            'bucket_ts',
            chunk_time_interval => INTERVAL '180 days',
            if_not_exists => TRUE
        );

        ALTER TABLE IF EXISTS market_data."candles_1M"
            SET (timescaledb.compress = TRUE,
                 timescaledb.compress_segmentby = 'exchange,symbol',
                 timescaledb.compress_orderby = 'bucket_ts');

        PERFORM add_compression_policy('market_data.candles_1M', INTERVAL '90 days')
            ON CONFLICT DO NOTHING;
        PERFORM add_retention_policy('market_data.candles_1M', INTERVAL '1825 days')
            ON CONFLICT DO NOTHING;
    END IF;
END$$;

-- upsert：1M -------------------------------------------------------------------
DROP FUNCTION IF EXISTS market_data."upsert_candle_1M"(TEXT, TEXT, TIMESTAMPTZ, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, BIGINT, BOOLEAN, TEXT);
CREATE OR REPLACE FUNCTION market_data."upsert_candle_1M"(
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
    p_source        TEXT    DEFAULT 'ccxt'
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO market_data."candles_1M" AS t (
        exchange, symbol, bucket_ts,
        open, high, low, close,
        volume, quote_volume, trade_count,
        is_closed, source, ingested_at, updated_at,
        taker_buy_volume, taker_buy_quote_volume
    ) VALUES (
        p_exchange, p_symbol, p_bucket_ts,
        p_open, p_high, p_low, p_close,
        p_volume, p_quote_volume, p_trade_count,
        p_is_closed, p_source, NOW(), NOW(),
        NULL, NULL
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
        is_closed   = t.is_closed OR EXCLUDED.is_closed,
        source      = EXCLUDED.source,
        updated_at  = NOW();
END;
$$;

DROP FUNCTION IF EXISTS market_data."upsert_candle_1M"(TEXT, TEXT, TIMESTAMPTZ, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, NUMERIC, BIGINT, BOOLEAN, TEXT, NUMERIC, NUMERIC);
CREATE OR REPLACE FUNCTION market_data."upsert_candle_1M"(
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
    INSERT INTO market_data."candles_1M" AS t (
        exchange, symbol, bucket_ts,
        open, high, low, close,
        volume, quote_volume, trade_count,
        is_closed, source, ingested_at, updated_at,
        taker_buy_volume, taker_buy_quote_volume
    ) VALUES (
        p_exchange, p_symbol, p_bucket_ts,
        p_open, p_high, p_low, p_close,
        p_volume, p_quote_volume, p_trade_count,
        p_is_closed, p_source, NOW(), NOW(),
        p_taker_buy_volume, p_taker_buy_quote_volume
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

-- 更多周期（3m/5m/15m/30m/2h/4h/6h/12h/1w 等）的 upsert DDL 已包含在 state/market_data_schema.sql 中。
-- 若需回滚至多物理表架构，可从备份中择需拷贝，或直接依赖 004 连续聚合输出派生周期。

-- bybit 历史清理示例 ---------------------------------------------------------
-- DO $$
-- DECLARE
--     target_exchange TEXT := 'bybit';
-- BEGIN
--     EXECUTE format('DELETE FROM market_data.candles_1m WHERE exchange = %L', target_exchange);
--     EXECUTE format('DELETE FROM market_data."candles_1M" WHERE exchange = %L', target_exchange);
--     EXECUTE format('DELETE FROM market_data.ingest_offsets WHERE exchange = %L', target_exchange);
-- END$$;
