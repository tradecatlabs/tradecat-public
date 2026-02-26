# STATUS

状态：In Progress

## 仓库基线

- Branch: `develop`
- Checkpoint（对话中已存在）：`527c998`（可作为迁移前回滚锚点）

## Stage 0：引用盘点（证据）

### 0.1 目录现状

- `find libs -maxdepth 2 -type d` 显示 `libs/common`, `libs/database`, `libs/external` 并存（职责混杂）。

### 0.2 Python import 级依赖（排除第三方镜像噪音）

> 说明：`libs/external/*` 内部的第三方仓库（例如 qlib examples）存在 `import libs.*`，但这不属于本仓库运行链路，盘点时需排除以避免噪音。

- `rg -n "\bimport\s+libs\b|\bfrom\s+libs\b" -S . --glob '!libs/external/**' | wc -l` = `20`
- 关键命中（节选）：
  - `services/compute/ai-service/scripts/start.sh:68`
  - `services/compute/ai-service/src/llm/client.py:56`
  - `services/consumption/telegram-service/src/cards/i18n.py:17`
  - `services/consumption/telegram-service/src/bot/app.py:53`

### 0.3 路径依赖（`libs/database`）

- `rg -n "libs/database" -S . --glob '!libs/external/**' | wc -l` = `158`
- 关键命中（节选）：
  - `config/.env.example:458`（`INDICATOR_SQLITE_PATH=libs/database/...`）
  - `scripts/init.sh:139`（创建 `libs/database/services/...`）
  - `scripts/check_env.sh:424`（检查 `libs/database/services/telegram-service/market_data.db`）
  - `services/compute/signal-service/src/config.py:36`（默认返回 `libs/database/...`）

### 0.4 `libs/external` 路径依赖（仅检查本仓库代码/脚本/配置/文档）

- `rg -n "libs/external" -S services scripts config docs tasks | wc -l` = `0`

结论：Stage 1（`libs/external` → `assets/repo`）应为**纯目录迁移**，几乎无引用替换风险；Stage 2（`libs/` → `assets/`）必须引入兼容层并逐项迁移。

## 下一步

- 按 `TODO.md` 执行 Stage 0 盘点，并将“引用清单”完整落在本文件中（便于执行 Agent 逐项消除）。

## Stage 1：执行记录（`libs/external` → `assets/repo`）

- 现实约束：`libs/external/` 被 `.gitignore` 忽略（证据：`.gitignore:123: libs/external/`），因此无法用 `git mv` 产生可审计 diff（source 目录在 index 中为空）。
- 已执行：
  - `mv libs/external assets/repo`
  - `.gitignore` 新增：`assets/repo/`（避免 2.9G 目录出现在 untracked）
- 迁移后验证：
  - `test -d assets/repo` ✅
  - `test -e libs/external`（应不存在）✅

## Stage 2：执行记录（`libs/` → `assets/` + 兼容层）

- 兼容层决策：采用 **顶层 symlink**（`libs -> assets`），避免“在 `libs/` 下对已跟踪目录做子级 symlink”导致 git index/rename 检测混乱。
- 已执行：
  - `git mv libs/common assets/common`
  - `git mv libs/database assets/database`
  - `git mv libs/__init__.py assets/__init__.py`
  - 创建并提交：`libs -> assets`（symlink，确保 `import libs.*` 与 `libs/database/...` 路径继续可用）
  - `.gitignore` 同步补齐：`assets/database/*` 的临时目录 ignore，避免迁移后出现大量 untracked
- 迁移后快速验证：
  - `python3 -c "import libs.common, assets.common; print('ok')"` ✅
