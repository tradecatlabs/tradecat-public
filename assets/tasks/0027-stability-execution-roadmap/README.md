# 任务门户：stability-execution-roadmap

## Why（价值，100字内）

把当前仍未闭环的稳定性工作收敛为一条可执行路线图：优先解决 data-service ban/backoff 与 sheets-service 弱网/配额问题，收尾“单 PG”清理与 Query Service 生产化 P2，用统一门禁保证采集→计算→查询→导出可长期跑。

## In Scope（范围）

- 明确“剩余工作清单”与执行顺序（P0→P1→P2），避免多任务并行导致漂移。
- 以任务为原子单元推进与验收：
  - `0018-stabilize-data-service-ban-backoff`（P0）
  - `0012-sheets-service-hardening`（P0）
  - `0015-unify-all-storage-to-postgres`（P0 补齐证据 + P2 收尾）
  - `0025-query-service-production-hardening`（P2 收口）
  - `0020-data-api-contract-hardening`（P0/P2 收口，主要是证据与 OpenAPI/缓存）
- 统一“全仓门禁”与证据留存口径（Verify/Gate/回滚点/敏感信息保护）。
- 修复 tasks 文档漂移：确保“代码真实状态”与 `assets/tasks/*/TODO.md`、`STATUS.md`、`INDEX.md` 一致。

## Out of Scope（不做）

- 不做服务器部署/远程运维（另开任务）。
- 不新增业务指标/卡片；不改既有展示口径。
- 不引入新基础设施（Redis/Kafka 等）作为本路线图的前置依赖。

## 执行顺序（流程锁）

1. `CONTEXT.md`（现状证据与风险图谱）
2. `PLAN.md`（方案选择与回滚协议）
3. `TODO.md`（逐条执行 + 证据写入）
4. `ACCEPTANCE.md`（验收断言对照）
5. `STATUS.md`（进度真相源）

