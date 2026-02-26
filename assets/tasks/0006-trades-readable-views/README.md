# 0006 - trades-readable-views

## 价值（Why）

逐笔事实表为了“写入成本/可压缩/可回填重跑”保持极简（整数时间轴 + ids），但这会让人类查询（BI/回测脚本/临时排障）成本变高。  
本任务用 **只读视图** 补齐“可读性层”：把 `time(ms/us)` 显示为 `timestamptz`（可按 UTC+8 展示），并 join `core.*` 输出可读的 `venue_code/symbol`，同时 **不污染物理表**。

## 范围（Scope）

### In Scope

- 新增 view（或 materialized view，优先 view）：
  - `crypto.vw_futures_um_trades`
  - `crypto.vw_futures_cm_trades`
  - `crypto.vw_spot_trades`
- view 输出字段至少包含：
  - `venue_code`、`symbol`（可读）
  - `time_ts_utc`（UTC）与 `time_ts_cn`（UTC+8 仅展示）
  - 原始事实字段（id/price/qty/quote_qty/is_buyer_maker/...）
- 维表 join 语义写死（避免行数放大）：按成交时间 as-of 匹配 symbol_map（LATERAL + LIMIT 1 或等价写法）。

### Out of Scope

- 不新增/修改事实表列（不加 `time_ts/ingested_at/file_id`）。
- 不做派生 K 线/聚合（见 task 0007）。

## 执行顺序

1. 阅读 `CONTEXT.md`
2. 按 `PLAN.md` 生成 SQL 脚本与 view
3. 执行 `TODO.md` 验收 `ACCEPTANCE.md`
4. 更新 `STATUS.md` 存证

