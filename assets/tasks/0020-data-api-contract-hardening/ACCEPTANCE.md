# ACCEPTANCE - 验收标准（原子断言）

## Happy Path（成功路径）

1) **能力发现可用**
   - 调用：`GET /api/v1/capabilities`
   - 期望：
     - 返回 `success=true`
     - 包含：`version`、`cards[]`（含 `card_id`）、`intervals[]`、`sources[]`（脱敏 DSN + ok 状态）

2) **卡片级排行榜接口可用且不泄露内部表名/列名**
   - 调用：`GET /api/v1/cards/{card_id}?interval=15m&limit=10`
   - 期望：
     - 输出字段是“稳定契约字段”（例如 `card_id/symbol/fields/ts_*` 等）
     - 响应中 **不得出现** `*.py`、`tg_cards`、`market_data`、`交易对/周期/数据时间` 等内部列名（允许 `symbol/interval/ts_*`）

3) **看板接口可以一次取全（多卡片×多周期）**
   - 调用：`GET /api/v1/dashboard?cards=atr_ranking,super_trend_ranking&intervals=5m,15m,1h&shape=wide`
   - 期望：
     - 单次响应包含所请求的 cards 与 intervals
     - 响应内有 `latest_ts_*`，且格式统一（UTC/UTC+8/ms）

4) **telegram-service 彻底不再依赖表名直通**
   - 期望：
     - `services/consumption/telegram-service/src` 内无 `api/v1/indicators` 调用
     - `TABLE_NAME_MAP` 等“表名映射”被删除/废弃
   - Verify:
     ```bash
     rg -n \"api/v1/indicators\" services/consumption/telegram-service/src -S
     rg -n \"TABLE_NAME_MAP\" services/consumption/telegram-service/src -S
     ```

5) **sheets-service 同步完成迁移**
   - 期望：
     - sheets 导出链路不再 import 旧的 provider 表名路径（若仍复用 TG provider，则 TG provider 必须已迁移）
   - Verify:
     ```bash
     rg -n \"api/v1/indicators\" services/consumption/sheets-service/src -S
     ```

6) **vis-service 继续保持“禁止直连 DB”，且使用稳定端点**
   - Verify:
     ```bash
     rg -n \"psycopg|DATABASE_URL\" services/consumption/vis-service/src -S
     ```

## Edge Cases（边缘场景，至少 3 条）

1) `card_id` 不存在：返回 `4xx` + 可诊断错误码（非 500）。
2) `intervals` 含不支持周期：返回 `4xx` 或从 capabilities 指示的周期集合中过滤，并明确 `ignored_intervals`。
3) 底层数据缺失（空表/缺 ts）：返回 `success=true` 但 rows 为空，且给出 `data_freshness`/`latest_ts_*` 为 null 或占位（不能 500）。

## Anti-Goals（禁止性准则）

- 不允许新增“消费侧直连 DB”的任何逻辑（consumption 仍必须 HTTP 调 Query Service）。
- 不允许为了迁移而修改 compute 写库 schema（除非证明“契约无法实现”且有回滚脚本）。
- 不允许在健康检查/日志中输出带密码的 DSN。

