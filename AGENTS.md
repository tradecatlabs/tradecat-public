# tradecat-public Agent 操作手册

本文件作用域：`tradecat-public/**`。本仓库是正常 Python 项目根，同时内嵌 Hermes/Codex Skill 包 `skills/tradecat-public/`。

## 使命

TradeCat Public 的当前使命是：Agent 交易员同步公开在线表格作为信号源，自主补齐 Binance public/read-only market context，生成 thesis，再由 TradeCat 执行 schema 审计、paper/watch、账本、风控拒绝、报告和可复现审计。

旧本地 TUI、安装器、watchdog、缓存浏览器和用户侧终端产品线已退役；不要恢复为默认产品形态。

## 禁区

- 禁止连接或写入 TradeCat 服务端 PostgreSQL。
- 禁止依赖内部 `apps/sheets` 实现细节；只能依赖公开在线表格 CSV 契约。
- 禁止提交缓存、运行日志、账本、Google key、Binance key、secret、`.env`、私钥、真实账户输出或真实订单日志。
- `tradecat_auto` 只能执行 public-readonly + paper/watch；不得调用真实下单、撤单、改杠杆、改保证金或签名账户接口。
- 缺 Agent sizing/leverage/exits 时必须 fail-closed；不得硬编码默认仓位、默认杠杆、默认止损止盈或默认持仓时长。

## 目录结构

```text
tradecat-public/
|-- README.md                  # 根项目说明、运行、开发入口
|-- AGENTS.md                  # 本文件，根项目与 Skill 包边界
|-- pyproject.toml             # Python 项目元数据
|-- constraints.txt            # 依赖约束
|-- contracts/                 # JSON Schema 机器契约
|-- resources/                 # Binance 快照、Agent soft layer 等公开自包含资源
|-- scripts/                   # request、paper runtime、监控、验证脚本
|-- src/
|   |-- tradecat_sources/      # 公开在线表格信号源与 dataset contract
|   `-- tradecat_auto/         # Agent context 审计、paper/watch、ledger、风控、报告
|-- tests/                     # 项目测试
`-- skills/
    `-- tradecat-public/
        |-- SKILL.md           # Hermes/Codex Skill 激活说明
        |-- agents/
        |   |-- manifest.json  # 唯一机器主契约
        |   |-- hermes.yaml
        |   `-- openai.yaml
        |-- references/        # Skill 长文档
        `-- scripts/           # 从 Skill 包跳回根项目的薄 wrapper
```

## 边界

- 根目录是唯一 Python 项目根；源码、测试、contracts、resources、运行脚本和任务包都在根项目内。
- `skills/tradecat-public/` 是唯一 Skill 包根；不得在仓库根重新创建 `SKILL.md`、`agents/` 或 `references/`。
- `skills/tradecat-public/agents/manifest.json` 是 Agent/Hermes 机器主契约；文档只能解释它。
- `scripts/request.py` 是公开在线表格读取入口；`src/tradecat_sources/` 只做信号源适配，不恢复 TUI 或本地缓存产品。
- `project/` 已退役，禁止重新作为项目根进入公开仓库。
- `tasks/` 只属于本地任务拆解/草稿，禁止进入 GitHub 公开仓库。
- `.runtime/`、`.tradecat/`、`.venv/`、`.hermes/`、`.tools/`、`project/`、`tasks/` 只属于本机运行态或开发态，必须保持 ignored。

## 主要数据流

```text
公开在线表格 CSV
-> scripts/request.py / tradecat_sources.registry
-> Agent/Hermes 生成 agent_market_context + agent_trade_thesis
-> context-audit / run-context
-> deterministic risk gate
-> paper_broker / paper_ledger
-> .runtime/auto-paper JSONL archive + SQLite audit journal
-> health/daily/alert/replay 报告
```

Binance 资源只作为 public/read-only market context 参考和 Agent 输入 provenance；TradeCat 不读取 key、不签名、不访问真实账户/订单、不真实下单。

## 验证

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

架构、目录、入口、数据流或控制流变化时，必须同步更新本文件、根 README、`skills/tradecat-public/SKILL.md`、`skills/tradecat-public/agents/manifest.json` 和相关 references。
