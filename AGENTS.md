# tradecat-public Agent 操作手册

本文件作用域：`tradecat-public/**`。本仓现在是正常 Python 项目根，同时内嵌一个 Hermes/Codex Skill 包：`skills/tradecat-public/`。

## 使命

TradeCat 根项目提供公开在线表格消费、本地快照缓存、CLI/TUI、Agent 观察/事实包、Agent-supplied Binance public/read-only market context 审计、paper/watch、ledger、replay/backtest、报告和本地运维脚本。`skills/tradecat-public/` 只负责 Skill 激活、Agent manifest、平台 profile 和长文档索引。

## 禁区

- 禁止连接或写入 TradeCat 服务端 PostgreSQL。
- 禁止把该服务接入服务端数据生产链路。
- 禁止依赖 `apps/sheets` 内部实现细节；只能依赖公开在线表格 CSV 契约。
- 禁止把缓存文件、凭证、Google key、私密 `.env` 写入仓库。
- 禁止提交 Binance API key、secret、`.env`、私钥、真实账户输出、真实订单日志或任何可复用凭证。
- `tradecat_auto` 只能执行 public-readonly + watch/paper；不得调用真实下单、撤单、改杠杆或签名账户接口。

## 目录结构

```text
tradecat-public/
|-- README.md                  # 根项目说明、安装、运行、开发入口
|-- AGENTS.md                  # 本文件，根项目与 Skill 包边界
|-- pyproject.toml             # Python 项目元数据
|-- constraints.txt            # 依赖约束
|-- install.sh / install.ps1   # 用户安装入口
|-- uninstall.sh / uninstall.ps1
|-- contracts/                 # JSON Schema 机器契约
|-- resources/                 # 自包含公开参考资源与 Agent soft layer
|-- scripts/                   # 根项目脚本、验证、运维和 thin wrappers
|-- src/
|   |-- tradecat_terminal/     # 公开表格、缓存、CLI/TUI、分析事实包
|   `-- tradecat_auto/         # Agent context 审计、paper/watch、ledger、风控、报告
|-- tests/                     # 项目测试
|-- tasks/                     # 任务治理资产
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

- 根目录是唯一 Python 项目根；源码、测试、contracts、resources、install/uninstall、运行脚本和任务包都在根项目内。
- `skills/tradecat-public/` 是唯一 Skill 包根；不得在仓库根重新创建 `SKILL.md`、`agents/` 或 `references/` 形成第二真相源。
- `skills/tradecat-public/agents/manifest.json` 是 Agent/Hermes 机器主契约；文档只解释它，不复制第二份机器契约。
- `scripts/` 是根项目脚本入口；`skills/tradecat-public/scripts/` 只能是薄 wrapper。
- `.runtime/`、`.tradecat/`、`.venv/`、`.hermes/`、`.tools/` 只属于本机运行态或开发态，必须保持 ignored。

## 主要数据流

```text
公开在线表格 CSV
-> scripts/request.py / tradecat_terminal.registry
-> .tradecat/cache 本地快照
-> CLI/TUI / analysis_report / feature_bundle
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
