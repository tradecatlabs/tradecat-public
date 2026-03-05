# 0026 - closeout-cagg-consumption-contract

## 核心价值（Why）
收敛“高周期缺表/缺数据 + 消费层依赖漂移 + 契约示例与门禁滞后”为可重复执行的闭环，让 Query Service 与指标计算在任意环境下都能稳定复现。

## In Scope

- 对齐服务实际使用的 PG DSN（`DATABASE_URL`/`QUERY_PG_*`），避免对错库执行 DDL
- 在运行库执行 `assets/database/db/schema/007_metrics_cagg_from_5m.sql` 并完成首次 refresh/backfill
- 复核 consumption 层无直连 DB、无 `/api/futures/` 依赖，统一走 `/api/v1/*`
- 对齐 `services/consumption/api-service/docs/API_EXAMPLES.md` 与真实响应（含 missing_table/not_supported）
- 门禁复验：`./scripts/verify.sh` + 核心服务 `make check`（本地）

## Out of Scope

- 服务器部署/远程运维（本任务只做本地闭环，服务器另开任务）
- 新增数据源/新增指标计算逻辑（不新增“手写聚合写入链路”）
- 大范围 API 语义变更（只修复缺表/漂移导致的功能不可用）

## 执行顺序（流程锁）

1. 读 `CONTEXT.md`（确认根因/风险/假设）
2. 按 `PLAN.md` 做决策与回滚预案
3. 严格逐条执行 `TODO.md`，每条把证据写入 `STATUS.md`
4. 满足 `ACCEPTANCE.md` 后才可标记 Done

