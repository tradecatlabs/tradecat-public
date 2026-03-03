# 0022 - api-service-contract-cleanup

## 核心价值（Why）

`api-service` 作为 **Query Service / 契约层** 的目标是“对外接口稳定、对内实现可变”。当前 futures 路由已收口到 `datasources(MARKET)`，但仍存在三类“尾巴”：

1) **路由层连接池分裂**：`coins/base_data/signal/indicator` 仍在使用 `get_pg_pool()` 直连（绕过 datasources），无法统一多 DSN / 探活 / 参数治理。  
2) **缺表诊断不结构化**：缺表目前只在 `msg` 文本里提示，缺少可机读的 `missing_table` 字段，排障/监控不友好。  
3) **tasks/状态漂移**：`assets/tasks/INDEX.md` 与各任务 `STATUS.md/TODO.md` 出现状态不一致，容易造成“我以为做了”的运维事故。

本任务的落点：把上述尾巴收干净，让“契约层”在工程上也更像契约层。

## In Scope

- tasks/索引与状态对齐（仅改 `assets/tasks/**`）：
  - `0015` Index 状态与 `STATUS.md` 对齐
  - `0020` TODO 打勾与证据补全（避免任务已做但显示未做）
- 统一错误响应可扩展（结构化 meta）：
  - `error_response(...)` 支持附带额外字段（不改变既有字段）
  - futures 缺表错误补齐 `missing_table:{schema,table}`
- 清理 `api-service` 路由层 `get_pg_pool()` 散落（统一 `datasources`）：
  - `routers/coins.py`
  - `routers/base_data.py`
  - `routers/signal.py`
  - `routers/indicator.py`
- 测试与最小冒烟：
  - 单测覆盖 `missing_table` 输出
  - `rg` 门禁：路由层不再引用 `get_pg_pool()`

## Out of Scope

- 不改数据库 schema / 不补建表（缺表属于 compute/ingestion 职责）。
- 不删除旧端点（只做“连接池统一 + 诊断增强 + 文档对齐”）。
- 不改变业务字段语义（仅新增可选 meta 字段，保持兼容）。

## 执行顺序（必须）

1. `CONTEXT.md`
2. `PLAN.md`
3. `TODO.md`
4. `ACCEPTANCE.md`
5. `STATUS.md`

