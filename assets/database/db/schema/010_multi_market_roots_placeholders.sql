-- 010_multi_market_roots_placeholders.sql
--
-- 目标：
-- - 先把“按市场类型分根”的 schema 骨架建出来（占位），后续逐个市场再补事实表/维表。
-- - 该脚本不创建任何事实表，避免过早定型。

CREATE SCHEMA IF NOT EXISTS equities;
CREATE SCHEMA IF NOT EXISTS fx;
CREATE SCHEMA IF NOT EXISTS commodities;
CREATE SCHEMA IF NOT EXISTS rates;
CREATE SCHEMA IF NOT EXISTS funds;
CREATE SCHEMA IF NOT EXISTS indices;

