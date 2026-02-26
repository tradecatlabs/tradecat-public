-- 015_crypto_spot_trades_fact_table.sql
--
-- 目标：
-- - 将 `crypto.raw_spot_trades` 从 legacy 结构（file_id + time_ts + NUMERIC）
--   重构为“极简事实表”（venue_id/instrument_id + DOUBLE + time=epoch(us)）。
-- - 与 futures trades（UM/CM）的事实表哲学保持一致：
--   - 行情事实表不放 file_id/ingested_at/time_ts
--   - 文件追溯放在 storage.*（files/import_batches/import_errors/file_revisions）
--
-- 注意：
-- - 本脚本采用 rename-swap，保留 `crypto.raw_spot_trades_old` 便于回滚。
-- - 当前运行库 spot 表为 0 行，但仍按“可复用迁移套路”执行。

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS crypto;

-- integer hypertable 的 now()（epoch us）
CREATE OR REPLACE FUNCTION crypto.unix_now_us() RETURNS BIGINT
LANGUAGE SQL
STABLE
AS $$
  SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::BIGINT
$$;

-- 1) 旧表改名（若存在）
DO $$
BEGIN
    IF to_regclass('crypto.raw_spot_trades') IS NULL THEN
        RETURN;
    END IF;

    IF to_regclass('crypto.raw_spot_trades_old') IS NOT NULL THEN
        RAISE EXCEPTION 'crypto.raw_spot_trades_old 已存在；请先手动处理/删除后再执行迁移';
    END IF;

    ALTER TABLE crypto.raw_spot_trades RENAME TO raw_spot_trades_old;
END$$;

-- 2) 新表（目标结构：严格对齐 Vision spot trades 字段语义）
-- Vision（样本事实）：
-- - 无 header
-- - 列序：id, price, qty, quote_qty, time(us), is_buyer_maker, is_best_match
CREATE TABLE IF NOT EXISTS crypto.raw_spot_trades (
    venue_id        BIGINT NOT NULL,
    instrument_id   BIGINT NOT NULL,
    id              BIGINT NOT NULL,
    price           DOUBLE PRECISION NOT NULL,
    qty             DOUBLE PRECISION NOT NULL,
    quote_qty       DOUBLE PRECISION NOT NULL,
    time            BIGINT NOT NULL, -- epoch(us)
    is_buyer_maker  BOOLEAN NOT NULL,
    is_best_match   BOOLEAN,
    PRIMARY KEY (venue_id, instrument_id, time, id)
);

-- 3) Timescale hypertable + 压缩（仅保留主键索引，禁用默认 time_idx）
-- - 86400000000us = 1 day
SELECT create_hypertable(
    'crypto.raw_spot_trades',
    'time',
    chunk_time_interval => 86400000000,
    create_default_indexes => FALSE,
    if_not_exists => TRUE
);
DROP INDEX IF EXISTS crypto.raw_spot_trades_time_idx;
SELECT set_integer_now_func('crypto.raw_spot_trades', 'crypto.unix_now_us', replace_if_exists => TRUE);

ALTER TABLE crypto.raw_spot_trades
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'venue_id,instrument_id',
         timescaledb.compress_orderby = 'time,id');

DO $$
BEGIN
    -- 30 days = 30 * 86400000000(us)
    PERFORM add_compression_policy('crypto.raw_spot_trades', 2592000000000);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

