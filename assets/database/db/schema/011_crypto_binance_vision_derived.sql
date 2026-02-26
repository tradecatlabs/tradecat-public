-- 011_crypto_binance_vision_derived.sql
--
-- 目标：
-- - 创建 crypto 市场下“可派生/汇总（Derived）”的数据集表，用于：
--   1) 直接落库 Binance Vision 官方提供的 aggTrades / klines / markPriceKlines / indexPriceKlines / premiumIndexKlines；
--   2) 或作为你基于原子数据（trades 等）重建后的一层缓存（可选）。
--
-- 重要说明：
-- - 你的强约束是“物理层只收集基元数据”。因此：
--   - 原子/物理层表 → `libs/database/db/schema/009_crypto_binance_vision_landing.sql`
--   - 派生/汇总层表 → 本脚本（可选执行）
-- - `option_eoh_summary` 虽然语义上属于汇总，但你明确要求强制归类到物理层，所以不在此脚本内。
--
-- 命名约定：
-- - 仍严格对齐 Binance Vision 目录结构的 dataset 命名（不引入 `_daily`）。
-- - 派生层**仍在 crypto 根内**（按你的要求），不新建 `crypto_derived` schema。
--   物理层 vs 派生层通过“执行脚本/表清单/文档”区分：
--   - 物理层（基元）由 `009_..._landing.sql` 创建
--   - 派生层（可派生/汇总）由本脚本创建
--
-- 依赖：
-- - 需要先执行 `008_multi_market_core_and_storage.sql`（提供 storage.files）
-- - 建议已安装 timescaledb（本脚本会 CREATE EXTENSION IF NOT EXISTS）

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS crypto;

-- ==================== crypto.spot（派生） ====================

-- spot/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-YYYY-MM-DD.csv
-- 样本列序（无 header）：
--   agg_trade_id, price, quantity, first_trade_id, last_trade_id, transact_time(us), is_buyer_maker, is_best_match
CREATE TABLE IF NOT EXISTS crypto.agg_spot_agg_trades (
    file_id             BIGINT NOT NULL REFERENCES storage.files(file_id),
    symbol              TEXT   NOT NULL,
    agg_trade_id        BIGINT NOT NULL,
    price               NUMERIC(38, 12) NOT NULL,
    quantity            NUMERIC(38, 12) NOT NULL,
    first_trade_id      BIGINT,
    last_trade_id       BIGINT,
    transact_time       BIGINT NOT NULL,          -- epoch(us)
    transact_time_ts    TIMESTAMPTZ NOT NULL,     -- 建议导入时计算：to_timestamp(transact_time / 1000000.0)
    is_buyer_maker      BOOLEAN NOT NULL,
    is_best_match       BOOLEAN,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, transact_time_ts, agg_trade_id)
);

SELECT create_hypertable(
    'crypto.agg_spot_agg_trades',
    'transact_time_ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

ALTER TABLE crypto.agg_spot_agg_trades
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'transact_time_ts,agg_trade_id'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_spot_agg_trades', INTERVAL '7 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- spot/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv
-- 样本列序（无 header），与 futures klines 字段一致，但时间戳为 epoch(us)
CREATE TABLE IF NOT EXISTS crypto.agg_spot_klines_1m (
    file_id             BIGINT NOT NULL REFERENCES storage.files(file_id),
    symbol              TEXT   NOT NULL,
    open_time           BIGINT NOT NULL,          -- epoch(us)
    open_time_ts        TIMESTAMPTZ NOT NULL,     -- 建议导入时计算：to_timestamp(open_time / 1000000.0)
    open                NUMERIC(38, 12) NOT NULL,
    high                NUMERIC(38, 12) NOT NULL,
    low                 NUMERIC(38, 12) NOT NULL,
    close               NUMERIC(38, 12) NOT NULL,
    volume              NUMERIC(38, 12) NOT NULL,
    close_time          BIGINT NOT NULL,          -- epoch(us)
    close_time_ts       TIMESTAMPTZ NOT NULL,     -- 建议导入时计算：to_timestamp(close_time / 1000000.0)
    quote_volume        NUMERIC(38, 12),
    count               BIGINT,
    taker_buy_volume        NUMERIC(38, 12),
    taker_buy_quote_volume  NUMERIC(38, 12),
    ignore              TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, open_time_ts)
);

SELECT create_hypertable(
    'crypto.agg_spot_klines_1m',
    'open_time_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

ALTER TABLE crypto.agg_spot_klines_1m
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'open_time_ts'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_spot_klines_1m', INTERVAL '30 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- ==================== crypto.futures_um（派生） ====================

-- futures/um/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-YYYY-MM-DD.csv
-- header：agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time(ms),is_buyer_maker
CREATE TABLE IF NOT EXISTS crypto.agg_futures_um_agg_trades (
    file_id             BIGINT NOT NULL REFERENCES storage.files(file_id),
    symbol              TEXT   NOT NULL,
    agg_trade_id        BIGINT NOT NULL,
    price               NUMERIC(38, 12) NOT NULL,
    quantity            NUMERIC(38, 12) NOT NULL,
    first_trade_id      BIGINT,
    last_trade_id       BIGINT,
    transact_time       BIGINT NOT NULL,          -- epoch(ms)
    transact_time_ts    TIMESTAMPTZ NOT NULL,     -- 建议导入时计算：to_timestamp(transact_time / 1000.0)
    is_buyer_maker      BOOLEAN NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, transact_time_ts, agg_trade_id)
);

SELECT create_hypertable(
    'crypto.agg_futures_um_agg_trades',
    'transact_time_ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

ALTER TABLE crypto.agg_futures_um_agg_trades
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'transact_time_ts,agg_trade_id'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_um_agg_trades', INTERVAL '7 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- futures/um/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv
CREATE TABLE IF NOT EXISTS crypto.agg_futures_um_klines_1m (
    file_id             BIGINT NOT NULL REFERENCES storage.files(file_id),
    symbol              TEXT   NOT NULL,
    open_time           BIGINT NOT NULL,          -- epoch(ms)
    open_time_ts        TIMESTAMPTZ NOT NULL,     -- 建议导入时计算：to_timestamp(open_time / 1000.0)
    open                NUMERIC(38, 12) NOT NULL,
    high                NUMERIC(38, 12) NOT NULL,
    low                 NUMERIC(38, 12) NOT NULL,
    close               NUMERIC(38, 12) NOT NULL,
    volume              NUMERIC(38, 12) NOT NULL,
    close_time          BIGINT NOT NULL,          -- epoch(ms)
    close_time_ts       TIMESTAMPTZ NOT NULL,     -- 建议导入时计算：to_timestamp(close_time / 1000.0)
    quote_volume        NUMERIC(38, 12),
    count               BIGINT,
    taker_buy_volume        NUMERIC(38, 12),
    taker_buy_quote_volume  NUMERIC(38, 12),
    ignore              TEXT,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, open_time_ts)
);

SELECT create_hypertable(
    'crypto.agg_futures_um_klines_1m',
    'open_time_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

ALTER TABLE crypto.agg_futures_um_klines_1m
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'open_time_ts'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_um_klines_1m', INTERVAL '30 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- futures/um/daily/markPriceKlines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv
CREATE TABLE IF NOT EXISTS crypto.agg_futures_um_mark_price_klines_1m (
    LIKE crypto.agg_futures_um_klines_1m INCLUDING ALL
);
SELECT create_hypertable(
    'crypto.agg_futures_um_mark_price_klines_1m',
    'open_time_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

DO $$
BEGIN
    ALTER TABLE crypto.agg_futures_um_mark_price_klines_1m
        ADD CONSTRAINT agg_futures_um_mark_price_klines_1m_file_id_fkey FOREIGN KEY (file_id) REFERENCES storage.files(file_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

ALTER TABLE crypto.agg_futures_um_mark_price_klines_1m
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'open_time_ts'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_um_mark_price_klines_1m', INTERVAL '30 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- futures/um/daily/indexPriceKlines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv
CREATE TABLE IF NOT EXISTS crypto.agg_futures_um_index_price_klines_1m (
    LIKE crypto.agg_futures_um_klines_1m INCLUDING ALL
);
SELECT create_hypertable(
    'crypto.agg_futures_um_index_price_klines_1m',
    'open_time_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

DO $$
BEGIN
    ALTER TABLE crypto.agg_futures_um_index_price_klines_1m
        ADD CONSTRAINT agg_futures_um_index_price_klines_1m_file_id_fkey FOREIGN KEY (file_id) REFERENCES storage.files(file_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

ALTER TABLE crypto.agg_futures_um_index_price_klines_1m
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'open_time_ts'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_um_index_price_klines_1m', INTERVAL '30 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- futures/um/daily/premiumIndexKlines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv
CREATE TABLE IF NOT EXISTS crypto.agg_futures_um_premium_index_klines_1m (
    LIKE crypto.agg_futures_um_klines_1m INCLUDING ALL
);
SELECT create_hypertable(
    'crypto.agg_futures_um_premium_index_klines_1m',
    'open_time_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

DO $$
BEGIN
    ALTER TABLE crypto.agg_futures_um_premium_index_klines_1m
        ADD CONSTRAINT agg_futures_um_premium_index_klines_1m_file_id_fkey FOREIGN KEY (file_id) REFERENCES storage.files(file_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

ALTER TABLE crypto.agg_futures_um_premium_index_klines_1m
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'open_time_ts'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_um_premium_index_klines_1m', INTERVAL '30 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- ==================== crypto.futures_cm（派生，占位：结构与 UM 对称） ====================
-- 注意：当前样本未包含 futures/cm 数据，但 Binance Vision 目录结构存在。
-- 派生类数据集（aggTrades/klines/*Klines）统一放在派生层占位。

CREATE TABLE IF NOT EXISTS crypto.agg_futures_cm_agg_trades (
    LIKE crypto.agg_futures_um_agg_trades INCLUDING ALL
);
SELECT create_hypertable(
    'crypto.agg_futures_cm_agg_trades',
    'transact_time_ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

DO $$
BEGIN
    ALTER TABLE crypto.agg_futures_cm_agg_trades
        ADD CONSTRAINT agg_futures_cm_agg_trades_file_id_fkey FOREIGN KEY (file_id) REFERENCES storage.files(file_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

ALTER TABLE crypto.agg_futures_cm_agg_trades
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'transact_time_ts,agg_trade_id'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_cm_agg_trades', INTERVAL '7 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

CREATE TABLE IF NOT EXISTS crypto.agg_futures_cm_klines_1m (
    LIKE crypto.agg_futures_um_klines_1m INCLUDING ALL
);
SELECT create_hypertable(
    'crypto.agg_futures_cm_klines_1m',
    'open_time_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

DO $$
BEGIN
    ALTER TABLE crypto.agg_futures_cm_klines_1m
        ADD CONSTRAINT agg_futures_cm_klines_1m_file_id_fkey FOREIGN KEY (file_id) REFERENCES storage.files(file_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

ALTER TABLE crypto.agg_futures_cm_klines_1m
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'open_time_ts'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_cm_klines_1m', INTERVAL '30 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

CREATE TABLE IF NOT EXISTS crypto.agg_futures_cm_mark_price_klines_1m (
    LIKE crypto.agg_futures_um_klines_1m INCLUDING ALL
);
SELECT create_hypertable(
    'crypto.agg_futures_cm_mark_price_klines_1m',
    'open_time_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

DO $$
BEGIN
    ALTER TABLE crypto.agg_futures_cm_mark_price_klines_1m
        ADD CONSTRAINT agg_futures_cm_mark_price_klines_1m_file_id_fkey FOREIGN KEY (file_id) REFERENCES storage.files(file_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

ALTER TABLE crypto.agg_futures_cm_mark_price_klines_1m
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'open_time_ts'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_cm_mark_price_klines_1m', INTERVAL '30 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

CREATE TABLE IF NOT EXISTS crypto.agg_futures_cm_index_price_klines_1m (
    LIKE crypto.agg_futures_um_klines_1m INCLUDING ALL
);
SELECT create_hypertable(
    'crypto.agg_futures_cm_index_price_klines_1m',
    'open_time_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

DO $$
BEGIN
    ALTER TABLE crypto.agg_futures_cm_index_price_klines_1m
        ADD CONSTRAINT agg_futures_cm_index_price_klines_1m_file_id_fkey FOREIGN KEY (file_id) REFERENCES storage.files(file_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

ALTER TABLE crypto.agg_futures_cm_index_price_klines_1m
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'open_time_ts'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_cm_index_price_klines_1m', INTERVAL '30 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

CREATE TABLE IF NOT EXISTS crypto.agg_futures_cm_premium_index_klines_1m (
    LIKE crypto.agg_futures_um_klines_1m INCLUDING ALL
);
SELECT create_hypertable(
    'crypto.agg_futures_cm_premium_index_klines_1m',
    'open_time_ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

DO $$
BEGIN
    ALTER TABLE crypto.agg_futures_cm_premium_index_klines_1m
        ADD CONSTRAINT agg_futures_cm_premium_index_klines_1m_file_id_fkey FOREIGN KEY (file_id) REFERENCES storage.files(file_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

ALTER TABLE crypto.agg_futures_cm_premium_index_klines_1m
    SET (
        timescaledb.compress = TRUE,
        timescaledb.compress_segmentby = 'symbol',
        timescaledb.compress_orderby = 'open_time_ts'
    );

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.agg_futures_cm_premium_index_klines_1m', INTERVAL '30 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;
