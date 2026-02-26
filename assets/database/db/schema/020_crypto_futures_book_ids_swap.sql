-- 020_crypto_futures_book_ids_swap.sql
--
-- 目标：
-- - 把 futures/um 与 futures/cm 的 bookTicker/bookDepth 从旧结构（file_id/symbol + NUMERIC + timestamptz）
--   迁移到新结构（venue_id/instrument_id + DOUBLE + integer hypertable）。
-- - 与 ids 事实表契约一致：
--   - 事实表只存“官方字段 + 公共字段（维度键）”，不放 file_id/ingested_at/*_ts
--   - 短主键固定宽度：PRIMARY KEY (venue_id, instrument_id, time, seq/percentage)
--   - Timescale integer hypertable（epoch ms）+ compression policy
--
-- 注意：
-- - rename-swap：保留 *_old 便于回滚/取证；不主动删除数据。
-- - 为避免对“已是新结构”的库误操作，这里会用列存在性（file_id）判定是否需要迁移。

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS crypto;

-- integer hypertable 的 now()（用于压缩/保留等 policy job）
CREATE OR REPLACE FUNCTION crypto.unix_now_ms() RETURNS BIGINT
LANGUAGE SQL
STABLE
AS $$
  SELECT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT
$$;

-- ==================== futures/um bookTicker ====================

DO $$
BEGIN
    IF to_regclass('crypto.raw_futures_um_book_ticker') IS NULL THEN
        RETURN;
    END IF;

    -- 已是新结构（无 file_id）则跳过
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'crypto'
          AND table_name = 'raw_futures_um_book_ticker'
          AND column_name = 'file_id'
    ) THEN
        RETURN;
    END IF;

    IF to_regclass('crypto.raw_futures_um_book_ticker_old') IS NOT NULL THEN
        RAISE EXCEPTION 'crypto.raw_futures_um_book_ticker_old 已存在；请先手动处理/删除后再执行迁移';
    END IF;

    ALTER TABLE crypto.raw_futures_um_book_ticker RENAME TO raw_futures_um_book_ticker_old;
END$$;

CREATE TABLE IF NOT EXISTS crypto.raw_futures_um_book_ticker (
    venue_id         BIGINT NOT NULL,
    instrument_id    BIGINT NOT NULL,
    update_id        BIGINT NOT NULL,
    best_bid_price   DOUBLE PRECISION NOT NULL,
    best_bid_qty     DOUBLE PRECISION NOT NULL,
    best_ask_price   DOUBLE PRECISION NOT NULL,
    best_ask_qty     DOUBLE PRECISION NOT NULL,
    transaction_time BIGINT,
    event_time       BIGINT NOT NULL, -- epoch(ms)
    PRIMARY KEY (venue_id, instrument_id, event_time, update_id)
);

SELECT create_hypertable(
    'crypto.raw_futures_um_book_ticker',
    'event_time',
    chunk_time_interval => 86400000, -- 1 day (ms)
    create_default_indexes => FALSE,
    if_not_exists => TRUE
);
DROP INDEX IF EXISTS crypto.raw_futures_um_book_ticker_event_time_idx;
SELECT set_integer_now_func('crypto.raw_futures_um_book_ticker', 'crypto.unix_now_ms', replace_if_exists => TRUE);

ALTER TABLE crypto.raw_futures_um_book_ticker
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'venue_id,instrument_id',
         timescaledb.compress_orderby = 'event_time,update_id');

DO $$
BEGIN
    -- 3 days = 3 * 86400000(ms)
    PERFORM add_compression_policy('crypto.raw_futures_um_book_ticker', 259200000);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- ==================== futures/um bookDepth ====================

DO $$
BEGIN
    IF to_regclass('crypto.raw_futures_um_book_depth') IS NULL THEN
        RETURN;
    END IF;

    -- 已是新结构（无 file_id）则跳过
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'crypto'
          AND table_name = 'raw_futures_um_book_depth'
          AND column_name = 'file_id'
    ) THEN
        RETURN;
    END IF;

    IF to_regclass('crypto.raw_futures_um_book_depth_old') IS NOT NULL THEN
        RAISE EXCEPTION 'crypto.raw_futures_um_book_depth_old 已存在；请先手动处理/删除后再执行迁移';
    END IF;

    ALTER TABLE crypto.raw_futures_um_book_depth RENAME TO raw_futures_um_book_depth_old;
END$$;

CREATE TABLE IF NOT EXISTS crypto.raw_futures_um_book_depth (
    venue_id      BIGINT NOT NULL,
    instrument_id BIGINT NOT NULL,
    timestamp     BIGINT NOT NULL, -- epoch(ms)
    percentage    DOUBLE PRECISION NOT NULL,
    depth         DOUBLE PRECISION NOT NULL,
    notional      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (venue_id, instrument_id, timestamp, percentage)
);

SELECT create_hypertable(
    'crypto.raw_futures_um_book_depth',
    'timestamp',
    chunk_time_interval => 604800000, -- 7 days (ms)
    create_default_indexes => FALSE,
    if_not_exists => TRUE
);
DROP INDEX IF EXISTS crypto.raw_futures_um_book_depth_timestamp_idx;
SELECT set_integer_now_func('crypto.raw_futures_um_book_depth', 'crypto.unix_now_ms', replace_if_exists => TRUE);

ALTER TABLE crypto.raw_futures_um_book_depth
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'venue_id,instrument_id',
         timescaledb.compress_orderby = 'timestamp,percentage');

DO $$
BEGIN
    -- 30 days = 30 * 86400000(ms)
    PERFORM add_compression_policy('crypto.raw_futures_um_book_depth', 2592000000);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- ==================== futures/cm bookTicker（占位，与 UM 对称） ====================

DO $$
BEGIN
    IF to_regclass('crypto.raw_futures_cm_book_ticker') IS NULL THEN
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'crypto'
          AND table_name = 'raw_futures_cm_book_ticker'
          AND column_name = 'file_id'
    ) THEN
        RETURN;
    END IF;

    IF to_regclass('crypto.raw_futures_cm_book_ticker_old') IS NOT NULL THEN
        RAISE EXCEPTION 'crypto.raw_futures_cm_book_ticker_old 已存在；请先手动处理/删除后再执行迁移';
    END IF;

    ALTER TABLE crypto.raw_futures_cm_book_ticker RENAME TO raw_futures_cm_book_ticker_old;
END$$;

CREATE TABLE IF NOT EXISTS crypto.raw_futures_cm_book_ticker (LIKE crypto.raw_futures_um_book_ticker INCLUDING ALL);

SELECT create_hypertable(
    'crypto.raw_futures_cm_book_ticker',
    'event_time',
    chunk_time_interval => 86400000, -- 1 day (ms)
    create_default_indexes => FALSE,
    if_not_exists => TRUE
);
DROP INDEX IF EXISTS crypto.raw_futures_cm_book_ticker_event_time_idx;
SELECT set_integer_now_func('crypto.raw_futures_cm_book_ticker', 'crypto.unix_now_ms', replace_if_exists => TRUE);

ALTER TABLE crypto.raw_futures_cm_book_ticker
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'venue_id,instrument_id',
         timescaledb.compress_orderby = 'event_time,update_id');

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.raw_futures_cm_book_ticker', 259200000);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- ==================== futures/cm bookDepth（占位，与 UM 对称） ====================

DO $$
BEGIN
    IF to_regclass('crypto.raw_futures_cm_book_depth') IS NULL THEN
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'crypto'
          AND table_name = 'raw_futures_cm_book_depth'
          AND column_name = 'file_id'
    ) THEN
        RETURN;
    END IF;

    IF to_regclass('crypto.raw_futures_cm_book_depth_old') IS NOT NULL THEN
        RAISE EXCEPTION 'crypto.raw_futures_cm_book_depth_old 已存在；请先手动处理/删除后再执行迁移';
    END IF;

    ALTER TABLE crypto.raw_futures_cm_book_depth RENAME TO raw_futures_cm_book_depth_old;
END$$;

CREATE TABLE IF NOT EXISTS crypto.raw_futures_cm_book_depth (LIKE crypto.raw_futures_um_book_depth INCLUDING ALL);

SELECT create_hypertable(
    'crypto.raw_futures_cm_book_depth',
    'timestamp',
    chunk_time_interval => 604800000, -- 7 days (ms)
    create_default_indexes => FALSE,
    if_not_exists => TRUE
);
DROP INDEX IF EXISTS crypto.raw_futures_cm_book_depth_timestamp_idx;
SELECT set_integer_now_func('crypto.raw_futures_cm_book_depth', 'crypto.unix_now_ms', replace_if_exists => TRUE);

ALTER TABLE crypto.raw_futures_cm_book_depth
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'venue_id,instrument_id',
         timescaledb.compress_orderby = 'timestamp,percentage');

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.raw_futures_cm_book_depth', 2592000000);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

