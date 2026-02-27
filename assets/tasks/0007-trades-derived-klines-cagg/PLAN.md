# PLAN

## 方案选择

### 方案 A（推荐）：Timescale continuous aggregate

Pros
- 自动增量刷新，适合长期运行。
- 产物可直接给训练/回测脚本读取。

Cons
- 需要设计刷新窗口（end_offset）避免与实时写入打架。

### 方案 B：纯 SQL view（每次现算）

Pros
- 0 存储。

Cons
- 大数据量下不可用（训练/回测会很慢）。

结论：采用方案 A。

## 实现要点

- futures（ms）：
  - bucket：`time_bucket(60000, time)` 得到 1m bucket(ms)
- spot（us）：
  - bucket：`time_bucket(60_000_000, time)` 得到 1m bucket(us)
- 维度：以 `(venue_id,instrument_id,bucket)` 为唯一键（后续可 join core 显示 symbol）。

## 交付物

- 新增 SQL：`assets/database/db/schema/017_crypto_trades_cagg_klines.sql`（编号如已占用则顺延）
- 在 `crypto` schema 下创建：
  - `crypto.cagg_futures_um_klines_1m`
  - `crypto.cagg_futures_cm_klines_1m`
  - `crypto.cagg_spot_klines_1m`

