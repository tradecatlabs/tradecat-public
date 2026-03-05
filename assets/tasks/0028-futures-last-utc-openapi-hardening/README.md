# 任务门户：futures-last-utc-openapi-hardening

## Why（价值，100字内）

把“期货高周期缺表/缺数据”“UTC 时间口径不统一”“OpenAPI/示例与真实行为漂移”三类问题一次性收敛到可重复执行的闭环，确保 compute 的期货情绪指标与 consumption 的 /api/v1 契约在任意环境下可稳定复现。

## In Scope（范围）

- 运行库（Timescale/LF）补齐并回填：
  - `market_data.binance_futures_metrics_{15m,1h,4h,1d,1w}_last`
- 统一 scheduler/SQL 比较口径（仅针对 `timestamp without time zone`）：
  - 以 UTC 为基准进行窗口过滤与“新数据判断”，避免“看起来超前/落后”的错觉
- 完善 Query Service（api-service）OpenAPI（/docs）与 `API_EXAMPLES.md`：
  - 字段说明、错误语义、示例与真实响应一致
- 端到端门禁复验：`./scripts/verify.sh` + 核心服务 `make check`

## Out of Scope（不做）

- 不新增数据源；不引入 Redis/Kafka 等基础设施
- 不改写事实表结构（仅执行仓库已有 DDL；必要时只做最小增量的运维脚本）
- 不做服务器部署（另开任务）；本任务只保证本地与“可迁移执行脚本”闭环

## 执行顺序（流程锁）

1. `CONTEXT.md`（现状证据与风险图谱）
2. `PLAN.md`（方案选择与回滚协议）
3. `TODO.md`（逐条执行 + 证据写入 `STATUS.md`）
4. `ACCEPTANCE.md`（验收断言对照）
5. `STATUS.md`（进度真相源）

