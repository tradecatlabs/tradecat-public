# TradeCat Public

TradeCat Public 是一个面向 Agent/Hermes 的自主纸面交易运行时。公开在线表格只作为信号源；Agent/Hermes 根据仓库内自包含的 Binance skill/API 快照和公开只读工具补齐行情上下文与交易 thesis；TradeCat 负责 schema 审计、信号对齐、paper/watch 执行、账本、风控拒绝、报告和可复现审计。

本仓库的核心目标是：Agent 交易员同步在线表格作为信号源的自主纸面交易系统。旧的本地交互式 TUI、安装器、watchdog、缓存浏览器和 `project/` 根目录已经退役。

## 功能特性

- 读取公开在线表格 `signal_flow` 和 `anomaly_panel`，不依赖私有 TradeCat 服务端。
- 使用 `contracts/` 中的 JSON Schema 约束 Agent market context、trade thesis、paper report、audit journal 等 I/O。
- 保留 Binance public-readonly skill/API 快照与 provenance，供 Agent/Hermes 研究行情上下文。
- 执行本地 paper/watch，不读取 Binance key，不签名，不访问账户/订单私有端点，不真实下单。
- 缺少 Agent 明确 sizing、leverage、stop loss、take profit 或 max holding plan 时 fail-closed。
- 运行态隔离在 ignored `.runtime/`，可生成 paper ledger、cycle archive、SQLite audit journal、health/daily/replay/alert 报告。
- 内嵌 `skills/tradecat-public/`，Agent/Hermes 可按 manifest 和 Skill references 使用本仓库。

## 安全边界

- 只允许 public/read-only market data 与本地 paper/watch。
- 禁止读取 Binance key/secret、`.env`、listen key、账户、余额、真实持仓或订单。
- 禁止签名请求，禁止调用下单、撤单、改杠杆、改保证金等私有端点。
- 禁止真实下单；实盘 executor 必须是未来独立私有仓库。
- 本地运行态只能写入 ignored `.runtime/`、`.tradecat/`、`.venv/`、`.tools/`、`.hermes/`。
- 交易 sizing、leverage、止损、止盈、持仓时长必须来自 Agent thesis 或 ignored runtime paper autonomy profile；TradeCat 不写入真实交易参数。

## 快速开始

环境要求来自 `pyproject.toml` 和 CI：

- Python `>=3.12`；CI 覆盖 Python `3.12` 和 `3.13`。
- `pip`。
- 可选：`make`、Docker 或本地 `gitleaks`，用于部分开发入口或安全扫描加速。

安装开发依赖：

```bash
python3 -m pip install -c constraints.txt -e ".[dev]"
```

最短只读检查：

```bash
python3 scripts/request.py --datasets --format json
python3 scripts/request.py signal_flow --format json --limit 5
python3 scripts/request.py anomaly_panel --format json --limit 0
bash scripts/run-tradecat.sh soft-layer --json
bash scripts/start-auto-paper.sh status --json
```

如需代理读取公开在线表格，使用标准环境变量：

```bash
export HTTPS_PROXY=http://127.0.0.1:7890
export HTTP_PROXY=http://127.0.0.1:7890
```

## 目录结构

```text
tradecat-public/
|-- README.md
|-- AGENTS.md
|-- CONTRIBUTING.md
|-- CHANGELOG.md
|-- LICENSE
|-- pyproject.toml
|-- constraints.txt
|-- Makefile
|-- .env.example
|-- .github/
|   |-- CODEOWNERS
|   |-- dependabot.yml
|   |-- pull_request_template.md
|   `-- workflows/ci.yml
|-- contracts/                 # JSON Schema 机器契约
|-- docs/                      # 架构、配置、部署、发布说明
|-- resources/
|   |-- agent_market_context/  # Binance skill/API 只读快照与 provenance
|   `-- agent_soft_layer/      # Agent 角色与软策略资源
|-- scripts/                   # request、paper runtime、验证、监控入口
|-- src/
|   |-- tradecat_sources/      # 在线表格公开信号源读取与 dataset contract
|   `-- tradecat_auto/         # Agent context、paper/watch、ledger、风控、报告
|-- tests/
`-- skills/tradecat-public/    # Hermes/Codex Skill 包
```

`skills/tradecat-public/agents/manifest.json` 是 Agent/Hermes 的唯一机器主契约。文档只解释它，不复制第二份机器契约。

`project/` 已退役；`tasks/` 是本地任务拆解/草稿目录，和 `.runtime/` 一样不进入公开 GitHub 仓库。

## 配置说明

配置示例见 `.env.example`。允许的本地配置：

```text
HTTP_PROXY=
HTTPS_PROXY=
NO_PROXY=127.0.0.1,localhost
TRADECAT_AUTO_PAPER_RUNTIME_DIR=.runtime/auto-paper
TRADECAT_AUTO_PAPER_CYCLE_TIMEOUT_SECONDS=6000
TRADECAT_AUTO_PAPER_FEE_BPS=4
TRADECAT_AUTO_PAPER_SLIPPAGE_BPS=0
TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH=
TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED=1
TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH=
TRADECAT_AUTO_PAPER_AUTONOMY_MARGIN_USDT=10
TRADECAT_AUTO_PAPER_AUTONOMY_LEVERAGE=1
TRADECAT_AUTO_PAPER_AUTONOMY_STOP_LOSS_BPS=150
TRADECAT_AUTO_PAPER_AUTONOMY_TAKE_PROFIT_BPS=300
TRADECAT_AUTO_PAPER_AUTONOMY_MAX_HOLDING_MINUTES=90
TRADECAT_AUTO_PAPER_AUTONOMY_DIRECTION_POLICY=sheet_signal_or_taker_flow
TRADECAT_AUTO_PAPER_MONITOR_HOST=127.0.0.1
TRADECAT_AUTO_PAPER_MONITOR_PORT=8765
```

默认本地 Web 监控地址来自 `scripts/serve-auto-paper-monitor.py`：`http://127.0.0.1:8765/`。

`start-auto-paper.sh` 默认会在 ignored `.runtime/auto-paper/paper_autonomy_profile.json`
生成 paper-only 自治 profile，并把它注入常驻 run-loop，让 Agent/AI 纸面交易不再卡在
`agent_sizing_required`。显式 `TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH` 仍优先；要恢复
严格等待外部 thesis 的模式，设置 `TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED=0`。

纸面成本模型默认使用 Binance USDⓈ-M 官方 commission-rate 文档示例中的 taker 费率 `4 bps`
作为 public fallback；实际开仓滑点优先用公开 `/fapi/v1/depth` 盘口按 Agent notional
估算成交均价。精确账户/VIP/symbol 费率需要签名 `USER_DATA`，不属于本公开仓库边界。

TODO: GitHub 仓库 Settings 中的 `main` 分支保护、必需 review 和必需 status checks 无法从仓库文件确认；需要仓库管理员在 GitHub UI/API 中核查。

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

常用 paper/watch 命令：

```bash
bash scripts/run-tradecat.sh context-audit --input context.json --json
bash scripts/run-tradecat.sh run-context --input context.json --mode paper --json
bash scripts/run-tradecat.sh run-once --agent-trade-thesis-path thesis.json --mode paper --json
bash scripts/run-tradecat.sh paper-report --json
bash scripts/run-tradecat.sh latest-cycle --json
bash scripts/run-tradecat.sh latest-decision --json
bash scripts/run-tradecat.sh audit-journal --json
bash scripts/run-tradecat.sh health-report --json
bash scripts/run-tradecat.sh daily-report --json
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

页面只展示本地 paper/watch、审计日志、账本、输入信号、Agent decision text 和依赖链健康，不接触真实账户。

## 常用命令

```bash
# 安装
python3 -m pip install -c constraints.txt -e ".[dev]"
make install-dev

# 只读数据源
python3 scripts/request.py --datasets --format json
python3 scripts/request.py signal_flow --format json --limit 5
python3 scripts/request.py anomaly_panel --format json --limit 0
bash scripts/binance-public-snapshot.sh --symbols BTCUSDT,ETHUSDT --json

# 测试、lint、format
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src ruff check src tests
PYTHONPATH=src ruff format --check src tests scripts

# 完整本地门禁
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
python3 scripts/validate_dependency_policy.py
git diff --check

# 构建 wheel，来源于 CI
python3 -m pip wheel . --no-deps -w /tmp/tradecat-wheel
```

`Makefile` 还提供 `make test`、`make lint`、`make format`、`make verify`、`make paper-status`、`make paper-start`、`make paper-stop`、`make monitor`。

## CI/CD

CI 文件为 `.github/workflows/ci.yml`，触发条件包括 `push`、`pull_request`、`workflow_dispatch` 和每日定时任务。CI 执行：

- Skill strict validation。
- secret scan。
- 安装 `python -m pip install -c constraints.txt -e ".[dev]"`。
- public boundary guard。
- dependency policy。
- `ruff check src tests`。
- `ruff format --check src tests scripts`。
- `PYTHONPATH=src pytest -q`。
- data contract validators。
- supply-chain audit。
- shell/Python syntax check。
- wheel package data check。
- agent readiness smoke。

本仓库没有 Dockerfile、docker-compose、K8s manifest 或 Helm chart；当前部署形态只有本地 public-readonly + paper/watch。TODO: 如未来新增容器或平台部署，需要同步更新 `docs/deployment.md`、README 和 AGENTS。

## Troubleshooting / FAQ

- `ModuleNotFoundError: tradecat_auto`：先安装 `python3 -m pip install -c constraints.txt -e ".[dev]"`，或运行命令时设置 `PYTHONPATH=src`。
- `ruff` 或 `pytest` 不存在：运行 `bash scripts/bootstrap-dev.sh` 或安装开发依赖。
- 在线表格读取失败或 HTTP 404：先运行 `python3 scripts/request.py --datasets --format json` 确认 dataset；如网络受限，设置 `HTTP_PROXY` / `HTTPS_PROXY`。
- `paper_service_not_running`：运行 `bash scripts/start-auto-paper.sh status --json` 查看状态，需要常驻时运行 `bash scripts/start-auto-paper.sh start --json`。
- `heartbeat_stale` 但 pid 仍在：说明单轮 public-readonly/paper cycle 可能卡住；`TRADECAT_AUTO_PAPER_CYCLE_TIMEOUT_SECONDS` 会限制单轮最长时间，必要时运行 `bash scripts/start-auto-paper.sh heal --json`。
- `paper-report` 显示 0 仓但服务在交易：默认账本应为 `.runtime/auto-paper/paper_ledger.json`；用 `bash scripts/run-tradecat.sh latest-decision --json` 和 `bash scripts/run-tradecat.sh health-report --json` 核对常驻服务事实源。
- `agent_sizing_required` 在重启后出现：先看 `bash scripts/start-auto-paper.sh status --json` 的 `paper_autonomy_profile_configured`。默认应为 true；若被 `TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED=0` 关闭，则需要 Agent/Hermes 显式写入 thesis。
- 想完全改 paper 自治参数：设置 `TRADECAT_AUTO_PAPER_AUTONOMY_*`，或显式传入 `TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH` / `TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH`。
- 监控端口冲突：使用 `python3 scripts/serve-auto-paper-monitor.py --host 127.0.0.1 --port <free-port>`。

## 贡献指南

- 贡献流程：`CONTRIBUTING.md`
- 变更记录：`CHANGELOG.md`
- 架构说明：`docs/ARCHITECTURE.md`
- 配置说明：`docs/configuration.md`
- 部署与运维：`docs/deployment.md`
- 发布流程：`docs/release.md`

`.github/pull_request_template.md`、`.github/CODEOWNERS` 和 `.github/dependabot.yml` 提供 PR、review owner 与依赖更新入口。平台级分支保护需要在 GitHub 仓库设置中启用。
