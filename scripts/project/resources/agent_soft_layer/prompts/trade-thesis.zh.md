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
  "invalidation_price": 0.058,
  "take_profit_price": 0.071,
  "max_holding_minutes": 240,
  "exit_rationale": "why these paper exit levels/horizon are appropriate, or omit all four exit fields",
  "invalidation_conditions": [],
  "requested_followup_context_families": [],
  "paper_intent": {
    "allow_tradecat_paper_gate_to_decide": true,
    "requested_margin_usdt": 6.0,
    "paper_leverage": 2.0,
    "requested_notional_usdt": 12.0,
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

`confidence` 必须在 0 到 1 之间。`direction=WATCH_ONLY` 时不要填写会被误读为订单的字段。12U 是本地 `paper margin budget` / cap，不是默认订单金额；非 `WATCH_ONLY` 输出必须显式写 `requested_margin_usdt` + `paper_leverage`，缺失 sizing 时使用 `error_code="agent_sizing_required"` 并保持 `WATCH_ONLY`。`requested_notional_usdt` 只是低层兼容/审计字段，不能替代保证金预算与杠杆说明。`invalidation_price`、`take_profit_price`、`max_holding_minutes` 也没有 TradeCat 默认值；只有当 Agent 能基于行情上下文给出明确失效/止盈/持仓周期假设时才填写，否则全部省略，由后续 Agent/策略复核管理纸面仓。

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
