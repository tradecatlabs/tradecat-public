-- LF stack（低频/分时/K线与指标库）
--
-- 适用：
-- - K线 1m 基表 + 指标汇总 + Continuous Aggregates（market_data/*）
-- - 推荐连接到独立的 Timescale 实例（例如 localhost:5433/market_data）
--
-- 注意：
-- - 本脚本会创建 market_data schema 与 candles_1m 等表。

\ir ../schema/001_timescaledb.sql
\ir ../schema/002_taker_buy_and_gap_tracking.sql
\ir ../schema/003_add_all_intervals.sql
\ir ../schema/004_continuous_aggregates.sql
\ir ../schema/005_metrics_5m.sql
\ir ../schema/007_metrics_cagg_from_5m.sql

-- TG 卡片/指标派生表（对齐 telegram-service SQLite 结构）
\ir ../schema/021_tg_cards_sqlite_parity.sql
