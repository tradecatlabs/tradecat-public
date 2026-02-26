# STATUS

State: Not Started

## 当前基线（证据记录）

- 分支：`develop`
- 近期关键提交（示例）：
  - `a8d4c00`：忽略并从 index 移除运行时 AI/telegram 数据
  - `4cb756f`：新增 `tests/` + 约束 pytest discovery
  - `07dbf34`：ai/signal 启动脚本改为安全加载 `.env`
- CI 现状：
  - `.github/workflows/ci.yml` 运行 `ruff check services/ --ignore E501,E402`（当前会失败）
  - `.github/workflows/pypi-ci.yml` 依赖 `src/tradecat/**`（当前目录缺失）

## 已执行命令（执行 Agent 需继续补充）

- `./scripts/verify.sh`：通过（含 pytest smoke）
- `pytest -q`：需保持通过且不误扫 `assets/repo/**`

## Blockers

- `src/tradecat/**` 缺失导致 PyPI 构建/导入链路不可用（P0）。
- `services/**` ruff 全规则错误过多，需先收敛到 `E,F`（P0）。

