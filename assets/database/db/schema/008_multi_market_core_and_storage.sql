-- 008_multi_market_core_and_storage.sql
--
-- 目标：
-- - 为“综合市场数据库（多市场）”提供跨市场共享的 core 维表根，以及对齐外部数据目录/文件的 storage 追溯根。
-- - 本脚本只创建：core/* 与 storage/*（不含具体市场事实表）。
--
-- 说明：
-- - 目前 TradeCat 现有表主要位于 schema `market_data`（K线/指标聚合）。本脚本新增的是并行的根结构，不破坏旧结构。
-- - 该脚本可在同一个 PostgreSQL 数据库中执行（推荐：database = `market_data`，schema 多根共存）。
-- - 若未安装 TimescaleDB，也可执行（本脚本不依赖 hypertable）。

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS storage;

-- ==================== core：跨市场共享维表 ====================

-- 数据源/交易场所/数据商
CREATE TABLE IF NOT EXISTS core.venue (
    venue_id        BIGSERIAL PRIMARY KEY,
    venue_code      TEXT NOT NULL UNIQUE,          -- 机器用：binance/nyse/sse/...
    venue_name      TEXT NOT NULL,                 -- 人看：Binance/NYSE/上交所/...
    venue_type      TEXT NOT NULL DEFAULT 'exchange',
    country_code    TEXT,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 货币（法币/稳定币/加密）
CREATE TABLE IF NOT EXISTS core.currency (
    currency_code   TEXT PRIMARY KEY,              -- USD/CNY/USDT/BTC...
    currency_name   TEXT,
    decimals        INTEGER,
    currency_type   TEXT NOT NULL DEFAULT 'fiat',   -- fiat/crypto/stable/unknown
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 统一金融工具（全局 instrument_id）
-- 注意：这是“锚点表”，不同市场的事实表最终都应该能映射到 instrument_id（通过 symbol_map）。
CREATE TABLE IF NOT EXISTS core.instrument (
    instrument_id       BIGSERIAL PRIMARY KEY,
    asset_class         TEXT NOT NULL,             -- crypto/equities/fx/commodities/rates/funds/index
    instrument_type     TEXT NOT NULL,             -- spot/future/perp/option/equity/bond/...
    base_currency       TEXT,                      -- 例如 BTC / AAPL / USD（按资产类型而定）
    quote_currency      TEXT,                      -- 例如 USDT / USD / CNY（按资产类型而定）
    underlying_id       BIGINT REFERENCES core.instrument(instrument_id),
    meta               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 交易所/数据源 symbol → instrument_id 映射（解决同一资产在不同 venue 下的代码差异）
CREATE TABLE IF NOT EXISTS core.symbol_map (
    venue_id        BIGINT NOT NULL REFERENCES core.venue(venue_id),
    symbol          TEXT NOT NULL,
    instrument_id   BIGINT NOT NULL REFERENCES core.instrument(instrument_id),
    effective_from  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_to    TIMESTAMPTZ,
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (venue_id, symbol, effective_from)
);

CREATE INDEX IF NOT EXISTS idx_symbol_map_instrument_id ON core.symbol_map (instrument_id);

-- 交易日历/交易时段（占位：后续按市场补充具体 session 规则）
CREATE TABLE IF NOT EXISTS core.calendar_session (
    calendar_code   TEXT NOT NULL,                 -- e.g. US_STOCK/CHINA_STOCK/CRYPTO_24X7
    session_date    DATE NOT NULL,
    open_ts         TIMESTAMPTZ,
    close_ts        TIMESTAMPTZ,
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (calendar_code, session_date)
);

-- ==================== storage：文件追溯/导入水位 ====================

-- 1 行 = 1 个来源文件（zip 或 csv），用于把“官方目录结构”固化为结构化字段，支撑审计/可复现/幂等导入。
CREATE TABLE IF NOT EXISTS storage.files (
    file_id             BIGSERIAL PRIMARY KEY,
    rel_path            TEXT NOT NULL UNIQUE,      -- 相对路径（对齐官方目录结构/文件名）
    content_kind        TEXT NOT NULL DEFAULT 'csv' CHECK (content_kind IN ('zip','csv','parquet','unknown')),
    parent_file_id      BIGINT REFERENCES storage.files(file_id), -- 例如：csv 的 parent=zip

    source              TEXT NOT NULL,             -- binance_vision / polygon / akshare / ...
    market_root         TEXT NOT NULL,             -- crypto/equities/fx/commodities/rates/funds/index

    -- 目录层级拆解（尽量通用；字段缺失则为 NULL）
    market              TEXT,                      -- spot/futures/option/...
    product             TEXT,                      -- um/cm（或其他产品分级）
    frequency           TEXT,                      -- daily/monthly/...
    dataset             TEXT,                      -- trades/klines/bookTicker/...
    symbol              TEXT,
    interval            TEXT,
    file_date           DATE,                      -- daily 文件日期
    file_month          DATE,                      -- monthly 文件月份（建议用每月 1 号表示）

    -- 文件属性
    size_bytes          BIGINT,
    checksum_sha256     TEXT,
    downloaded_at       TIMESTAMPTZ,
    extracted_at        TIMESTAMPTZ,
    parser_version      TEXT NOT NULL DEFAULT 'v1',

    -- 快速质量统计（可选）
    row_count           BIGINT,
    min_event_ts        TIMESTAMPTZ,
    max_event_ts        TIMESTAMPTZ,

    meta                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_files_source ON storage.files (source);
CREATE INDEX IF NOT EXISTS idx_files_market_root ON storage.files (market_root);
CREATE INDEX IF NOT EXISTS idx_files_dataset ON storage.files (dataset);
CREATE INDEX IF NOT EXISTS idx_files_symbol ON storage.files (symbol);
CREATE INDEX IF NOT EXISTS idx_files_file_date ON storage.files (file_date);

-- 同一路径被替换（checksum 变化）时的版本链
CREATE TABLE IF NOT EXISTS storage.file_revisions (
    revision_id         BIGSERIAL PRIMARY KEY,
    rel_path            TEXT NOT NULL,
    old_checksum_sha256 TEXT,
    new_checksum_sha256 TEXT NOT NULL,
    detected_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note                TEXT
);

CREATE INDEX IF NOT EXISTS idx_file_revisions_rel_path ON storage.file_revisions (rel_path);

-- 导入批次（用于幂等重跑、审计与可观测）
CREATE TABLE IF NOT EXISTS storage.import_batches (
    batch_id            BIGSERIAL PRIMARY KEY,
    source              TEXT NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','failed','partial')),
    note                TEXT,
    meta                JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- 单文件导入错误（便于定位某个 CSV/zip 的问题）
CREATE TABLE IF NOT EXISTS storage.import_errors (
    error_id            BIGSERIAL PRIMARY KEY,
    batch_id            BIGINT REFERENCES storage.import_batches(batch_id),
    file_id             BIGINT REFERENCES storage.files(file_id),
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error_type          TEXT NOT NULL,
    message             TEXT NOT NULL,
    detail              TEXT,
    meta                JSONB NOT NULL DEFAULT '{}'::jsonb
);

