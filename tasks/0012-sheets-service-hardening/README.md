# 0012 - sheets-service-hardening

目标：在不改变现有表格结构与展示口径（看板 v5 / 币种查询 / Polymarket 三表）的前提下，对 `sheets-service` 做“长期可运维”的加固：更稳、更省配额、更少噪音、更易回滚。

## Why（价值）

- 目前服务在弱网/代理环境下会出现间歇性 `SSLError/ConnectionResetError`，尤其在 `prune_tabs` 这种额外读写操作上表现明显。
- 目前部分“维护性操作”（例如 prune、列宽固化）需要手工脚本/临时命令；应收敛到标准 CLI 与可审计的 meta 记录。
- 日志噪音偏高（大量 `[DEBUG]` 与“模块未导出 CARD”），影响排障效率。

## In Scope

- `prune_tabs` 调度化：只在必要时执行（按间隔/配置变更触发），避免每轮同步都调用。
- `SaSheetsWriter._exec` 读请求的“弱网重试”增强：覆盖 `SSLError/ConnectionResetError` 等典型瞬断。
- 列宽固化流程标准化：提供 CLI 输出固定列宽 env（看板/币种查询/Polymarket），减少手工操作。
- 日志治理：将 debug 输出纳入开关（env 控制），默认安静，必要时可开启细粒度调试。
- 文档/运维：补齐与现状一致的 runbook（不写死敏感路径/ID），并提供验证命令。

## Out of Scope

- 改变现有表格结构、字段含义、排序口径（除非为修复明显 bug）。
- 引入 Apps Script Webhook 写入路径（本任务仅加固 SA 模式；Webhook 另开任务）。
- 大规模重构 `telegram-service` 或指标计算链路。
- 数据库 schema 变更。

## 执行顺序（强制）

1. 读 `CONTEXT.md`（现状与风险）
2. 读 `PLAN.md`（方案与取舍）
3. 按 `TODO.md` 执行（逐项验证）
4. 对照 `ACCEPTANCE.md` 验收
5. 更新 `STATUS.md`（留证据）

