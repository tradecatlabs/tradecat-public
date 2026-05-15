# Agent Soft Decision Layer

TradeCat 的 Agent 软决策层只沉淀提示词、端点策略、研究假设格式和使用说明；除安全边界外，不把 Agent 研究逻辑过早固化为硬代码。

## 设计边界

- 软层：提示词、文档、endpoint policy、Agent trade thesis JSON。
- 硬层：schema/version、context-audit、public/read-only allowlist、签名/凭证/账户/订单拒绝、paper ledger、paper account state、风控拒绝、报告与 replay。
- 运行模式：只允许 public/read-only + paper/watch。
- 禁止：Binance key/secret、签名请求、真实账户/余额/仓位/订单读取、真实下单/撤单/改单。

## 自包含资源

- `scripts/project/resources/agent_soft_layer/README.md`
- `scripts/project/resources/agent_soft_layer/endpoint_policy.json`
- `scripts/project/resources/agent_soft_layer/prompts/system.zh.md`
- `scripts/project/resources/agent_soft_layer/prompts/context-request.zh.md`
- `scripts/project/resources/agent_soft_layer/prompts/trade-thesis.zh.md`

这些资源从仓库内已复制的 Binance skill/API 快照提炼，不依赖外部私有目录；上游快照 provenance 仍由 `scripts/project/resources/agent_market_context/binance/provenance.manifest.json` 管理。

## Agent 最小流程

1. 读取 `bash scripts/run-tradecat.sh auto soft-layer --json`，获得系统提示词、context 采集模板、trade thesis 模板和 endpoint policy。
2. 只用 `endpoint_policy.allowed_market_context_families` 中的 public/read-only GET 端点采集行情上下文。
3. 输出 `tradecat_auto.agent_market_context.v1` 到本地 JSON 文件。
4. 运行 `bash scripts/run-tradecat.sh auto context-audit --input <context.json> --json`。
5. 只有 audit `ok=true` 时，才运行 `bash scripts/run-tradecat.sh auto run-context --input <context.json> --mode paper --notional-usdt 12 --json`。
6. 如需账户上下文，只使用 `paper-report` 中的 `paper_account_state`，它来自本地 paper ledger，不来自 Binance。
7. 生成 `tradecat_auto.agent_trade_thesis.v1` 时，只写研究假设、风险备注、观察条件和 paper intent；不要写真实交易指令。

## 硬代码必须兜住的内容

以下内容不能只依赖提示词，必须由代码拒绝或派生：

- signed/account/order/leverage/margin/listenKey 等真实交易或账户端点；
- API key、secret、signature、listen_key、private_key 等凭证类字段；
- account_state、balance、positionRisk、open_orders、exchange_order_id、user_trades 等真实账户/订单状态；
- paper account state，只能从本地 `tradecat_auto.paper_ledger.v1` 派生为 `tradecat_auto.paper_account_state.v1`；
- 所有 paper order 必须标记为 `tradecat_auto.paper_order.v1`、`real_order=false`、`exchange_order_id=null`。

## 契约

- 软层 bundle：`tradecat_auto.agent_soft_layer.v1`
- Agent 市场上下文输入：`tradecat_auto.agent_market_context.v1`
- 市场上下文审计输出：`tradecat_auto.agent_market_context_audit.v1`
- 本地纸面账户状态：`tradecat_auto.paper_account_state.v1`
- Agent 研究假设输出：`tradecat_auto.agent_trade_thesis.v1`

对应 JSON Schema 位于 `scripts/project/contracts/`。
