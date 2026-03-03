# 0020 - data-api-contract-hardening

## 核心价值（Why）

当前消费侧（telegram/sheets/vis）虽然已统一通过 Query Service（`services/consumption/api-service`）读取数据，但接口仍暴露 **内部表名/列名**（如 `基础数据同步器.py`、`交易对/周期/数据时间`）。一旦 compute 侧表结构/字段名/聚合策略调整，消费侧就会被迫联动修改，违背“统一数据接口遮蔽实现变动”的目标。

本任务的落点：把 `api-service` 强化为真正的 **稳定数据契约层（Data API / Serving API）**，对内对外提供稳定抽象接口（card_id/field_id/interval/symbol），让采集/计算如何演进都不“外溢”到消费层。

## In Scope

- 在 `api-service` 新增稳定契约端点（`/api/v1`）：
  - `GET /api/v1/capabilities`：能力发现（cards/fields/intervals/数据源健康）
  - `GET /api/v1/cards/{card_id}`：卡片级数据读取（排行榜/快照所需字段的稳定输出）
  - `GET /api/v1/dashboard`：看板级聚合输出（按 card_id/intervals/symbols，一次取全）
- 抽取并收敛“卡片字段/表映射”的单一真相源（建议放在 `assets/common/`），避免 `api-service` 与 `telegram-service` 各维护一套映射导致口径漂移。
- 迁移消费侧只依赖稳定端点：
  - `telegram-service`（`cards/data_provider.py` 等）不再依赖 `/api/v1/indicators/{table}` 与表名映射
  - `sheets-service`（复用 TG 导出逻辑）同步迁移
  - `vis-service` 同步迁移到稳定端点（保持“禁止直连 DB”的硬约束）
- 对旧接口制定“退场策略”：
  - `table 直通`/`调试接口`保留一段时间但 **不再被消费侧依赖**；并逐步加上内网 token 保护与 Deprecation 标记

## Out of Scope

- 不更改数据库 schema（`tg_cards.*`、`market_data.*`、`signal_state.*`）与 compute 侧写入逻辑（除非为契约补齐必须且最小）。
- 不重写对外 CoinGlass 风格路径的全部语义（仅做“最小遮蔽/降级/数据源抽象贯穿”的必要修补）。
- 不进行 UI/卡片文案的主观重写（以“输出不变”为优先）。

## 执行顺序（必须）

1. `CONTEXT.md`（现状证据、风险、假设）
2. `PLAN.md`（方案选择、数据流、回滚）
3. `TODO.md`（逐条执行 + 验证）
4. `ACCEPTANCE.md`（验收断言对照）
5. `STATUS.md`（记录命令与证据）

