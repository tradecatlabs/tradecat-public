# tradecat-public

这是给用户本机 Hermes 使用的 TradeCat Skill 包：用户把本仓库安装到 `~/.hermes/skills/tradecat-public` 后，Hermes 通过 `SKILL.md` 和 `agents/manifest.json` 读取规则、入口和契约；`scripts/project/` 只是这个 skill 调用的本地只读工具层。Agent / Hermes 的机器第一入口是 `agents/manifest.json`，长文档契约见 `references/agent-contract.md`。


## 安装给本机 Hermes 使用

最简单方式是把本仓库作为 Hermes skill 放到本机 skills 目录：

```bash
git clone https://github.com/tukuaiai/tradecat-public ~/.hermes/skills/tradecat-public
hermes -s tradecat-public
```

开发中的本地仓库也可以用软链接方式挂进去：

```bash
mkdir -p ~/.hermes/skills
ln -sfn /path/to/tradecat-public ~/.hermes/skills/tradecat-public
hermes -s tradecat-public
```

## Agent 快速入口

```bash
python3 -m json.tool agents/manifest.json >/dev/null
bash scripts/run-tradecat.sh status --json
bash scripts/run-tradecat.sh datasets --json
bash scripts/run-tradecat.sh path event_stream --json
bash scripts/run-tradecat.sh analyze --json
bash scripts/run-tradecat.sh features --json
bash scripts/run-tradecat.sh auto paper-report --json
bash scripts/run-tradecat.sh auto run-loop --mode paper --notional-usdt 12 --once --json
bash scripts/run-tradecat.sh auto context-audit --input /path/to/agent-market-context.json --json
bash scripts/run-tradecat.sh auto run-context --input /path/to/agent-market-context.json --mode paper --notional-usdt 12 --json
bash scripts/run-tradecat.sh auto replay-report --archive-path .runtime/cycles.jsonl --ledger-path .runtime/paper_ledger.json --json
python3 scripts/project/scripts/request.py event_stream --format json --limit 5
```

`datasets --json` 同时携带 dataset consumption contract；字段语义、缺失值、
时间粒度和质量等级的长文档见
[references/dataset-consumption-contract.md](references/dataset-consumption-contract.md)。
`analyze --json` 只读本地缓存，输出
`tradecat.analysis_report.v1` 观察报告；边界见
[references/analysis-contract.md](references/analysis-contract.md)。
`features --json` 复用本地观察报告逻辑，输出
`tradecat.feature_bundle.v1` 按 symbol 归一化的事实包；它仍然只是事实层，边界见
[references/feature-contract.md](references/feature-contract.md)。Hermes/Agent 自动化入口统一走 `tradecat auto ...` / `bash scripts/run-tradecat.sh auto ...`，当前只允许公开行情、Agent-supplied market context 审计、paper/watch 和 JSONL replay，不读取 Binance API key，不签名，不真实下单；它是给 Hermes 使用的本地契约层，不是让 TradeCat 自己越权变成真实交易机器人。

默认先走只读入口；只有需要写本地缓存时再执行 `sync`、`doctor --repair`、
安装或卸载。

## 用户安装入口

TradeCat 用户侧安装、运行和卸载说明见
[scripts/project/README.md](scripts/project/README.md)。
固定版本发布说明见 [references/release.md](references/release.md)。

Linux / macOS / WSL / Git Bash：

```bash
curl -fsSL https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.3/scripts/project/install.sh | sh
```

Windows PowerShell：

```powershell
irm https://raw.githubusercontent.com/tukuaiai/tradecat/v0.1.3/scripts/project/install.ps1 | iex
```

根目录承担三件事：

1. 作为 Git 仓库边界。
2. 作为 Skill 入口与长期参考资料边界。
3. 提供进入统一项目源码与自动化生命周期入口的薄脚本。

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
|   |-- analysis-contract.md
|   |-- cache-contract.md
|   |-- dataset-consumption-contract.md
|   |-- feature-contract.md
|   |-- first-run-cache.md
|   |-- install-uninstall.md
|   |-- linear-flows.md
|   |-- quality-gate.md
|   |-- release.md
|   |-- stability-hardening-task-tree.md
|   |-- stability-hardening-task-tree.json
|   |-- test-strategy.md
|   `-- tui-contract.md
`-- scripts/
    |-- verify.sh
    |-- bootstrap-dev.sh
    |-- agent-smoke.sh
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
|-- constraints.txt
|-- contracts/
|-- install.sh
|-- install.ps1
|-- uninstall.sh
|-- uninstall.ps1
|-- AGENTS.md
|-- DEBUG.md
|-- DEBUG.archive.md
|-- scripts/
|-- src/tradecat_terminal/
|-- src/tradecat_auto/
`-- tests/
```

`scripts/project/` 是 Python 项目根；`tradecat-auto` 已并入这里，不再作为独立实现中心。运行、打包、安装、测试和源码修改都以这里为准。

## 移动边界

应留在根目录：

- `.git/`、`.gitignore`、`.github/`：仓库与 CI 元数据。
- `SKILL.md`：Skill 激活入口。
- `agents/`：canonical machine manifest 和平台 profile 元数据。
- `references/`：Skill 长文档与契约。
- `scripts/verify.sh`、`scripts/bootstrap-dev.sh`、`scripts/security-scan.sh`、
  `scripts/supply-chain-audit.sh`、`scripts/install-security-tools.sh`、
  `scripts/clean-local-runtime.sh`、`scripts/run-tradecat.sh`、
  `scripts/agent-smoke.sh`：从 Skill 根进入项目或治理门禁的薄封装。

应放入 `scripts/project/`：

- `README.md`、`Makefile`、`pyproject.toml`、`constraints.txt`。
- `install.*`、`uninstall.*`。
- Python 包源码 `src/`，包括 `tradecat_terminal` 用户侧数据层和 `tradecat_auto` 自动化生命周期层。
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
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
bash scripts/validate-skill.sh --strict
bash scripts/run-tradecat.sh --help
cd scripts/project
PYTHONPATH=src python3 -m tradecat_terminal --help
PYTHONPATH=src python3 -m tradecat_auto.cli --help
PYTHONPATH=src python3 -m tradecat_terminal auto --help
```

本地收尾清理忽略运行态目录：

```bash
bash scripts/clean-local-runtime.sh --apply
```
