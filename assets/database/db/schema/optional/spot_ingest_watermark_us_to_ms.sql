-- spot_ingest_watermark_us_to_ms.sql
--
-- 目的：
-- - spot trades 的事实表 time 对齐 Binance Vision CSV，单位为 epoch(us)
-- - 但治理表 crypto.ingest_watermark.last_time 约定为 epoch(ms)（与 REST since / ingest_gaps 同单位）
-- - 如果历史上曾把 spot watermark 写成 us（~1e15），会导致后续写入（ms ~1e12）永远无法覆盖（GREATEST 会保留旧值）。
--
-- 迁移策略（安全门禁）：
-- - 仅对 dataset='spot.trades' 且 last_time >= 1e13 的行做 /1000 转换
--   - ms 在 2286 年左右才会达到 1e13，因此该阈值足够安全

BEGIN;

UPDATE crypto.ingest_watermark
SET last_time = (last_time / 1000),
    updated_at = NOW()
WHERE dataset = 'spot.trades'
  AND last_time >= 10000000000000;

COMMIT;

-- 自检
SELECT exchange, dataset, symbol, last_time, last_id, updated_at
FROM crypto.ingest_watermark
WHERE dataset = 'spot.trades'
ORDER BY updated_at DESC
LIMIT 20;

