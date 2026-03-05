# STATUS - 0027 stability-execution-roadmap

## 当前状态

- 状态：In Progress
- 最后更新：2026-03-05
- 基线提交：59b995c3
- Owner：TBD

## 证据存证（执行过程中填写）

> 规则：
> - 只记录“事实与可复现命令”，不记录敏感信息（DSN 密码/Token/SA JSON）。
> - 每个 Phase 通过后再进入下一 Phase。

- `git rev-parse --short HEAD`: `59b995c3`
- `./scripts/verify.sh`: ✅ 通过（提示：未找到顶层 `.venv`，ruff 未安装；仅影响顶层校验，不影响各服务自带 `.venv` 的 `make check`）
- 核心服务门禁（至少 api-service/telegram-service/trading-service/data-service/sheets-service）：
  - `cd services/consumption/api-service && make check`: ✅ 通过（pytest：`26 passed`）
  - `cd services/consumption/telegram-service && make check`: ✅ 通过（pytest：`3 passed`）
  - `cd services/compute/trading-service && make check`: ✅ 通过（pytest：`2 passed, 1 skipped`）
  - `cd services/consumption/sheets-service && make check`: ✅ 通过（pytest：`8 passed`）
  - `cd services/ingestion/data-service && make check`: ❌ 失败（ruff lint：`Found 148 errors`；含 `UP035/E402/UP006/UP045` 等；`126` 可 `--fix` 自动修复）

## 阻塞详情（如有）

- Blocked by: data-service `make check` 当前不绿（lint 失败）
- Required Action: 按 `0018-stabilize-data-service-ban-backoff` 执行时同步修复 lint（至少做到 `make check` 通过），再继续后续 Phase
