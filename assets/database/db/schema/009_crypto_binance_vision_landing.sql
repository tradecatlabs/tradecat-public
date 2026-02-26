-- 009_crypto_binance_vision_landing.sql
--
-- 目标：
-- - 在 schema `crypto` 下创建“严格对齐 Binance Vision CSV”的落库表（Landing Zone）。
-- - 该层追求：可追溯（file_id）、幂等（唯一键/主键）、可增量（按时间分区/压缩策略）。
-- - 本脚本只包含「基元/物理层（Atomic Physical）」数据集；可派生/汇总数据集统一放到派生层脚本：
--   `libs/database/db/schema/011_crypto_binance_vision_derived.sql`
--
-- 重要约束（来自当前样本事实）：
-- - spot CSV：无 header，时间戳为 epoch(us)
-- - futures UM CSV：有 header，时间戳多为 epoch(ms) 或 datetime 字符串
-- - option：BVOLIndex 为 epoch(ms)，EOHSummary 为 date+hour
--
-- 命名约定：
-- - 不把 daily/monthly 写进表名；frequency 由 storage.files.frequency 表达（通过 file_id 回溯）。
-- - 以“市场根 crypto + 子分支”组织（spot / futures_um / futures_cm / option）。

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE SCHEMA IF NOT EXISTS crypto;

-- ==================== crypto.spot（raw） ====================

-- spot/daily/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM-DD.csv
-- 样本列序（无 header）：
--   id, price, qty, quote_qty, time(us), is_buyer_maker, is_best_match
--
-- 说明（重要）：
-- - 该表是“逐笔事实表”，实时（WS）与历史回填（Vision ZIP）会写入同一张表。
-- - 为了控制索引/体积成本，主键使用整型维度键（venue_id/instrument_id），不使用 TEXT(symbol) 做主键。
-- - 每行的文件追溯在 storage.*（files/import_batches/import_errors）侧完成，本表不放 file_id。
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

-- integer hypertable 的 now()（用于压缩/保留等 policy job）
CREATE OR REPLACE FUNCTION crypto.unix_now_us() RETURNS BIGINT
LANGUAGE SQL
STABLE
AS $$
  SELECT (EXTRACT(EPOCH FROM NOW()) * 1000000)::BIGINT
$$;

-- 使用整数时间列（epoch us）作为 hypertable 时间轴：
-- - chunk_time_interval 单位与 time 列一致（us）
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

-- NOTE：
-- - spot/aggTrades 与 spot/klines 属于“官方已提供但可派生/汇总”的数据集：
--   - aggTrades 可由 trades 聚合重建
--   - klines 可由 trades 聚合重建
-- - 为了让“物理层=基元数据”保持纯粹，这两类表移动到派生层：
--   `libs/database/db/schema/011_crypto_binance_vision_derived.sql`

-- ==================== crypto.futures_um（raw） ====================

-- futures/um/daily/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM-DD.csv
-- header：id,price,qty,quote_qty,time(ms),is_buyer_maker
--
-- 说明（重要）：
-- - 该表是“逐笔事实表”，实时（WS）与历史回填（Vision ZIP）会写入同一张表。
-- - 为了控制索引/体积成本，主键使用整型维度键（venue_id/instrument_id），不使用 TEXT 主键。
-- - 每行的文件追溯在 storage.*（files/import_batches/import_errors）侧完成，本表不放 file_id。
CREATE TABLE IF NOT EXISTS crypto.raw_futures_um_trades (
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

-- integer hypertable 的 now()（用于压缩/保留等 policy job）
CREATE OR REPLACE FUNCTION crypto.unix_now_ms() RETURNS BIGINT
LANGUAGE SQL
STABLE
AS $$
  SELECT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT
$$;

-- 使用整数时间列（epoch ms）作为 hypertable 时间轴：
-- - chunk_time_interval 单位与 time 列一致（ms）
-- - 86400000ms = 1 day
SELECT create_hypertable(
    'crypto.raw_futures_um_trades',
    'time',
    chunk_time_interval => 86400000,
    create_default_indexes => FALSE,
    if_not_exists => TRUE
);
-- TimescaleDB 默认会创建 `time DESC` 索引（*_time_idx）。该表主键已覆盖核心查询路径，为降低写入放大/索引体积，这里禁用默认索引并兜底删除。
DROP INDEX IF EXISTS crypto.raw_futures_um_trades_time_idx;
SELECT set_integer_now_func('crypto.raw_futures_um_trades', 'crypto.unix_now_ms', replace_if_exists => TRUE);

ALTER TABLE crypto.raw_futures_um_trades
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'venue_id,instrument_id',
         timescaledb.compress_orderby = 'time,id');

DO $$
BEGIN
    -- 30 days = 30 * 86400000(ms)
    PERFORM add_compression_policy('crypto.raw_futures_um_trades', 2592000000);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- NOTE：
-- - futures/um/aggTrades 与 futures/um/*Klines 属于“官方已提供但可派生/汇总”的数据集：
--   - aggTrades 可由 trades 聚合重建（trade id 区间聚合）
--   - klines 可由 trades 聚合重建（OHLCV/count/taker_buy_*）
--   - mark/index/premium klines 本质也是按时间对齐的衍生序列
-- - 为了保持“物理层=基元数据”，这类表移动到派生层：
--   `libs/database/db/schema/011_crypto_binance_vision_derived.sql`

-- futures/um/daily/bookTicker/{SYMBOL}/{SYMBOL}-bookTicker-YYYY-MM-DD.csv
-- header：update_id,best_bid_price,best_bid_qty,best_ask_price,best_ask_qty,transaction_time(ms),event_time(ms)
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

-- 86400000ms = 1 day
SELECT create_hypertable(
    'crypto.raw_futures_um_book_ticker',
    'event_time',
    chunk_time_interval => 86400000,
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

-- futures/um/daily/bookDepth/{SYMBOL}/{SYMBOL}-bookDepth-YYYY-MM-DD.csv
-- header：timestamp(datetime),percentage,depth,notional
CREATE TABLE IF NOT EXISTS crypto.raw_futures_um_book_depth (
    venue_id      BIGINT NOT NULL,
    instrument_id BIGINT NOT NULL,
    timestamp     BIGINT NOT NULL, -- epoch(ms)，导入时按 UTC 解析官方 datetime 再转 ms
    percentage    DOUBLE PRECISION NOT NULL,
    depth         DOUBLE PRECISION NOT NULL,
    notional      DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (venue_id, instrument_id, timestamp, percentage)
);

-- 604800000ms = 7 days
SELECT create_hypertable(
    'crypto.raw_futures_um_book_depth',
    'timestamp',
    chunk_time_interval => 604800000,
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

-- futures/um/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-YYYY-MM-DD.csv
-- header：create_time(datetime),symbol,sum_open_interest,sum_open_interest_value,count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,count_long_short_ratio,sum_taker_long_short_vol_ratio
CREATE TABLE IF NOT EXISTS crypto.raw_futures_um_metrics (
    file_id         BIGINT NOT NULL REFERENCES storage.files(file_id),
    create_time     TIMESTAMPTZ NOT NULL, -- 约定：按 UTC 解析
    symbol          TEXT NOT NULL,
    sum_open_interest               NUMERIC(38, 12) NOT NULL,
    sum_open_interest_value         NUMERIC(38, 12) NOT NULL,
    count_toptrader_long_short_ratio NUMERIC(38, 12),
    sum_toptrader_long_short_ratio   NUMERIC(38, 12),
    count_long_short_ratio           NUMERIC(38, 12),
    sum_taker_long_short_vol_ratio   NUMERIC(38, 12),
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, create_time)
);

SELECT create_hypertable('crypto.raw_futures_um_metrics', 'create_time', chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE crypto.raw_futures_um_metrics
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'symbol',
         timescaledb.compress_orderby = 'create_time');

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.raw_futures_um_metrics', INTERVAL '90 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- ==================== crypto.futures_cm（raw，占位：结构与 UM 对称） ====================
-- 注意：当前样本未包含 futures/cm 数据，但 Binance Vision 目录结构存在，字段通常与 UM 相同或高度相似。
-- 先建“占位表”，未来接入 cm 数据时可直接落库。

CREATE TABLE IF NOT EXISTS crypto.raw_futures_cm_trades (LIKE crypto.raw_futures_um_trades INCLUDING ALL);
CREATE TABLE IF NOT EXISTS crypto.raw_futures_cm_book_ticker (LIKE crypto.raw_futures_um_book_ticker INCLUDING ALL);
CREATE TABLE IF NOT EXISTS crypto.raw_futures_cm_book_depth (LIKE crypto.raw_futures_um_book_depth INCLUDING ALL);
CREATE TABLE IF NOT EXISTS crypto.raw_futures_cm_metrics (LIKE crypto.raw_futures_um_metrics INCLUDING ALL);

DO $$
BEGIN
    -- trades 表不包含 file_id（实时+回填统一事实表），因此无需 file_id 外键。
    PERFORM 1;
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

DO $$
BEGIN
    ALTER TABLE crypto.raw_futures_cm_metrics
        ADD CONSTRAINT raw_futures_cm_metrics_file_id_fkey FOREIGN KEY (file_id) REFERENCES storage.files(file_id);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- CM 表也按与 UM 相同的策略创建 hypertable + 压缩（当前无数据，先占位不影响）
SELECT create_hypertable(
    'crypto.raw_futures_cm_trades',
    'time',
    chunk_time_interval => 86400000,
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
    PERFORM add_compression_policy('crypto.raw_futures_cm_trades', 2592000000);
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

SELECT create_hypertable(
    'crypto.raw_futures_cm_book_ticker',
    'event_time',
    chunk_time_interval => 86400000,
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

SELECT create_hypertable(
    'crypto.raw_futures_cm_book_depth',
    'timestamp',
    chunk_time_interval => 604800000,
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

SELECT create_hypertable('crypto.raw_futures_cm_metrics', 'create_time', chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);
ALTER TABLE crypto.raw_futures_cm_metrics
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'symbol',
         timescaledb.compress_orderby = 'create_time');
DO $$
BEGIN
    PERFORM add_compression_policy('crypto.raw_futures_cm_metrics', INTERVAL '90 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- ==================== crypto.option ====================

-- option/daily/BVOLIndex/{SYMBOL}/{SYMBOL}-BVOLIndex-YYYY-MM-DD.csv
-- header：calc_time(ms),symbol,base_asset,quote_asset,index_value
CREATE TABLE IF NOT EXISTS crypto.raw_option_bvol_index (
    file_id         BIGINT NOT NULL REFERENCES storage.files(file_id),
    calc_time       BIGINT NOT NULL, -- epoch(ms)
    calc_time_ts    TIMESTAMPTZ NOT NULL, -- 建议导入时计算：to_timestamp(calc_time / 1000.0)
    symbol          TEXT NOT NULL,
    base_asset      TEXT,
    quote_asset     TEXT,
    index_value     NUMERIC(38, 12) NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, calc_time_ts)
);

SELECT create_hypertable('crypto.raw_option_bvol_index', 'calc_time_ts', chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE crypto.raw_option_bvol_index
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'symbol',
         timescaledb.compress_orderby = 'calc_time_ts');

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.raw_option_bvol_index', INTERVAL '180 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;

-- option/daily/EOHSummary/{UNDERLYING}/{UNDERLYING}-EOHSummary-YYYY-MM-DD.csv
-- header：date,hour,symbol,underlying,type,strike,open,high,low,close,volume_contracts,volume_usdt,best_bid_price,best_ask_price,best_bid_qty,best_ask_qty,best_buy_iv,best_sell_iv,mark_price,mark_iv,delta,gamma,vega,theta,openinterest_contracts,openinterest_usdt
-- 注意：部分字段可能为空字符串（例如 best_buy_iv/mark_price），导入时需转 NULL。
CREATE TABLE IF NOT EXISTS crypto.raw_option_eoh_summary (
    file_id         BIGINT NOT NULL REFERENCES storage.files(file_id),
    date            DATE NOT NULL,
    hour            SMALLINT NOT NULL CHECK (hour >= 0 AND hour <= 23),
    hour_ts         TIMESTAMPTZ NOT NULL, -- 建议导入时由 date+hour 计算（按 UTC）：(date::timestamp + hour * interval '1 hour') AT TIME ZONE 'UTC'

    symbol          TEXT NOT NULL,      -- 期权合约代码，例如 BTC-231027-33000-C
    underlying      TEXT NOT NULL,      -- 标的，例如 BTCUSDT
    type            TEXT NOT NULL,      -- C/P
    strike          TEXT NOT NULL,      -- 兼容官方字段：231027-33000（保持原样）

    open            NUMERIC(38, 12),
    high            NUMERIC(38, 12),
    low             NUMERIC(38, 12),
    close           NUMERIC(38, 12),

    volume_contracts    NUMERIC(38, 12),
    volume_usdt         NUMERIC(38, 12),

    best_bid_price   NUMERIC(38, 12),
    best_ask_price   NUMERIC(38, 12),
    best_bid_qty     NUMERIC(38, 12),
    best_ask_qty     NUMERIC(38, 12),
    best_buy_iv      NUMERIC(38, 12),
    best_sell_iv     NUMERIC(38, 12),

    mark_price       NUMERIC(38, 12),
    mark_iv          NUMERIC(38, 12),

    delta            NUMERIC(38, 12),
    gamma            NUMERIC(38, 12),
    vega             NUMERIC(38, 12),
    theta            NUMERIC(38, 12),

    openinterest_contracts NUMERIC(38, 12),
    openinterest_usdt      NUMERIC(38, 12),

    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, hour_ts)
);

-- EOHSummary 粒度较低，hypertable 可选；这里仍创建以便统一按时间裁剪与压缩
SELECT create_hypertable('crypto.raw_option_eoh_summary', 'hour_ts', chunk_time_interval => INTERVAL '30 days', if_not_exists => TRUE);

ALTER TABLE crypto.raw_option_eoh_summary
    SET (timescaledb.compress = TRUE,
         timescaledb.compress_segmentby = 'underlying',
         timescaledb.compress_orderby = 'hour_ts,symbol');

DO $$
BEGIN
    PERFORM add_compression_policy('crypto.raw_option_eoh_summary', INTERVAL '365 days');
EXCEPTION WHEN duplicate_object THEN NULL;
END$$;
