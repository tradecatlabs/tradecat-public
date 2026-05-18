# TradeCat Public

TradeCat Public 是一个面向 Agent/Hermes 的自主纸面交易运行时。公开在线表格只作为信号源；Agent/Hermes 根据仓库内自包含的 Binance skill/API 快照和公开只读工具补齐行情上下文与交易 thesis；TradeCat 负责 schema 审计、信号对齐、paper/watch 执行、账本、风控拒绝、报告和可复现审计。

本仓库不再维护本地交互式 TUI、安装器或用户侧缓存浏览器产品线。核心目标是一句话：Agent 交易员同步在线表格作为信号源的自主纸面交易系统。

## 安全边界

- 只允许 public/read-only market data 与本地 paper/watch。
- 禁止读取 Binance key/secret、`.env`、listen key、账户、余额、真实持仓或订单。
- 禁止签名请求，禁止调用下单、撤单、改杠杆、改保证金等私有端点。
- 禁止真实下单；实盘 executor 必须是未来独立私有仓库。
- 本地运行态只能写入 ignored `.runtime/`、`.tradecat/`、`.venv/`、`.tools/`、`.hermes/`。
- 交易 sizing、leverage、止损、止盈、持仓时长必须由 Agent thesis 显式给出；TradeCat 不发明默认仓位或默认 exits。

## 目录

```text
tradecat-public/
|-- README.md
|-- AGENTS.md
|-- pyproject.toml
|-- constraints.txt
|-- contracts/                 # JSON Schema 机器契约
|-- resources/
|   |-- agent_market_context/  # Binance skill/API 只读快照与 provenance
|   `-- agent_soft_layer/      # Agent 角色与软策略资源
|-- scripts/                   # request、paper runtime、验证、监控薄入口
|-- src/
|   |-- tradecat_sources/      # 在线表格公开信号源读取与 dataset contract
|   `-- tradecat_auto/         # Agent context、paper/watch、ledger、风控、报告
|-- tests/
`-- skills/tradecat-public/    # Hermes/Codex Skill 包
```

`skills/tradecat-public/agents/manifest.json` 是 Agent/Hermes 的唯一机器主契约。文档只解释它，不复制第二份机器契约。

`project/` 已退役；`tasks/` 是本地任务拆解/草稿目录，和 `.runtime/` 一样不进入公开 GitHub 仓库。

## 快速开始

```bash
python3 -m pip install -c constraints.txt -e ".[dev]"
python3 scripts/request.py --datasets --format json
python3 scripts/request.py signal_flow --format json --limit 5
python3 scripts/request.py anomaly_panel --format json --limit 0
bash scripts/run-tradecat.sh soft-layer --json
bash scripts/start-auto-paper.sh status --json
```

读取在线表格信号时如需代理，使用标准环境变量即可，例如：

```bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
```

## Agent 纸面交易流

```text
signal_flow / anomaly_panel
-> Agent/Hermes 读取 Binance public/read-only K线、盘口、资金费率、OI 等上下文
-> agent_market_context.v1 + agent_trade_thesis.v1
-> context-audit
-> run-context / run-loop
-> paper risk gate
-> paper ledger + cycle archive + audit journal
-> health / daily / alert / replay report
```

常用命令：

```bash
bash scripts/run-tradecat.sh context-audit --input context.json --json
bash scripts/run-tradecat.sh run-context --input context.json --mode paper --json
bash scripts/run-tradecat.sh paper-report --json
bash scripts/run-tradecat.sh audit-journal --json
bash scripts/run-tradecat.sh health-report --json
bash scripts/run-tradecat.sh daily-report --json
```

Agent thesis 单独作为文件输入时：

```bash
bash scripts/run-tradecat.sh run-once \
  --agent-trade-thesis-path thesis.json \
  --mode paper \
  --json
```

缺少 Agent sizing/exits 时，TradeCat 必须 fail-closed，并返回结构化 `error_code`，不得自动填金额、杠杆、止损或止盈。

## 常驻 paper/watch

```bash
bash scripts/start-auto-paper.sh ops-check --json
bash scripts/start-auto-paper.sh start --json
bash scripts/start-auto-paper.sh status --json
bash scripts/start-auto-paper.sh stop --json
```

本地 Web 监控页面：

```bash
python3 scripts/serve-auto-paper-monitor.py --host 127.0.0.1 --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`。页面只展示本地 paper/watch、审计日志、账本、输入信号和依赖链健康，不接触真实账户。

## 验证

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

定向开发时可先跑：

```bash
PYTHONPATH=src python3 -m pytest tests/test_pipeline.py tests/test_service.py tests/test_paper_ledger.py
PYTHONPATH=src ruff check src tests
```

## 退役说明

旧的本地 TUI、安装器、watchdog、本地缓存浏览器、分析 facts bundle 已退役。保留的输入面是 `scripts/request.py` 和 `src/tradecat_sources/`，输出面是 `src/tradecat_auto/` 的 JSON contract 与 paper/watch runtime。
