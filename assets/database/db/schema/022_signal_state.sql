-- Signal Service 状态库（SQLite → PG）
--
-- 目的：
-- - 替代 assets/database/services/signal-service 下的 cooldown.db / signal_subs.db / signal_history.db
-- - 让 signal-service / telegram-service / api-service 共享同一份状态真相源（DATABASE_URL）
--
-- 注意：
-- - 本文件不做“业务级唯一约束”猜测，仅提供与现有 SQLite 语义等价的最小表结构与必要索引。

CREATE SCHEMA IF NOT EXISTS signal_state;

-- 冷却表：防止同一信号在短时间内重复推送
CREATE TABLE IF NOT EXISTS signal_state.cooldown (
  key text PRIMARY KEY,
  ts_epoch double precision NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cooldown_ts_epoch_idx ON signal_state.cooldown (ts_epoch);

-- 订阅表：按用户（或 chat_id）存储信号开关与启用的表集合
CREATE TABLE IF NOT EXISTS signal_state.signal_subs (
  user_id bigint PRIMARY KEY,
  enabled boolean NOT NULL DEFAULT true,
  tables jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS signal_subs_enabled_idx ON signal_state.signal_subs (enabled);

-- 历史表：记录信号触发历史（用于复盘/审计）
CREATE TABLE IF NOT EXISTS signal_state.signal_history (
  id bigserial PRIMARY KEY,
  ts timestamptz NOT NULL,
  symbol text NOT NULL,
  signal_type text NOT NULL,
  direction text NOT NULL,
  strength integer NOT NULL,
  message text,
  timeframe text,
  price double precision,
  source text NOT NULL DEFAULT 'pg',
  extra jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS signal_history_symbol_idx ON signal_state.signal_history (symbol);
CREATE INDEX IF NOT EXISTS signal_history_ts_idx ON signal_state.signal_history (ts DESC);
CREATE INDEX IF NOT EXISTS signal_history_direction_idx ON signal_state.signal_history (direction);

