# TradeCat Agent Trade Thesis 提示词模板

输入占位符：

- `{{audited_market_context_json}}`：已通过 `context-audit` 的 `tradecat_auto.agent_market_context.v1`。
- `{{paper_account_state_json}}`：TradeCat 本地 `tradecat_auto.paper_account_state.v1`，只能来自 paper ledger。
- `{{run_context_report_json}}`：可选，TradeCat `auto run-context` 的 paper/watch 报告。

## 指令

请基于已审计的公开行情 context、TradeCat 表格信号和本地 paper account state，生成一个纸面研究假设。你可以提出方向、观察条件、失效条件、风险备注、是否建议 paper/watch 继续观察；但不能输出真实交易动作，不能引用真实 Binance 账户/订单状态。

## 输出 JSON schema

```json
{
  "schema": "tradecat_auto.agent_trade_thesis.v1",
  "schema_version": "1.0.0",
  "ok": true,
  "symbol": "<SYMBOL>",
  "mode": "paper_research",
  "direction": "LONG | SHORT | WATCH_ONLY",
  "confidence": 0.0,
  "holding_horizon": "intraday | multi_day | unknown",
  "entry_context": {
    "reference_price": 0.0,
    "price_source": "agent_market_context | run_context_report",
    "not_order_instruction": true
  },
  "risk_notes": [],
  "invalidation_conditions": [],
  "requested_followup_context_families": [],
  "paper_intent": {
    "allow_tradecat_paper_gate_to_decide": true,
    "requested_notional_usdt": 0.0,
    "real_order": false
  },
  "rationale": "short auditable rationale without hidden chain-of-thought",
  "provenance": {
    "market_context_schema": "tradecat_auto.agent_market_context.v1",
    "paper_account_state_schema": "tradecat_auto.paper_account_state.v1"
  },
  "limitations": [
    "paper/watch research only",
    "no Binance keys, no signed requests, no real account reads, no real orders"
  ]
}
```

`confidence` 必须在 0 到 1 之间。`direction=WATCH_ONLY` 时不要填写会被误读为订单的字段。`requested_notional_usdt` 只是给 TradeCat deterministic risk gate 的 paper 参数建议，不是订单金额。

## 拒绝条件

如果输入里出现真实账户、真实订单、API key、签名端点或未通过 audit 的 market context，输出：

```json
{
  "schema": "tradecat_auto.agent_trade_thesis.v1",
  "schema_version": "1.0.0",
  "ok": false,
  "symbol": "<SYMBOL_OR_EMPTY>",
  "mode": "paper_research",
  "direction": "WATCH_ONLY",
  "confidence": 0.0,
  "error_code": "unsafe_or_unaudited_input",
  "rationale": "拒绝原因",
  "limitations": ["paper/watch research only"]
}
```
