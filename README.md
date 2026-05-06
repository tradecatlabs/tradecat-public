# tradecat-public

这是一个标准 Skill 外壳仓库，真正的 TradeCat 用户侧源码统一放在
`scripts/project/`。

根目录只承担三件事：

1. 作为 Git 仓库边界。
2. 作为 Skill 入口与长期参考资料边界。
3. 提供进入项目源码的薄脚本。

## 根目录应有文件

```text
tradecat-public/
|-- README.md
|-- AGENTS.md                 # 本地治理说明，按公开仓库规则忽略
|-- .git/                     # Git 元数据，隐藏目录，不移动
|-- .github/workflows/ci.yml  # GitHub CI，隐藏目录，不移动
|-- .gitignore
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
|-- references/
|   |-- index.md
|   |-- architecture.md
|   |-- cache-contract.md
|   |-- install-uninstall.md
|   `-- tui-contract.md
`-- scripts/
    |-- verify.sh
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
- `scripts/verify.sh`、`scripts/run-tradecat.sh`：从 Skill 根进入项目的薄封装。

应放入 `scripts/project/`：

- `README.md`、`Makefile`、`pyproject.toml`。
- `install.*`、`uninstall.*`。
- Python 包源码 `src/`。
- 测试 `tests/`。
- 项目脚本 `scripts/request.py`、`scripts/start.sh`、`scripts/watchdog.sh`、
  `scripts/verify.sh`、`scripts/guard_public_local_files.sh`。
- 项目本地文档 `AGENTS.md`、`DEBUG.md`、`DEBUG.archive.md`，这些文件按公开
  仓库规则忽略，不提交。

根目录禁止重新出现 `assets/` 或 `assets/examples/`。如果以后确实需要项目示例
资产，应放入 `scripts/project/` 内部，并同步更新项目文档。

## 常用入口

```bash
bash scripts/verify.sh
bash scripts/run-tradecat.sh --help
cd scripts/project
PYTHONPATH=src python3 -m tradecat_terminal --help
```
