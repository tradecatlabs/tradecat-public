# 0021 - harden-futures-datasources-fallback

## 核心价值（Why）

当前 `api-service` 中 futures 相关路由仍在直接使用 `get_pg_pool()`（单 DSN 直连）+ 硬编码 `market_data.*` 表名（包含 `*_last`），一旦高周期派生表缺失，会直接触发 500，破坏“对外接口稳定/对内实现可变”的契约目标。

本任务的落点：把 futures 路由也纳入 Query Service 的 **多数据源抽象（datasources）**，并补齐“缺表/空表降级”策略，同时把旧的“表名直通”端点降级为 **仅内网调试**，彻底避免消费方再耦合内部表名。

## In Scope

- futures 路由统一使用 `src/query/datasources.py` 的 `MARKET` 数据源连接池（替换 `get_pg_pool()`）：
  - `services/consumption/api-service/src/routers/futures_metrics.py`
  - `services/consumption/api-service/src/routers/open_interest.py`
  - `services/consumption/api-service/src/routers/funding_rate.py`
  - `services/consumption/api-service/src/routers/ohlc.py`
- `*_last` 表缺失降级：
  - 缺表时不再返回 500
  - 返回可诊断的错误码/提示（并可选携带 `missing_table`/`fallback` 元信息）
- `/api/v1/indicators/{table}` 端点退场策略：
  - 标记 deprecated
  - 强制内网 token（避免外部误用）
  - 确保核心消费侧（TG/Sheets/Vis）无依赖
- 单测补齐（至少覆盖 1 条缺表降级与 1 条 token 拦截）

## Out of Scope

- 不新增/修改数据库 schema，不补建 `*_last` 表（表是否存在属于 compute/ingestion 的职责）。
- 不改变 CoinGlass 风格响应字段命名与业务语义（只做“缺表不炸/连接池统一/调试端点收口”）。
- 不引入新的外部依赖。

## 执行顺序（必须）

1. `CONTEXT.md`
2. `PLAN.md`
3. `TODO.md`
4. `ACCEPTANCE.md`
5. `STATUS.md`

