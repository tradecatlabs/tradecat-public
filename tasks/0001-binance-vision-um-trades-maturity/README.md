# 0001 - binance-vision-um-trades-maturity

将 Binance Vision UM trades 升级到“业内成熟可运营”：可审计、可修复、可扩展、成本可控。

## In Scope

- **完整性**：为 Vision ZIP 引入 `.CHECKSUM/sha256` 强校验（失败可重试、可记录、可追溯）。
- **审计**：回填链路写入 `storage.files / storage.file_revisions / storage.import_batches / storage.import_errors`。
- **治理闭环**：新增 `repair` 流程消费 `crypto.ingest_gaps`，自动补齐并关闭缺口。
- **成熟升级（v2）**：引入 `core.venue/core.instrument/core.symbol_map`，落地 `raw_futures_um_trades_v2(venue_id,instrument_id,...)`，并提供兼容查询（view）。
- **测试**：新增/补齐单测覆盖 checksum 解析、file_revision 触发、repair 计划生成等关键路径。
- **文档**：把关键决策、风险与回滚协议固化（本任务目录内即为真相源）。

## Out of Scope

- 不修改 `config/.env`（生产配置只读）。
- 不引入除 `ccxt/ccxtpro` 之外的交易所 SDK（实时侧仍以 `ccxtpro` WS 为主）。
- 不创建/写入派生层 `aggTrades/klines/*Klines`（原子层先稳）。
- 不强制替换现有 `crypto.raw_futures_um_trades`（v1 仍保留；v2 通过开关/双写/迁移逐步切换）。
- 不做跨市场（美股/A股/外汇等）统一落地（仅做 core/storage 维度锚点的使用）。

## 阅读与执行顺序（必须严格遵守）

1. `CONTEXT.md`：锁定现状证据、约束与风险
2. `PLAN.md`：确认技术选型与回滚协议
3. `ACCEPTANCE.md`：锁定验收口径（不要边做边改标准）
4. `TODO.md`：逐项执行（每步必须跑 Verify）
5. `STATUS.md`：记录证据与状态迁移
