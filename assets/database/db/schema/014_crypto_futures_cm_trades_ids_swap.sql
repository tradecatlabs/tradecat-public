-- 014_crypto_futures_cm_trades_ids_swap.sql
--
-- 目标：
-- - 修正运行库中 `crypto.raw_futures_cm_trades` 的“历史漂移结构”：
--   从旧结构（exchange/symbol + NUMERIC）迁移到新结构（venue_id/instrument_id + DOUBLE）。
-- - 与 `crypto.raw_futures_um_trades` 的事实表契约保持一致：
--   - 字段极简（不放 file_id/ingested_at/time_ts）
--   - 幂等键：PRIMARY KEY (venue_id, instrument_id, time, id)
--   - Timescale integer hypertable（time=epoch ms）+ compression
--
-- 注意：
-- - 本脚本默认采用 rename-swap（保留 *_old 便于回滚）。
-- - 若你确定旧表无价值，可在验收后手动 DROP *_old。

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS crypto;

-- integer hypertable 的 now()（用于压缩/保留等 policy job）
CREATE OR REPLACE FUNCTION crypto.unix_now_ms() RETURNS BIGINT
LANGUAGE SQL
STABLE
AS $$
  SELECT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT
$$;

-- 1) 旧表改名（若存在）
DO $$
BEGIN
    IF to_regclass('crypto.raw_futures_cm_trades') IS NULL THEN
        RETURN;
    END IF;

    IF to_regclass('crypto.raw_futures_cm_trades_old') IS NOT NULL THEN
        RAISE EXCEPTION 'crypto.raw_futures_cm_trades_old 已存在；请先手动处理/删除后再执行迁移';
    END IF;

    ALTER TABLE crypto.raw_futures_cm_trades RENAME TO raw_futures_cm_trades_old;
END$$;

-- 2) 新表（目标结构）
CREATE TABLE IF NOT EXISTS crypto.raw_futures_cm_trades (
    venue_id        BIGINT NOT NULL,
    instrument_id   BIGINT NOT NULL,
    id              BIGINT NOT NULL,
    price           DOUBLE PRECISION NOT NULL,
    qty             DOUBLE PRECISION NOT NULL,
    quote_qty       DOUBLE PRECISION NOT NULL,
    time            BIGINT NOT NULL, -- epoch(ms)
    is_buyer_maker  BOOLEAN NOT NULL,
    PRIMARY KEY (venue_id, instrument_id, time, id)
);

-- 3) Timescale hypertable + 压缩（仅保留主键索引，禁用默认 time_idx）
SELECT create_hypertable(
    'crypto.raw_futures_cm_trades',
    'time',
    chunk_time_interval => 86400000, -- 1 day (ms)
    create_default_indexes => FALSE,
    if_not_exists => TRUE
);
DROP INDEX IF EXISTS crypto.raw_futures_cm_trades_time_idx;
SELECT set_integer_now_func('crypto.raw_futures_cm_trades', 'crypto.unix_now_ms', replace_if_exists => TRUE);

ALTER TABLE crypto.raw_futures_cm_trades
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'venue_id,instrument_id',
         timescaledb.compress_orderby = 'time,id');

DO $$
BEGIN
    -- 30 days = 30 * 86400000(ms)
    PERFORM add_compression_policy('crypto.raw_futures_cm_trades', 2592000000);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

