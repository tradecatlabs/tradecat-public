# 0011 - tg-cards-sheets-dashboard

把 telegram-service 现有 TG 前端“卡片消息”同步到 Google Sheets（公开只读）：
- `看板`（默认 `replace`）：**按 card_type 固定槽位覆盖写** 的卡片块（固定列宽 + 固定槽位 y），避免“持续向下堆叠”。
  - `卡片索引 + EAV + 大字段索引`：全字段无遗漏的事实留存（可筛选/可审计/可重放）。

## In Scope

- **协议**：定义 `CardEvent(schema_version=1)`（卡片级字段 + 表格明细 + raw 引用），以及幂等键 `card_key` 规则。
- **写入通道（默认 B）**：Service Account + Sheets API（纯 CLI，写入前提：目标工作簿已分享给 SA 邮箱为编辑）。
- **写入通道（可选 A）**：Apps Script Webhook（`doPost()`）提供 HTTP 写入能力（HMAC 鉴权 + 幂等 + 锁 + 批量写入），适合“用个人账号写入 + Drive blob 不受 SA 配额限制”的场景。
- **新服务**：新增消费层服务 `services/consumption/sheets-service`，负责从本地数据生成 CardEvent 并写入在线表格。
- **事实表**：在 Google Sheets 工作簿内落 `cards_index / card_fields_eav / card_rows / row_fields_eav / blobs_index / meta`。
- **展示表**：将卡片渲染到 `看板`（固定列区间 + 标准版式 + y 指针推进）。
- **多周期横向（7 周期）**：对存在 `<prefix>_period` 的排行榜卡片，导出为 `排名/币种 + 1m..1w` 横向列（默认启用）。
- **可靠性**：sheets-service 侧 outbox（JSONL + checkpoint，旁路、可补写）+ 重试退避 + 幂等去重。
- **可重建**：提供重放机制：从事实表重建 `看板`（可运维执行）。
- **可观测**：写入延迟、成功率、重试次数、outbox backlog、Webhook 耗时/锁等待。

## Out of Scope

- 不把逐笔/订单簿等高频明细灌入 Sheets 主仓。
- 不修改数据库 schema（PG/SQLite）与既有采集/计算链路。
- 不重构现有 TG 卡片业务逻辑（仅做“复用渲染/旁路导出/同步”）。
- 不修改 `config/.env` 生产配置文件（只读约束保持）。

## 阅读与执行顺序（必须严格遵守）

1. `CONTEXT.md`：锁定现状证据、约束与风险
2. `PLAN.md`：确认技术选型、数据流与回滚协议
3. `ACCEPTANCE.md`：锁定验收口径
4. `TODO.md`：逐项执行（每步必须跑 Verify）
5. `STATUS.md`：记录证据与状态迁移
