# ACCEPTANCE

## A) CI（`ci.yml`）验收

- A1：本地等价执行 CI lint 命令通过（无 ruff 报错）
  - Verify: `ruff check services/ ...`（以 `PLAN.md` 里最终选定的命令为准）
- A2：本地等价执行 CI syntax-check 通过
  - Verify: `find services -name "*.py" -type f | head -50 | xargs -I {} python -m py_compile {}`

## B) pytest discovery 验收

- B1：`pytest -q` 只扫描 `tests/`，不会进入 `assets/repo/**`
  - Verify: `pytest -q` 输出 `1 passed`（或更多，但不得 collection 崩溃）
- B2（边缘）：即使 `assets/repo/**` 内存在 `test_*.py`，也不影响 pytest collection
  - Verify: `pytest -q` 仍为 0 退出码

## C) PyPI 包/CLI 验收

- C1：`src/tradecat/**` 存在且可导入
  - Verify: `python -c "from tradecat import Data, Indicators, Signals, AI, __version__"`
- C2：`tradecat` CLI 入口可执行（最低：帮助信息）
  - Verify: `python -m tradecat --help` 或 `tradecat --help`（取决于安装方式）
- C3：构建可用
  - Verify: `python -m build` 产出 `dist/*.whl` 与 `dist/*.tar.gz`
- C4：wheel 安装后的 import smoke 可用
  - Verify: `pip install dist/*.whl && python -c "import tradecat; print(tradecat.__version__)"`

## D) 安全/污染验收（Anti-Goals）

- D1：运行时数据不得进入 git index（例如 `services/**/data/**`、AI payload）
  - Verify: `git status --porcelain` 无 `data/`、`*.db`、`raw_payload.json` 等
- D2：不允许把凭证写入仓库
  - Verify: `git grep -nE 'BEGIN PRIVATE KEY|client_secret|service_account'`

