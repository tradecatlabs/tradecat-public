# tradecat-public

这是一个标准 Skill 外壳仓库，真正的 TradeCat 用户侧源码统一放在
`scripts/project/`。

## 用户安装入口

TradeCat 用户侧安装、运行和卸载说明见
[scripts/project/README.md](scripts/project/README.md)。
固定版本发布说明见 [references/release.md](references/release.md)。

Linux / macOS / WSL / Git Bash：

```bash
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.2/scripts/project/install.sh | sh
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.2/scripts/project/install.ps1 | iex
```

根目录只承担三件事：

1. 作为 Git 仓库边界。
2. 作为 Skill 入口与长期参考资料边界。
3. 提供进入项目源码的薄脚本。

## 根目录应有文件

```text
tradecat-public/
|-- README.md
|-- AGENTS.md                 # 根治理说明，随仓库提交
|-- lessons.md                # 本仓长期事故经验与防复发规则
|-- .git/                     # Git 元数据，隐藏目录，不移动
|-- .github/workflows/ci.yml  # GitHub CI，隐藏目录，不移动
|-- .gitignore
|-- .pre-commit-config.yaml
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
|-- references/
|   |-- index.md
|   |-- architecture.md
|   |-- cache-contract.md
|   |-- first-run-cache.md
|   |-- install-uninstall.md
|   |-- linear-flows.md
|   |-- quality-gate.md
|   |-- release.md
|   `-- tui-contract.md
`-- scripts/
    |-- verify.sh
    |-- bootstrap-dev.sh
    |-- security-scan.sh
    |-- supply-chain-audit.sh
    |-- install-security-tools.sh
    |-- clean-local-runtime.sh
    |-- run-tradecat.sh
    `-- project/
```

说明：在 Windows 文件管理器或 WSL 网络路径中，`.git/`、`.github/`、
`.gitignore` 这类点号开头的 Git 文件默认可能被隐藏。

## 项目源码位置

```text
scripts/project/
|-- README.md
|-- Makefile
|-- pyproject.toml
|-- install.sh
|-- install.ps1
|-- uninstall.sh
|-- uninstall.ps1
|-- AGENTS.md
|-- DEBUG.md
|-- DEBUG.archive.md
|-- scripts/
|-- src/tradecat_terminal/
`-- tests/
```

`scripts/project/` 是 Python 项目根；运行、打包、安装、测试和源码修改都以
这里为准。

## 移动边界

应留在根目录：

- `.git/`、`.gitignore`、`.github/`：仓库与 CI 元数据。
- `SKILL.md`：Skill 激活入口。
- `agents/`：Agent marketplace / profile 元数据。
- `references/`：Skill 长文档与契约。
- `scripts/verify.sh`、`scripts/bootstrap-dev.sh`、`scripts/security-scan.sh`、
  `scripts/supply-chain-audit.sh`、`scripts/install-security-tools.sh`、
  `scripts/clean-local-runtime.sh`、`scripts/run-tradecat.sh`：从 Skill 根进入项目或治理门禁的薄封装。

应放入 `scripts/project/`：

- `README.md`、`Makefile`、`pyproject.toml`。
- `install.*`、`uninstall.*`。
- Python 包源码 `src/`。
- 测试 `tests/`。
- 项目脚本 `scripts/request.py`、`scripts/start.sh`、`scripts/watchdog.sh`、
  `scripts/verify.sh`、`scripts/guard_public_local_files.sh`；根级
  `scripts/security-scan.sh` 留在 Skill 根。
- 项目治理文档 `AGENTS.md`、`DEBUG.md`、`DEBUG.archive.md`；这些文件随仓库提交，
  但必须保持脱敏，不得写入凭证、缓存内容或私密环境变量。

根目录禁止重新出现 `assets/` 或 `assets/examples/`。如果以后确实需要项目示例
资产，应放入 `scripts/project/` 内部，并同步更新项目文档。

## 常用入口

```bash
bash scripts/bootstrap-dev.sh
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
bash scripts/validate-skill.sh --strict
bash scripts/run-tradecat.sh --help
cd scripts/project
PYTHONPATH=src python3 -m tradecat_terminal --help
```

本地收尾清理忽略运行态目录：

```bash
bash scripts/clean-local-runtime.sh --apply
```
