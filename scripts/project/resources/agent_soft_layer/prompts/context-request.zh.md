# Agent-supplied Market Context 采集提示词模板

输入占位符：

- `{{symbol}}`：标准 USDⓈ-M 永续合约 symbol，例如 `BTCUSDT`。
- `{{source_event_json}}`：TradeCat 表格事件或异动行。
- `{{endpoint_policy_json}}`：`scripts/project/resources/agent_soft_layer/endpoint_policy.json`。
- `{{source_manifest_path}}`：`scripts/project/resources/agent_market_context/binance/provenance.manifest.json`。

## 指令

请只使用 `endpoint_policy_json.allowed_market_context_families` 中列出的 public/read-only GET 端点，为 `{{symbol}}` 采集与 `{{source_event_json}}` 对齐的市场上下文。优先顺序：

1. `24h_ticker` 与 `book_ticker`：确认最新价格、24h 变化、成交额和 bid/ask。
2. `klines`：至少覆盖事件前后短周期 K 线，便于对齐异动时间。
3. `order_book_depth`：评估 spread、浅层流动性和盘口倾斜。
4. `open_interest` / `open_interest_history`：识别价格变化是否伴随 OI 变化。
5. `funding_rate` / `premium_index`：标注资金费率、mark/index 偏离和拥挤风险。
6. `long_short_ratios` / `taker_buy_sell_volume`：补充公开多空比和主动买卖量。

## 输出 JSON

输出一个本地文件内容，schema 必须为：

```json
{
  "schema": "tradecat_auto.agent_market_context.v1",
  "schema_version": "1.0.0",
  "symbol": "{{symbol}}",
  "generated_at": "<UTC ISO8601>",
  "mode": "public_readonly",
  "provenance": {
    "agent": "hermes",
    "source_manifest": "{{source_manifest_path}}",
    "notes": "public/read-only Binance context gathered from self-contained TradeCat resource policy"
  },
  "source_event": {{source_event_json}},
  "market_data": []
}
```

每个 `market_data[]` 必须包含：`family`、`endpoint`、`method="GET"`、`ok`、`fetched_at`、`requires_signature=false`、`signed=false`、`provenance`、`data` 或 `error`。

## 禁止

不要调用或引用 account、balance、positionRisk、userTrades、order、openOrders、allOrders、batchOrders、leverage、marginType、listenKey。不要读取环境变量、`.env`、API key、secret。不要把 Binance 真实账户、真实仓位、真实订单或真实成交放入 context。

## 下一步

生成文件后必须先运行：

```bash
bash scripts/run-tradecat.sh auto context-audit --input <context.json> --json
```

只有 audit `ok=true` 才能进入：

```bash
bash scripts/run-tradecat.sh auto run-context --input <context.json> --mode paper --notional-usdt 12 --json
```
