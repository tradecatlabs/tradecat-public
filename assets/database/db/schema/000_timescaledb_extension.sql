-- 000_timescaledb_extension.sql
--
-- 目标：
-- - 仅确保 TimescaleDB 扩展存在（不创建任何表/视图）。
--
-- 用途：
-- - 供 “HF/原子事实库（core/crypto/storage）” 的 stack 入口脚本引用，
--   避免误跑 `001_timescaledb.sql` 把 market_data/candles_1m 等低频表也创建出来。

CREATE EXTENSION IF NOT EXISTS timescaledb;

