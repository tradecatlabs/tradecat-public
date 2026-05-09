# tradecat-public Agent 操作说明

本文件作用域：`tradecat-public/**`。它是公开治理说明，随仓库提交；内容必须保持
脱敏，不得包含凭证、缓存内容或私密环境变量。

## 目录定位

根目录是 Skill 外壳，不是 Python 项目根。TradeCat 用户侧源码统一归入
`scripts/project/`。

```text
tradecat-public/
|-- README.md
|-- AGENTS.md
|-- lessons.md
|-- .git/
|-- .github/workflows/ci.yml
|-- .gitignore
|-- .pre-commit-config.yaml
|-- SKILL.md
|-- agents/
|   |-- manifest.json
|   |-- hermes.yaml
|   `-- openai.yaml
|-- references/
|   |-- index.md
|   |-- agent-contract.md
|   |-- agent-contract-maturity-task-tree.md
|   |-- agent-contract-maturity-task-tree.json
|   |-- agent-readiness-remediation-task-tree.md
|   |-- agent-readiness-remediation-task-tree.json
|   |-- architecture.md
|   |-- cache-contract.md
|   |-- first-run-cache.md
|   |-- install-uninstall.md
|   |-- linear-flows.md
|   |-- quality-gate.md
|   |-- release.md
|   |-- stability-hardening-task-tree.md
|   |-- stability-hardening-task-tree.json
|   `-- tui-contract.md
`-- scripts/
    |-- validate-skill.sh
    |-- verify.sh
    |-- bootstrap-dev.sh
    |-- agent-smoke.sh
    |-- security-scan.sh
    |-- supply-chain-audit.sh
    |-- install-security-tools.sh
    |-- clean-local-runtime.sh
    |-- run-tradecat.sh
    `-- project/
        |-- README.md
        |-- AGENTS.md
        |-- DEBUG.md
        |-- DEBUG.archive.md
        |-- pyproject.toml
        |-- constraints.txt
        |-- contracts/
        |-- scripts/
        |-- src/
        `-- tests/
```

## 根目录边界

- `.git/`、`.github/`、`.gitignore` 是 Git / CI 边界，禁止移动到
  `scripts/project/`。
- `SKILL.md`、`agents/`、`references/` 是 Skill/Agent 契约边界，禁止混入项目源码。
- `agents/manifest.json` 是唯一机器可读 Agent 主契约；`agents/openai.yaml`
  与 `agents/hermes.yaml` 只能作为平台适配层。
- `lessons.md` 是事故经验与防复发规则，必须保持脱敏、短句、可执行。
- `scripts/validate-skill.sh`、`scripts/verify.sh`、`scripts/bootstrap-dev.sh`、
  `scripts/security-scan.sh`、`scripts/supply-chain-audit.sh`、
  `scripts/install-security-tools.sh`、`scripts/clean-local-runtime.sh`、
  `scripts/agent-smoke.sh` 和
  `scripts/run-tradecat.sh` 只是薄入口，业务逻辑在 `scripts/project/`，
  治理扫描只读取 Git 跟踪文件或指定提交范围。
- 根目录禁止创建 `assets/`、`assets/examples/`、`src/`、`tests/`、
  `pyproject.toml`、`Makefile`、安装脚本或卸载脚本。

## 项目目录边界

`scripts/project/` 是唯一 Python 项目根，承载：

- `README.md`：用户安装、运行、开发说明。
- `pyproject.toml` / `constraints.txt` / `Makefile`：Python 项目元数据、依赖锁定口径与开发入口。
- `contracts/`：公开 JSON Schema 草案文件，用于外部工具校验 Agent/CLI 契约。
- `install.*` / `uninstall.*`：用户安装与卸载入口。
- `scripts/`：项目级脚本。
- `src/tradecat_terminal/`：TradeCat CLI / TUI 源码。
- `tests/`：项目测试。
- `AGENTS.md`、`DEBUG.md`、`DEBUG.archive.md`：项目治理与调试记录，随仓库提交；
  必须保持公开安全，不得写入凭证、缓存内容或私密环境变量。

## 验证

从根目录执行：

```bash
bash scripts/bootstrap-dev.sh
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
```

从根目录执行 Skill 严格校验：

```bash
bash scripts/validate-skill.sh --strict
```

从项目目录执行：

```bash
cd scripts/project
bash scripts/verify.sh
```
