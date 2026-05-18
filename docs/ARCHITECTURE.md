# Architecture

TradeCat Public 是一个仓库根 Python 项目，内嵌 `skills/tradecat-public/` Hermes/Codex Skill 包。根项目承载实现，Skill 包承载 Agent/Hermes 使用契约。

## 分层

```text
tradecat-public/
|-- src/tradecat_sources/       # 公开在线表格信号源适配
|-- src/tradecat_auto/          # Agent context 审计、paper/watch、ledger、风控、报告
|-- contracts/                  # JSON Schema 机器契约
|-- resources/                  # Binance public-readonly 快照与 Agent soft layer
|-- scripts/                    # CLI、runtime、监控、验证入口
|-- tests/                      # pytest 回归测试
|-- skills/tradecat-public/     # Skill 激活、manifest、Agent profiles、references
`-- docs/                       # 人类协作和治理入口
```

## 数据流

```text
公开在线表格 signal_flow / anomaly_panel
-> Agent/Hermes public-readonly market research
-> agent_market_context.v1 + agent_trade_thesis.v1
-> context-audit
-> paper/watch run-context 或 run-loop
-> paper ledger + cycle archive + audit journal
-> latest-cycle / latest-decision / health / daily / alert / replay reports
```

## 机器契约

`skills/tradecat-public/agents/manifest.json` 是 Agent/Hermes 的唯一机器主契约。`contracts/` 下的 JSON Schema 是 I/O 校验契约。文档只能解释这些契约，不复制第二份机器真相。

## 安全边界

- 只允许 public/read-only market data 与本地 paper/watch。
- 禁止 Binance key/secret/listen key。
- 禁止签名请求。
- 禁止账户、订单、杠杆、保证金私有端点。
- 禁止真实下单。
- 缺 Agent sizing/leverage/exits 时必须 fail-closed。
- 运行态只能写入 ignored `.runtime/`、`.tradecat/`、`.venv/`、`.hermes/`、`.tools/`。

## 退役边界

旧 TUI、安装器、watchdog、本地缓存浏览器和 `project/` 根已退役。不要把它们作为兼容层恢复。
