-- HF stack（高频/原子事实库）
--
-- 适用：
-- - 逐笔/订单簿等“原子事实”落库：core/* + storage/* + crypto.raw_*
-- - 推荐连接到独立的 Timescale 实例（例如 localhost:15432/market_data）
--
-- 注意：
-- - 本脚本用于“新库初始化/补齐缺失对象”；
-- - 对于已存在的 legacy 表结构漂移（同名不同列），需要用 rename-swap 迁移脚本处理，
--   `CREATE TABLE IF NOT EXISTS` 不会自动升级旧表。

\ir ../schema/000_timescaledb_extension.sql

\ir ../schema/008_multi_market_core_and_storage.sql
\ir ../schema/009_crypto_binance_vision_landing.sql
\ir ../schema/010_multi_market_roots_placeholders.sql
\ir ../schema/012_crypto_ingest_governance.sql
\ir ../schema/013_core_symbol_map_hardening.sql
\ir ../schema/016_crypto_trades_readable_views.sql
\ir ../schema/019_crypto_raw_trades_sanity_checks.sql
