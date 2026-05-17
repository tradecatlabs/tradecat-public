# Skill Package Governance

`tradecat-public` 的长期形态是一个 Hermes Skill/Agent 配置包。Agent/Hermes 拿到仓库根目录这一整个包后，应先读取 `SKILL.md`，再把 `agents/manifest.json` 当作唯一机器主契约；其他文档只解释和索引它，不另建第二份真实契约。

## 分层边界

- Skill 根目录：只承载 Skill 激活、Agent profile、长文档、治理说明、根级薄脚本和 Git/CI 元数据。
- 内部项目根：`project/` 是唯一 Python 项目根，承载源码、测试、contracts、resources、安装/卸载脚本、项目脚本和项目级文档。
- 资源快照：Binance skill/API 参考、Agent soft layer、endpoint policy 和 trader role profile 都放在 `project/resources/`，由 manifest 和 schema 暴露来源。
- 本地运行态：`.runtime/`、`.hermes/`、`.tradecat/`、`.venv/`、`.tools/` 与 `project/.runtime/` 等目录只属于本机，不得成为源码资产。

## 根目录职责

根目录负责让 Hermes/Agent 知道“如何使用这个 Skill 包”：

- `SKILL.md`：最短激活说明、常用入口、安全边界和验证入口。
- `agents/manifest.json`：唯一机器主契约，声明路径、命令、schema、风险等级、角色配置和运行顺序。
- `agents/hermes.yaml` / `agents/openai.yaml`：平台适配层，只指向 manifest 和引用文档。
- `references/`：长文档与治理说明，引用 manifest，不复制机器契约。
- `scripts/*.sh`：从 Skill 根进入项目实现或治理门禁的薄封装。

根目录不得新增 `assets/`、`assets/examples/`、`src/`、`tests/`、`pyproject.toml`、`Makefile` 或 install/uninstall 脚本。需要项目示例或资源时，放入 `project/` 并同步项目文档。

## 内部项目职责

`project/` 承载所有 TradeCat 具体实现：

- 公开 Google Sheets 数据消费、cache-first CLI/TUI、zero-install request。
- Agent-supplied Binance public/read-only market context 对齐与审计。
- paper/watch run-once、run-loop、replay/backtest、ledger、risk、audit journal、health/daily/alert 报告。
- JSON Schema contracts、资源 provenance、项目测试和项目级验证脚本。

TradeCat 不内置真实交易权限。任何 Agent/交易员配置都只是 soft prompt 或研究假设；真实边界由 schema、context-audit、risk gate 和 paper ledger 代码兜底。

## Agent/交易员角色配置

机器入口是 `agents/manifest.json` 的 `agent_role_profiles`。当前默认 role 是 `discretionary_futures_trader`，实际文本在 `project/resources/agent_soft_layer/profiles/discretionary-futures-trader.zh.md`，并通过：

```bash
bash scripts/run-tradecat.sh auto soft-layer --json
```

暴露给 Agent/Hermes。该 role 只能用于 public/read-only 市场研究、paper/watch thesis 和 prompt 组织，不授权 Binance key、签名请求、真实账户读取或真实下单。

## 安全与验证

结构治理改动至少要验证：

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
cd project && bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

边界检查由 `project/scripts/guard_public_local_files.sh` 和 `project/tests/test_agent_contract.py` 共同兜底：禁止 root Python 项目形态、禁止跟踪本地运行态、要求 manifest 的关键静态路径存在，并保持 `project_root=project`。
