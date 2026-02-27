# PLAN

## 核心策略：view 只解决“可读性”，不引入新事实字段

- 事实表保持：ids + 原子字段 + 整数时间轴。
- view 做两件事：
  1) `time` → `timestamptz`（UTC/UTC+8）
  2) ids → 可读维度（`venue_code/symbol`）

## 技术路线

1. 为 UM/CM/Spot 分别建 view（原因：Spot time 单位是 us；UM/CM 是 ms）。
2. symbol_map join 用 as-of：
   - 条件：`t.time_ts_utc >= effective_from` AND (`effective_to` IS NULL OR `t.time_ts_utc < effective_to`)
   - 取 1 条：`ORDER BY effective_from DESC LIMIT 1`
3. 输出字段保持稳定顺序（便于下游脚本）。

## 交付物

- 新增 SQL：`assets/database/db/schema/016_crypto_trades_readable_views.sql`（编号如已占用则顺延）
- 执行后可在 DB 里直接 `SELECT` 使用。

