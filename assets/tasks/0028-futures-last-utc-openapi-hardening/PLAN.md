# PLAN - futures-last-utc-openapi-hardening

## 技术选型分析（至少两案）

### 方案 A：复用 Timescale continuous aggregates（推荐）

做法：
- 在“运行库”执行仓库既有 DDL：`assets/database/db/schema/007_metrics_cagg_from_5m.sql`
- 手动 refresh/backfill 一个有限窗口（例如 30 天），确保 `WITH NO DATA` 不再为空
- 挂载/确认 policy 以支持后续自动刷新

Pros：
- 与仓库 DDL 真相源一致，最少代码变更
- 统一口径（bucket/last/points/complete）可复用到 query-service 与 compute

Cons：
- 初次 refresh 可能重（必须窗口控制）

### 方案 B：compute 侧定时“手写聚合”写入物理表（不推荐）

Pros：
- 刷新粒度可控

Cons：
- 新增写入链路 + 幂等 + 回填 + 对账成本高
- 易产生“多世界语义漂移”（聚合口径在不同服务里分叉）

结论：采用 **方案 A**。

## 逻辑流图（ASCII）

```text
TimescaleDB (运行库, DSN=DATABASE_URL)
  ├─ market_data.binance_futures_metrics_5m (source)
  └─ CAGG: market_data.binance_futures_metrics_{15m,1h,4h,1d,1w}_last
            ▲
            │ (refresh/backfill + policy)
            │
compute (trading-service)
  └─ indicators/incremental/futures_sentiment.py 读取 *_last

Query Service (api-service)
  ├─ /api/v1/* 契约端点
  └─ /docs OpenAPI + docs/API_EXAMPLES.md
```

## 原子变更清单（操作序列）

> 本任务为任务文档；执行 Agent 按 TODO 实施并记录证据。

1) DSN 对齐（止血）
- 记录 `DATABASE_URL`（以及如存在 `QUERY_PG_MARKET_URL`）的 target DB 名称与主机
- 禁止在 DSN 未确认前执行 DDL/refresh

2) CAGG DDL + refresh/backfill
- 执行 DDL（幂等）：`psql "$DATABASE_URL" -f assets/database/db/schema/007_metrics_cagg_from_5m.sql`
- 发现 view 存在但无数据：执行 refresh/backfill（窗口默认 30 天，可分段）

3) scheduler UTC 口径统一
- 审计 `simple_scheduler.py` 的 NOW() 窗口条件
- 对 `timestamp without time zone` 的比较统一 `(NOW() AT TIME ZONE 'UTC')`
- Python 侧统一 tz-aware UTC（不允许 naive datetime 参与比较）

4) OpenAPI/示例对齐
- 补齐 /api/v1 端点的 summary/description/response_model（以 FastAPI 生成 OpenAPI）
- 更新 `services/consumption/api-service/docs/API_EXAMPLES.md`，确保与实际 curl 输出一致（脱敏）

## 回滚协议（Rollback）

1) CAGG refresh 过重：
- 立即停止 refresh；缩小窗口分段执行（按周/按日）
- 必要时移除 policy（不 drop 视图）：
  - `SELECT remove_continuous_aggregate_policy('market_data.binance_futures_metrics_1h_last');`

2) scheduler UTC 改动引入回归：
- 回滚到上一提交；保留审计结论与最小重现用例

3) OpenAPI/示例变更导致 CI 失败：
- 先回滚 docs（不回滚行为）；用最小差异逐步补齐 response_model

