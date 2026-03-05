# PLAN - 0026 closeout-cagg-consumption-contract

## 技术选型分析（至少两案）

### 方案 A：执行仓库既有 CAGG DDL + 首次 refresh/backfill（推荐）

做法：
- 对齐服务实际 DSN（`DATABASE_URL`/`QUERY_PG_*`）到“运行库”
- 执行：`assets/database/db/schema/007_metrics_cagg_from_5m.sql`
- 进行有限窗口 refresh/backfill（默认 30 天，必要时分段）

Pros：
- 与仓库 DDL 真相源一致（最少工程漂移）
- compute/api 的读取路径无需新增聚合写入链路
- 可复用 Timescale policy 自动增量刷新

Cons：
- 初次 refresh 可能重（需窗口控制与低峰执行）

### 方案 B：计算服务定时“手写聚合”写入 `_last` 物理表（不推荐）

做法：
- trading-service/signal-service 定时从 5m 聚合写入 15m/1h/... 表（物理表）

Pros：
- 刷新粒度可控（可按 symbol/时间分段）

Cons：
- 需要新增表 DDL + 幂等 + 回填 + 对账，工程量大
- 与 Timescale continuous aggregates 重复造轮子
- 更容易出现“多世界语义漂移”（聚合口径与 CAGG 不一致）

结论：采用 **方案 A**。

## 逻辑流图（ASCII）

```text
TimescaleDB(运行库，DSN=DATABASE_URL 或 QUERY_PG_MARKET_URL)
  ├─ market_data.binance_futures_metrics_5m (source, 5m)
  └─ CAGG: market_data.binance_futures_metrics_{15m,1h,4h,1d,1w}_last
            ▲
            │ refresh/backfill + policy
            │
Query Service (api-service)
  ├─ /api/v1/*  (稳定契约：capabilities/cards/dashboard/ohlc)
  └─ /api/futures/* (兼容层；消费侧禁止依赖)
            ▲
            │ HTTP only
            │
consumption: telegram / sheets / vis
  └─ 只调用 /api/v1/*
```

## 原子变更清单（文件级/操作级）

> 本任务为“任务文档”，不直接改业务代码；执行 Agent 按 TODO 执行并把证据写入 STATUS。

1) 数据库操作（运行库）
- `psql "$DATABASE_URL" -f assets/database/db/schema/007_metrics_cagg_from_5m.sql`
- `CALL refresh_continuous_aggregate(...)`（窗口默认 30 天）

2) 消费层收口复核（只读审计 + 必要时修复）
- `rg` 审计 consumption 直连 DB / 旧端点字符串
- `./scripts/verify.sh` 门禁复验

3) 契约示例对齐（若发现漂移）
- 仅在必要时更新 `services/consumption/api-service/docs/API_EXAMPLES.md`，并将 curl 输出“最小化脱敏落盘”

## 回滚协议（Rollback）

1) 若 refresh/backfill 压力过大：
- 立即缩小窗口分段执行（例如按周）
- 必要时移除 policy（不 drop 视图）：
  - `SELECT remove_continuous_aggregate_policy('market_data.binance_futures_metrics_1h_last');`

2) 若发现“对错库执行”：
- 停止所有 DDL/refresh
- 回到“DSN 对齐”步骤重新确认（禁止在不确认 DSN 前继续）

3) 若消费层回归（仍依赖 /api/futures/）：
- 不回滚服务端兼容端点；只修消费侧调用路径（最小化影响）

