# TODO

> 格式：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

## P0（必须做）

- [ ] P0: 复现 CI ruff 失败并统计 `E,F` 错误清单 | Verify: `/tmp/tradecat-audit-venv/bin/ruff check services/ --ignore E501,E402 --select E,F --output-format full` | Gate: `ACCEPTANCE.A1`
- [ ] P0: 修改 `.github/workflows/ci.yml` 的 ruff 命令为 `--select E,F`（保留必要 ignore） | Verify: `cat .github/workflows/ci.yml | rg -n \"ruff check\"` | Gate: `ACCEPTANCE.A1`
- [ ] P0: 修复所有 `E,F` 级别错误（`F401/F821/F601/E721/...`） | Verify: `/tmp/tradecat-audit-venv/bin/ruff check services/ --ignore E501,E402 --select E,F` 退出码 0 | Gate: `ACCEPTANCE.A1`
- [ ] P0: 确保 pytest 只扫 `tests/` 且不会进入 `assets/repo/**` | Verify: `pytest -q` | Gate: `ACCEPTANCE.B1`
- [ ] P0: 新增 `src/tradecat/**`（最小包骨架 + `cli.py` + `__init__.py`） | Verify: `python -c \"from tradecat import Data, Indicators, Signals, AI, __version__\"` | Gate: `ACCEPTANCE.C1`
- [ ] P0: 确保 `python -m build` 可构建并 `twine check dist/*` 通过 | Verify: `python -m build && twine check dist/*` | Gate: `ACCEPTANCE.C3`

## P1（建议做）

- [ ] P1: 更新 `README.md`（补齐“PyPI 包/CLI 入口”的现实状态） | Verify: `rg -n \"tradecat\" README.md` | Gate: `ACCEPTANCE.C2`
- [ ] P1: 更新 `AGENTS.md`（补齐“CI 基线 lint 规则/测试入口”的硬约束） | Verify: `rg -n \"CI\" AGENTS.md` | Gate: 文档与行为一致
- [ ] P1: 对“旧路径引用”做可执行面清零（scripts/services/workflows） | Verify: `rg -n \"\\bdocs/|\\btasks/|\\bartifacts/|\\blibs/\" scripts services .github/workflows` | Gate: 不影响运行

## P2（可选增强）

- [ ] P2: 分阶段扩大 CI ruff 规则集（`I/UP/B/...`） | Verify: `ruff check services/` 错误趋势单调下降 | Gate: CI 稳定不回退

## Parallelizable（可并行）

- `P0: pytest discovery` 与 `P0: ruff E,F 修复` 可并行。
- `P0: src/tradecat 包骨架` 可与上述并行，但最终需一起过 `python -m build`。

