# STATUS

状态：Not Started

## 仓库基线

- Branch: `develop`
- Checkpoint（对话中已存在）：`527c998`（可作为迁移前回滚锚点）

## 已执行的证据收集（来自本任务创建时的扫描）

- `find libs -maxdepth 2 -type d` 显示 `libs/common`, `libs/database`, `libs/external` 并存。
- `rg -n "import libs|from libs|libs/" -S .` 命中：
  - `services/compute/ai-service/scripts/start.sh:68`
  - `services/compute/ai-service/src/llm/client.py:56`
  - `config/.env.example:458`
  - `scripts/init.sh:139`
  - `scripts/check_env.sh:424`
  - ……
- `rg -n "libs/external" -S .` 目前输出为空（意味着 Stage 1 很可能是纯目录迁移）。

## 下一步

- 按 `TODO.md` 执行 Stage 0 盘点，并将“引用清单”完整落在本文件中（便于执行 Agent 逐项消除）。

