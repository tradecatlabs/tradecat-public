-- 016_crypto_trades_readable_views.sql
--
-- 目标：
-- - 为 crypto trades 事实表提供“人类可读”的只读视图（不污染事实表）：
--   - time(epoch ms/us) -> timestamptz（UTC） + timestamp（UTC+8 展示）
--   - ids(venue_id/instrument_id) -> venue_code + symbol（as-of 映射）
--
-- 依赖：
-- - 008_multi_market_core_and_storage.sql（core.venue/core.symbol_map）
-- - 009_crypto_binance_vision_landing.sql（crypto.raw_*_trades）

CREATE SCHEMA IF NOT EXISTS crypto;

-- ==================== futures UM trades readable view ====================
CREATE OR REPLACE VIEW crypto.vw_futures_um_trades AS
SELECT
    v.venue_code,
    sm.symbol,
    t.venue_id,
    t.instrument_id,
    t.time,
    ts.time_ts_utc,
    (ts.time_ts_utc AT TIME ZONE 'Asia/Shanghai') AS time_ts_cn,
    t.id,
    t.price,
    t.qty,
    t.quote_qty,
    t.is_buyer_maker
FROM crypto.raw_futures_um_trades t
JOIN core.venue v
  ON v.venue_id = t.venue_id
CROSS JOIN LATERAL (
    SELECT to_timestamp(t.time / 1000.0) AS time_ts_utc
) ts
LEFT JOIN LATERAL (
    SELECT m.symbol
    FROM core.symbol_map m
    WHERE m.venue_id = t.venue_id
      AND m.instrument_id = t.instrument_id
      AND tstzrange(
            m.effective_from,
            COALESCE(m.effective_to, 'infinity'::timestamptz),
            '[)'
          ) @> ts.time_ts_utc
    LIMIT 1
) sm ON TRUE;

-- ==================== futures CM trades readable view ====================
CREATE OR REPLACE VIEW crypto.vw_futures_cm_trades AS
SELECT
    v.venue_code,
    sm.symbol,
    t.venue_id,
    t.instrument_id,
    t.time,
    ts.time_ts_utc,
    (ts.time_ts_utc AT TIME ZONE 'Asia/Shanghai') AS time_ts_cn,
    t.id,
    t.price,
    t.qty,
    t.quote_qty,
    t.is_buyer_maker
FROM crypto.raw_futures_cm_trades t
JOIN core.venue v
  ON v.venue_id = t.venue_id
CROSS JOIN LATERAL (
    SELECT to_timestamp(t.time / 1000.0) AS time_ts_utc
) ts
LEFT JOIN LATERAL (
    SELECT m.symbol
    FROM core.symbol_map m
    WHERE m.venue_id = t.venue_id
      AND m.instrument_id = t.instrument_id
      AND tstzrange(
            m.effective_from,
            COALESCE(m.effective_to, 'infinity'::timestamptz),
            '[)'
          ) @> ts.time_ts_utc
    LIMIT 1
) sm ON TRUE;

-- ==================== spot trades readable view ====================
CREATE OR REPLACE VIEW crypto.vw_spot_trades AS
SELECT
    v.venue_code,
    sm.symbol,
    t.venue_id,
    t.instrument_id,
    t.time,
    ts.time_ts_utc,
    (ts.time_ts_utc AT TIME ZONE 'Asia/Shanghai') AS time_ts_cn,
    t.id,
    t.price,
    t.qty,
    t.quote_qty,
    t.is_buyer_maker,
    t.is_best_match
FROM crypto.raw_spot_trades t
JOIN core.venue v
  ON v.venue_id = t.venue_id
CROSS JOIN LATERAL (
    SELECT to_timestamp(t.time / 1000000.0) AS time_ts_utc
) ts
LEFT JOIN LATERAL (
    SELECT m.symbol
    FROM core.symbol_map m
    WHERE m.venue_id = t.venue_id
      AND m.instrument_id = t.instrument_id
      AND tstzrange(
            m.effective_from,
            COALESCE(m.effective_to, 'infinity'::timestamptz),
            '[)'
          ) @> ts.time_ts_utc
    LIMIT 1
) sm ON TRUE;
