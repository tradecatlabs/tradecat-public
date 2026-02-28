-- Sheets Service 状态库（SQLite → PG）
--
-- 目的：
-- - 替代 sheets-service 本地 idempotency.db（sent_keys）
-- - 让幂等去重与写入检查点可被审计/备份/复用

CREATE SCHEMA IF NOT EXISTS sheets_state;

-- 幂等键：同一个 card_key 只允许写入一次（或在 dashboard replace 模式下用于跳过无变更写入）
CREATE TABLE IF NOT EXISTS sheets_state.sent_keys (
  card_key text PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now()
);

