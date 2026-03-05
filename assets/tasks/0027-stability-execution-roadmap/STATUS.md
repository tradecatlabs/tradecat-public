# STATUS - 0027 stability-execution-roadmap

## 当前状态

- 状态：Done
- 最后更新：2026-03-05
- 基线提交：59b995c3
- 收尾提交：
  - `39a91db1`（0015 P2：SQLite 运行态出清 + 文档口径同步）
- Owner：TBD

## 端到端冒烟清单（≥10 条，最小可复现）

> 目标：保证“采集→计算→查询→导出/消费”核心链路在本地至少能通过门禁与关键守护检查。

1) `./scripts/verify.sh`：✅ 通过  
   - 断言：顶层无 symlink；核心链路无 SQLite 引用；consumption 无 PG 直连与 SQL 片段；i18n 对齐；docs 链接可达
2) `cd services/consumption/api-service && make check`：✅ `26 passed`
3) `cd services/consumption/telegram-service && make check`：✅ `3 passed`
4) `cd services/consumption/sheets-service && make check`：✅ `8 passed`
5) `cd services/compute/trading-service && make check`：✅ `2 passed, 1 skipped`
6) `cd services/ingestion/data-service && make check`：✅ `6 passed`
7) `rg -n "import sqlite3|sqlite3\\.connect" services -S --glob '!**/.venv/**'`：✅ 无命中
8) `find . -type f -name "*.db" -not -path "*/assets/repo/*" -not -path "*/.venv/*" -not -path "*/dist/*" | sort`：✅ 仅剩历史/非核心链路 `.db`
9) `rg -n "\\| 0015 \\|.*\\| Done \\|" assets/tasks/INDEX.md`：✅ 0015 标记 Done
10) `rg -n "\\| 0027 \\|.*\\| Done \\|" assets/tasks/INDEX.md`：✅ 0027 标记 Done
11) `rg -n "market_data\\.db" README* assets/docs/analysis`：✅ 仅保留历史/迁移说明（不再作为运行态依赖）

## 证据存证（执行过程中填写）

> 规则：
> - 只记录“事实与可复现命令”，不记录敏感信息（DSN 密码/Token/SA JSON）。
> - 每个 Phase 通过后再进入下一 Phase。

- `git rev-parse --short HEAD`: `39a91db1`
- `./scripts/verify.sh`: ✅ 通过（提示：未找到顶层 `.venv`，ruff 未安装；仅影响顶层校验，不影响各服务自带 `.venv` 的 `make check`）
- `rg -n "import sqlite3|sqlite3\\.connect" services -S --glob '!**/.venv/**'`：无命中
- `find . -type f -name "*.db" -not -path "*/assets/repo/*" -not -path "*/.venv/*" -not -path "*/dist/*" | sort`：
  - `./assets/artifacts/sqlite_import/market_data_windows.db`（导入 artifacts：回放/对账）
  - `./assets/artifacts/sqlite_import/market_data_windows_recovered.db`（导入 artifacts：回放/对账）
  - `./assets/database/services/telegram-service/market_data.db`（历史指标库样本：schema 提取/迁移对账）
  - `./services/compute/fate-service/libs/database/bazi/bazi.db`（非核心链路：不纳入“单 PG”整改范围）
  - `./services/compute/fate-service/libs/external/github/tzuwei-master/.vs/Prototype3/v15/Browse.VC.db`（外部仓库缓存：非核心链路）
  - `./services/consumption/nofx-dev/data/data.db`（非核心链路：不纳入“单 PG”整改范围）
- 核心服务门禁（至少 api-service/telegram-service/trading-service/data-service/sheets-service）：
  - `cd services/consumption/api-service && make check`: ✅ 通过（pytest：`26 passed`）
  - `cd services/consumption/telegram-service && make check`: ✅ 通过（pytest：`3 passed`）
  - `cd services/compute/trading-service && make check`: ✅ 通过（pytest：`2 passed, 1 skipped`）
  - `cd services/consumption/sheets-service && make check`: ✅ 通过（pytest：`8 passed`）
  - `cd services/ingestion/data-service && make check`: ✅ 通过（pytest：`6 passed`；含 `tests/test_ban_backoff.py`）

## 进展记录

- 2026-03-05（完成 0012 sheets-service-hardening）
  - 相关提交：`24265767`
  - `./scripts/verify.sh`：✅ 通过（同样提示：顶层 `.venv`/ruff 缺失不影响各服务门禁）
  - `cd services/consumption/sheets-service && make check`：✅ 通过（pytest：`8 passed`）
  - 结果：`0012` 已标记 Done（见 `assets/tasks/0012-sheets-service-hardening/STATUS.md`）

- 2026-03-05（完成 0025 query-service-production-hardening）
  - 相关提交：`0e3d4a1d`
  - `sed -n '1,60p' assets/tasks/0025-query-service-production-hardening/TODO.md`：✅ P2 两项已勾选
  - 结果：`0025` 已标记 Done（见 `assets/tasks/0025-query-service-production-hardening/STATUS.md`）

- 2026-03-05（完成 0015 unify-all-storage-to-postgres P2 收尾）
  - 相关提交：`39a91db1`
  - `./scripts/verify.sh`：✅ 通过（含“核心链路无 SQLite 引用/consumption 无 PG 直连”守护）
  - `services/consumption/sheets-service/data/remote/`：✅ 远端 SQLite 快照产物已清理（空目录）
  - 结果：`0015` 已标记 Done（见 `assets/tasks/0015-unify-all-storage-to-postgres/STATUS.md`）

## 阻塞详情（如有）

- Blocked by: _None_
- Required Action: _None_
