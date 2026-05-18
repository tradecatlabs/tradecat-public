# Skill Package Governance

`tradecat-public` 现在是正常 Python 项目根，Hermes/Codex Skill 包内嵌在 `skills/tradecat-public/`。Agent/Hermes 读取 `skills/tradecat-public/SKILL.md` 后，应把 `skills/tradecat-public/agents/manifest.json` 当作唯一机器主契约；其他文档只解释和索引它。

## 分层边界

- 仓库根：Python 项目根，承载源码、测试、contracts、resources、安装/卸载脚本、项目脚本、CI 和本地 paper/watch 运维。
- Skill 包根：`skills/tradecat-public/`，只承载 Skill 激活、Agent profile、manifest、长文档和跳回根项目的薄 wrapper。
- 资源快照：Binance skill/API 参考、Agent soft layer、endpoint policy 和 trader role profile 都放在根项目 `resources/`。
- 本地运行态：`.runtime/`、`.hermes/`、`.tradecat/`、`.venv/`、`.tools/` 只属于本机，不得成为源码资产。

## 根项目职责

- `src/`：TradeCat CLI/TUI、公开表格、Agent context、paper/watch 自动化源码。
- `contracts/`：公开 JSON Schema 草案文件。
- `resources/`：自包含公开参考资源与 Agent soft layer。
- `scripts/`：项目验证、运行、安装辅助、auto-paper 运维、监控和安全扫描入口。
- `tests/`：项目测试和边界守卫。
- `tasks/`：任务治理资产，不属于运行态。

## Skill 包职责

- `SKILL.md`：最短激活说明、常用入口、安全边界和验证入口。
- `agents/manifest.json`：唯一机器主契约；路径按仓库根目录解释。
- `agents/hermes.yaml` / `agents/openai.yaml`：平台适配层，只指向 manifest 和引用文档。
- `references/`：长文档与治理说明，引用 manifest，不复制机器契约。
- `scripts/*.sh`：从 Skill 包跳回根项目脚本的薄封装。

仓库根不得重新出现 `SKILL.md`、`agents/` 或 `references/`，避免 Skill 契约出现第二真相源。根项目允许并且应该拥有 `src/`、`tests/`、`contracts/`、`resources/`、`pyproject.toml`、`Makefile` 与安装脚本。

## Agent/交易员角色配置

机器入口是 `skills/tradecat-public/agents/manifest.json` 的 `agent_role_profiles`。当前默认 role 是 `discretionary_futures_trader`，实际文本在 `resources/agent_soft_layer/profiles/discretionary-futures-trader.zh.md`，并通过：

```bash
bash scripts/run-tradecat.sh auto soft-layer --json
```

暴露给 Agent/Hermes。该 role 只能用于 public/read-only 市场研究、paper/watch thesis 和 prompt 组织，不授权 Binance key、签名请求、真实账户读取或真实下单。

## 安全与验证

结构治理改动至少要验证：

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

边界检查由 `scripts/guard_public_local_files.sh` 和 `tests/test_agent_contract.py` 共同兜底：禁止跟踪本地运行态，禁止仓库根恢复旧 Skill 外壳，要求 `project_root=.`、`skill_root=skills/tradecat-public`，并保持 public-readonly + paper/watch 安全边界。
