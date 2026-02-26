-- 012_crypto_ingest_governance.sql
--
-- 目标：
-- - 在 schema `crypto` 内创建“旁路元数据”（不污染事实表）的治理表：
--   - ingest_runs：一次运行/任务的生命周期（realtime/backfill/repair）
--   - ingest_watermark：每个 symbol 的高水位（last_time/last_id）
--   - ingest_gaps：缺口队列（用于补拉/修复）
--
-- 约束：
-- - 不新建 schema（按你的要求：必须在 crypto 内部）
-- - 与事实表解耦：不要求 raw_futures_um_trades 增加任何过程字段

CREATE SCHEMA IF NOT EXISTS crypto;

-- ==================== crypto.ingest_runs ====================
CREATE TABLE IF NOT EXISTS crypto.ingest_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    exchange        TEXT NOT NULL,
    dataset         TEXT NOT NULL, -- e.g. futures.um.trades
    mode            TEXT NOT NULL CHECK (mode IN ('realtime','backfill','repair')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (status IN ('running','success','failed','partial')),
    error_message   TEXT,
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_crypto_ingest_runs_exchange_dataset_started_at
ON crypto.ingest_runs (exchange, dataset, started_at DESC);

-- ==================== crypto.ingest_watermark ====================
CREATE TABLE IF NOT EXISTS crypto.ingest_watermark (
    exchange        TEXT NOT NULL,
    dataset         TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    last_time       BIGINT NOT NULL, -- epoch ms
    last_id         BIGINT NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exchange, dataset, symbol)
);

CREATE INDEX IF NOT EXISTS idx_crypto_ingest_watermark_updated_at
ON crypto.ingest_watermark (updated_at DESC);

-- ==================== crypto.ingest_gaps ====================
CREATE TABLE IF NOT EXISTS crypto.ingest_gaps (
    gap_id          BIGSERIAL PRIMARY KEY,
    exchange        TEXT NOT NULL,
    dataset         TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    start_time      BIGINT NOT NULL, -- epoch ms
    end_time        BIGINT NOT NULL, -- epoch ms, end exclusive (约定)
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','repairing','closed','ignored')),
    reason          TEXT,
    run_id          BIGINT REFERENCES crypto.ingest_runs(run_id),
    UNIQUE (exchange, dataset, symbol, start_time, end_time)
);

CREATE INDEX IF NOT EXISTS idx_crypto_ingest_gaps_status_detected_at
ON crypto.ingest_gaps (status, detected_at DESC);

