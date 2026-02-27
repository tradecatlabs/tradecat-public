-- 019_crypto_raw_trades_sanity_checks.sql
--
-- 目标：
-- - 为 raw trades 事实表补齐“最小 sanity CHECK”，避免脏数据静默落库；
-- - 使用 NOT VALID：不强制全表扫描（避免迁移/上线时卡住），但会对新写入强制校验。
--
-- 注意：
-- - 本脚本使用 NOT VALID：不会扫描历史数据，但会对新写入强制校验；
-- - 若你希望对历史数据也给出“强一致保证”：
--   - 在启用 Timescale 压缩（columnstore）后的 hypertable/chunk 上，`VALIDATE CONSTRAINT` 在部分版本/组合上不受支持；
--   - 推荐低峰执行“重建 validated CHECK（ADD v2 / DROP / RENAME）”，见：
--     `docs/analysis/crypto_raw_trades_hardening_runbook.md`。
--

CREATE SCHEMA IF NOT EXISTS crypto;

DO $$
BEGIN
    -- ==================== futures UM trades ====================
    IF to_regclass('crypto.raw_futures_um_trades') IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'chk_raw_futures_um_trades_sanity'
              AND conrelid = 'crypto.raw_futures_um_trades'::regclass
        ) THEN
            EXECUTE $sql$
                ALTER TABLE crypto.raw_futures_um_trades
                ADD CONSTRAINT chk_raw_futures_um_trades_sanity
                CHECK (
                  venue_id > 0
                  AND instrument_id > 0
                  AND time > 0
                  AND id >= 0
                  AND price >= 0
                  AND qty >= 0
                  AND quote_qty >= 0
                )
                NOT VALID
            $sql$;
        END IF;
    END IF;

    -- ==================== futures CM trades ====================
    IF to_regclass('crypto.raw_futures_cm_trades') IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'chk_raw_futures_cm_trades_sanity'
              AND conrelid = 'crypto.raw_futures_cm_trades'::regclass
        ) THEN
            EXECUTE $sql$
                ALTER TABLE crypto.raw_futures_cm_trades
                ADD CONSTRAINT chk_raw_futures_cm_trades_sanity
                CHECK (
                  venue_id > 0
                  AND instrument_id > 0
                  AND time > 0
                  AND id >= 0
                  AND price >= 0
                  AND qty >= 0
                  AND quote_qty >= 0
                )
                NOT VALID
            $sql$;
        END IF;
    END IF;

    -- ==================== spot trades ====================
    IF to_regclass('crypto.raw_spot_trades') IS NOT NULL THEN
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = 'chk_raw_spot_trades_sanity'
              AND conrelid = 'crypto.raw_spot_trades'::regclass
        ) THEN
            EXECUTE $sql$
                ALTER TABLE crypto.raw_spot_trades
                ADD CONSTRAINT chk_raw_spot_trades_sanity
                CHECK (
                  venue_id > 0
                  AND instrument_id > 0
                  AND time > 0
                  AND id >= 0
                  AND price >= 0
                  AND qty >= 0
                  AND quote_qty >= 0
                )
                NOT VALID
            $sql$;
        END IF;
    END IF;
END
$$;
