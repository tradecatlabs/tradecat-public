# tradecat-public Agent 操作手册

本文件作用域：`tradecat-public/**`。它是 AI 编码/自动化 Agent 的作业说明书。执行任务时以仓库事实为准：先读代码和配置，再改文件；不确定就写 TODO，不允许猜。

## Mission & Scope

TradeCat Public 的使命是：Agent 交易员同步公开在线表格作为信号源，自主补齐 Binance public/read-only market context，生成 thesis，再由 TradeCat 执行 schema 审计、paper/watch、账本、风控拒绝、报告和可复现审计。

允许做：

- 修改 `src/tradecat_sources/` 的公开在线表格信号源适配。
- 修改 `src/tradecat_auto/` 的 Agent context 审计、paper/watch、ledger、风控、报告和本地运行态逻辑。
- 修改 `contracts/`、`resources/`、`tests/`、`scripts/`、`docs/`、`skills/tradecat-public/` 中与任务直接相关的契约、资源、测试、脚本和文档。
- 运行 public-readonly 命令、本地 paper/watch 命令和验证门禁。

禁止做：

- 禁止连接或写入 TradeCat 服务端 PostgreSQL。
- 禁止依赖内部 `apps/sheets` 实现细节；只能依赖公开在线表格 CSV 契约。
- 禁止提交缓存、运行日志、账本、Google key、Binance key、secret、`.env`、私钥、真实账户输出或真实订单日志。
- 禁止读取 Binance key/secret、listen key、账户、余额、真实持仓或订单。
- 禁止签名请求，禁止调用真实下单、撤单、改杠杆、改保证金或账户私有接口。
- 禁止恢复旧本地 TUI、安装器、watchdog、缓存浏览器和 `project/` 根目录。
- 禁止在缺 Agent sizing/leverage/exits 时硬编码默认仓位、默认杠杆、默认止损止盈或默认持仓时长。

敏感或本地路径：

- `.runtime/`、`.tradecat/`、`.venv/`、`.hermes/`、`.tools/`、`project/`、`tasks/` 只属于本机运行态或开发态，必须保持 ignored。
- `skills/tradecat-public/agents/manifest.json` 是 Agent/Hermes 机器主契约。
- TODO: GitHub 平台分支保护配置无法从仓库文件确认；需要仓库管理员核查 GitHub Settings。

## Golden Path

标准执行路径：

1. `git status --short --branch`
2. 阅读任务相关文件、`README.md`、本文件、`skills/tradecat-public/agents/manifest.json` 和相关 `contracts/`。
3. 安装或确认开发依赖：`python3 -m pip install -c constraints.txt -e ".[dev]"`
4. 先跑针对性测试或只读命令复现问题。
5. 做最小必要修改；不做顺手重构。
6. 同步测试、schema、manifest、README/AGENTS/docs/references。
7. 运行必须门禁。
8. 汇报改动、验证、剩余风险和 git 状态；未获明确要求不得 push。

## Must-Run Commands

安装：

```bash
python3 -m pip install -c constraints.txt -e ".[dev]"
```

只读入口：

```bash
python3 scripts/request.py --datasets --format json
python3 scripts/request.py signal_flow --format json --limit 5
python3 scripts/request.py anomaly_panel --format json --limit 0
bash scripts/binance-public-snapshot.sh --symbols BTCUSDT,ETHUSDT --json
bash scripts/run-tradecat.sh soft-layer --json
bash scripts/start-auto-paper.sh status --json
bash scripts/run-tradecat.sh latest-cycle --json
bash scripts/run-tradecat.sh latest-decision --json
```

测试、lint、format：

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src ruff check src tests
PYTHONPATH=src ruff format --check src tests scripts
```

完整交付门禁：

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
python3 scripts/validate_dependency_policy.py
git diff --check
```

本地 paper/watch：

```bash
bash scripts/start-auto-paper.sh ops-check --json
bash scripts/start-auto-paper.sh start --json
bash scripts/start-auto-paper.sh status --json
bash scripts/start-auto-paper.sh stop --json
```

本地 Web 监控：

```bash
python3 scripts/serve-auto-paper-monitor.py --host 127.0.0.1 --port 8765
```

## Code Change Rules

- 根目录是唯一 Python 项目根；不要创建 `scripts/project/` 或恢复 `project/`。
- `skills/tradecat-public/` 是唯一 Skill 包根；不得在仓库根创建 `SKILL.md`、`agents/` 或 `references/`。
- `scripts/request.py` 是公开在线表格读取入口；`src/tradecat_sources/` 只做信号源适配。
- `src/tradecat_auto/` 只执行 public-readonly + paper/watch。
- `contracts/` 中 schema 变化必须同步测试和 manifest/docs。
- 新依赖必须先通过 `scripts/validate_dependency_policy.py`；更新 allowlist 时写明用途。
- 任何功能、命令、配置、目录或工作流变化必须同步 README、AGENTS、相关 `docs/`、Skill references 和 manifest。
- 不做无任务要求的大范围重构、格式化或搬目录；若为了新增格式门禁必须机械格式化，需明确说明。

## Style & Quality

- Python 版本要求来自 `pyproject.toml`：`>=3.12`。
- Ruff 配置在 `pyproject.toml`：`target-version=py312`，`line-length=120`，lint 选择 `E/W/F/I/B/C4/UP`。
- CI 执行 `ruff check src tests` 和 `ruff format --check src tests scripts`。
- pytest 配置在 `pyproject.toml`：测试目录为 `tests`，文件名 `test_*.py`，函数名 `test_*`。
- 人类可见文档、注释、日志优先中文；机器结构、变量、函数、类名使用清晰英文。
- 输出 JSON contract 时保留 `schema_version`、`error_code`、`provenance`、`safety`；安全字段 `real_orders`、`signed_requests`、`reads_api_keys` 必须保持 false。

## Project Map

```text
tradecat-public/
|-- README.md                  # 人类开发者入口
|-- AGENTS.md                  # 本文件，Agent 操作手册
|-- CONTRIBUTING.md            # 分支、提交、PR、review、发布规则
|-- CHANGELOG.md               # 公开变更记录
|-- LICENSE                    # MIT 许可证文本
|-- pyproject.toml             # Python 项目元数据、依赖、ruff、pytest
|-- constraints.txt            # 依赖约束
|-- Makefile                   # 常用本地命令
|-- .env.example               # public-readonly 与本地 runtime 配置示例
|-- .github/
|   |-- CODEOWNERS
|   |-- dependabot.yml
|   |-- pull_request_template.md
|   `-- workflows/ci.yml
|-- contracts/                 # JSON Schema 机器契约
|-- docs/                      # 架构、配置、部署、发布说明
|-- resources/                 # Binance 快照、Agent soft layer 等公开资源
|-- scripts/                   # request、paper runtime、监控、验证脚本
|-- src/
|   |-- tradecat_sources/      # 公开在线表格信号源与 dataset contract
|   `-- tradecat_auto/         # Agent context 审计、paper/watch、ledger、风控、报告
|-- tests/                     # pytest 测试
`-- skills/
    `-- tradecat-public/
        |-- SKILL.md
        |-- agents/manifest.json
        |-- agents/hermes.yaml
        |-- agents/openai.yaml
        |-- references/
        `-- scripts/
```

主要数据流：

```text
公开在线表格 CSV
-> scripts/request.py / tradecat_sources.registry
-> Agent/Hermes 生成 agent_market_context + agent_trade_thesis
-> context-audit / run-context
-> deterministic risk gate
-> paper_broker / paper_ledger
-> .runtime/auto-paper JSONL archive + SQLite audit journal
-> latest-cycle/latest-decision + health/daily/alert/replay 报告
```

## Common Pitfalls

- `ModuleNotFoundError: tradecat_auto`：先安装开发依赖，或运行命令时设置 `PYTHONPATH=src`。
- `pytest` / `ruff` 不存在：运行 `bash scripts/bootstrap-dev.sh` 或安装 `python3 -m pip install -c constraints.txt -e ".[dev]"`。
- 在线表格请求失败：先跑 `python3 scripts/request.py --datasets --format json`；网络受限时设置 `HTTP_PROXY` / `HTTPS_PROXY`。
- `paper_service_not_running`：运行 `bash scripts/start-auto-paper.sh status --json`；需要常驻时运行 `bash scripts/start-auto-paper.sh start --json`。
- `heartbeat_stale` 但 pid 仍在：单轮可能卡在 public 网络或盯市；默认 `TRADECAT_AUTO_PAPER_CYCLE_TIMEOUT_SECONDS=6000`，可运行 `bash scripts/start-auto-paper.sh heal --json`。
- `paper-report` 和常驻交易不一致：默认事实源是 `.runtime/auto-paper/paper_ledger.json` 与 `.runtime/auto-paper/cycles.jsonl`；先跑 `bash scripts/run-tradecat.sh latest-decision --json`。
- `agent_sizing_required` 在重启后出现：默认不自动套用 `.runtime/auto-paper/paper_autonomy_profile.json`；确认 Agent/Hermes 已显式写入 thesis，并通过 `TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH` 或 `--agent-trade-thesis-path` 注入。
- `agent_sizing_required`：这是安全拒绝；Agent thesis 必须显式提供 sizing/leverage/exits。用户需要约束时再显式传入 paper autonomy profile 或 portfolio risk policy。
- 监控端口 `8765` 冲突：换空闲端口运行 `python3 scripts/serve-auto-paper-monitor.py --host 127.0.0.1 --port <free-port>`。

## PR / Commit Rules

- 分支和提交规则见 `CONTRIBUTING.md`。
- 推荐 Conventional Commits：`feat:`、`fix:`、`docs:`、`refactor:`、`test:`、`chore:`、`ci:`、`perf:`。
- PR 模板在 `.github/pull_request_template.md`。
- Review owner 在 `.github/CODEOWNERS`。
- CI 触发来自 `.github/workflows/ci.yml`：`push`、`pull_request`、`workflow_dispatch`、每日定时任务。
- 不要直接 push 到远端，除非用户明确要求。
- TODO: GitHub 平台是否已强制 CODEOWNERS review、branch protection、required checks，需要仓库管理员确认。

## Documentation Sync Rule

任何架构、目录、入口、数据流、控制流、命令、配置、依赖、schema、CI、Skill contract 或协作治理变化，必须同步更新：

- `README.md`
- `AGENTS.md`
- `CONTRIBUTING.md`
- `CHANGELOG.md`
- 相关 `docs/`
- `skills/tradecat-public/SKILL.md`
- `skills/tradecat-public/agents/manifest.json`
- 相关 `skills/tradecat-public/references/`
- 对应测试或 guard

不确定则写 `TODO:` 并指出需要哪个文件、路径、字段或命令输出才能确认；严禁编造。
