# PLAN - 发布 Query Service v1 + 补齐期货 CAGG

## 技术选型分析（至少两案）

### A) 直接启用 Timescale continuous aggregates（推荐）

做法：
- 执行仓库既有 DDL：`assets/database/db/schema/007_metrics_cagg_from_5m.sql`
- 生成 `market_data.binance_futures_metrics_{15m,1h,4h,1d,1w}_last`
- 首次手动 refresh/backfill 一个有限窗口（例如 90 天）以避免 `WITH NO DATA` 导致“表存在但查不到数据”

Pros：
- 与 DDL 真相源一致，最少业务代码改动
- 支持自动 policy 刷新（`add_continuous_aggregate_policy` 已内置）
- compute/api 现有读取路径无需再写一套聚合逻辑

Cons：
- 初次 refresh 可能重（需控制窗口/低峰）

### B) 计算服务自己写派生表（不推荐作为默认）

做法：
- trading-service/signal-service 定时任务按 5m 聚合写入 `_last` 物理表

Pros：
- 可控性强（可按 symbol/窗口分批）

Cons：
- 需要新表 DDL、新写入链路、幂等与回填逻辑，工程量大
- 与 Timescale 现有能力重复

结论：采用 **方案 A**。

## 关键决策（本任务的“写死规则”）

1) `timestamp without time zone`（期货 metrics）统一按 **UTC** 解释  
   - SQL 窗口比较统一：`(NOW() AT TIME ZONE 'UTC') - INTERVAL ...`
2) consumption 层只读 `/api/v1/*`：允许保留 `/api/futures/*` 作为兼容，但 **不得再被消费方调用**
3) `OTHER` 数据源作为可选项：未配置时 **不进入** health 输出（避免误报）

## 逻辑流图（ASCII）

```text
TimescaleDB (LF)
  ├─ market_data.binance_futures_metrics_5m (source, 5m)
  └─ CAGG: market_data.binance_futures_metrics_{15m,1h,4h,1d,1w}_last
            ▲
            │ (refresh/backfill + policy)
            │
Query Service (api-service)
  ├─ /api/v1/*      (稳定契约：cards/dashboard/symbol snapshot)
  ├─ /api/v1/ohlc/* (v1 wrapper, 供消费侧使用)
  └─ /api/futures/* (兼容层；消费侧禁止调用)
            ▲
            │ HTTP only
            │
consumption: telegram / sheets / vis
  └─ 只调用 /api/v1/*
```

## 原子变更清单（文件级，执行 Agent 用）

> 注意：本文件只列“预期改动点”，不在此任务中直接改代码。

### 1) 数据库（DDL/运维）

- 执行：`assets/database/db/schema/007_metrics_cagg_from_5m.sql`
- 可能需要追加：一个“手动 refresh 脚本”写入 `assets/database/db/`（如需）

### 2) Query Service v1 wrapper（迁移消费侧）

- api-service：
  - 新增 `/api/v1/ohlc/history`（语义对齐 `/api/futures/ohlc/history`）
  - 更新 `datasources.check_sources()`：OTHER 未配置则跳过
- vis-service：
  - `services/consumption/vis-service/src/templates/registry.py`：从 `/api/futures/ohlc/history` 迁移到 `/api/v1/ohlc/history`
- scripts：
  - `scripts/verify.sh`：增加门禁（消费层禁止出现 `"/api/futures/"` 字符串）

### 3) 输出类型/单位标准化 + 文档对齐（0020 P1）

- 规范化 `fields` 的数值类型（float/int/str 的统一规则）
- 更新 `services/consumption/api-service/docs/API_EXAMPLES.md`：
  - Base URL 从 8089 → 8088
  - 补齐 `/api/v1/*` 示例与 `missing_table` 示例

### 4) scheduler UTC 统一

- trading-service：
  - `src/core/async_full_engine.py`：`create_time > NOW()` → `create_time > (NOW() AT TIME ZONE 'UTC')`
  - `src/core/storage.py`：同上
  - `src/indicators/batch/futures_gap_monitor.py`：`NOW()` → UTC 基准

## 回滚协议（Rollback）

1) CAGG 相关：
   - 若 refresh 造成 DB 压力：停止 refresh，缩小窗口分段执行；必要时移除 policy：
     - `SELECT remove_continuous_aggregate_policy('market_data.binance_futures_metrics_1h_last');`
2) v1 wrapper：
   - 若消费侧失败：恢复 vis-service 到旧路径（仅回滚消费侧，不动服务端兼容端点）
3) OTHER health：
   - 若需要强制探测 OTHER：改为必须配置 env（恢复 missing_env 行为）

