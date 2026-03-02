# 任务门户：migrate-consumption-to-query-service

## Why（价值）

统一“读数据”出口，彻底移除 consumption 层直连 PostgreSQL 与口径漂移：以 `/api/v1` 契约化 Query Service 为唯一数据源，让 Telegram/Sheets/外部消费只依赖稳定接口，并为未来多数据源扩展打底。

## In Scope（范围）

- 将 `services/consumption/api-service` 升级为 **Query Service（唯一读出口）**：
  - 新增 `/api/v1/health`、`/api/v1/dashboard`、`/api/v1/symbol/{symbol}/snapshot`
  - 统一时间规范（UTC 基准；输出 `ts_utc/ts_ms/ts_shanghai`）
  - 统一“有效行过滤”与“最新快照”规则（消费端不再重复实现）
  - 支持多数据源 DSN（指标库/行情库/未来其它库），以“领域路由”对外暴露
- `services/consumption/telegram-service`：
  - 删除 `PgRankingDataProvider` 与所有 `psycopg/SQL` 直连逻辑
  - 卡片渲染只通过 Query Service 获取数据（不保留 fallback）
- `services/consumption/sheets-service`：
  - 删除 `PG 幂等存储（sheets_state.sent_keys）` 直连逻辑
  - 幂等/检查点改为 **Sheets 自身存储**（隐藏 tab 或 DeveloperMetadata），仅走 Sheets API
  - 指标数据只通过 Query Service 获取（不保留 fallback）
- 质量门禁（强制）：
  - `scripts/verify.sh`/CI：除 Query Service 外，`services/consumption/**/src` 禁止出现 DB 直连与 `tg_cards/market_data` SQL 片段
- 文档与配置模板同步：
  - 更新 `assets/config/.env.example` 与各服务 README，使运维口径与新架构一致

## Out of Scope（不做）

- 不改 ingestion/compute 的写入链路为 HTTP（写入仍直连数据库）
- 不做 `tg_cards` 表结构大迁移（例如 text 时间改 `timestamptz`）
- 不引入面向公网的复杂鉴权体系（仅内部 token/内网即可）

## 执行顺序（强制）

1. `CONTEXT.md`（现状与证据）
2. `PLAN.md`（方案选择与路径）
3. `TODO.md`（可执行清单）
4. `ACCEPTANCE.md`（验收口径）
5. `STATUS.md`（记录执行证据）

