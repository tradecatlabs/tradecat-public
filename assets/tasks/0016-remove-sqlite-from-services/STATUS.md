# STATUS：remove-sqlite-from-services

Status: Done

## Live Evidence（已完成的只读审计记录）

> 说明：核心服务侧已完成“去 SQLite 运行时依赖/误导性文案”，并清理遗留 `.db` 文件。

- ✅ 已完成（signal-service）：
  - 修复默认事件来源：`source="sqlite"` → `source="pg"`
  - 移除/替换不存在的 sqlite_engine 测试引用
  - 重写 history 测试为纯 unit（不依赖真实数据库）
  - 证据：提交 `ea5e626c`（`fix(signal-service): remove sqlite remnants`）
  - 证据：`cd services/compute/signal-service && make test` → `15 passed`

- ✅ 已完成（api-service）：
  - 修正文档/注释中 “SQLite” 误导口径，明确数据源为 PG（tg_cards / signal_state）
  - 证据：提交 `4a9b9fd5`（`docs(api-service): remove sqlite references`）

- ✅ 已完成（trading-service）：
  - 修正模块/README 中 “写入 SQLite” 误导口径，明确写入 PG(tg_cards)
  - 清理代码注释中 “对齐 SQLite” 误导性表述（保留 `021_tg_cards_sqlite_parity.sql` 文件名引用）
  - 证据：提交 `49b9001e`（`docs(trading-service): remove sqlite wording`）

- ✅ 已完成（ai-service）：
  - 修正文档/脚本/注释中的 “SQLite” 误导口径，统一为 PG(tg_cards)
  - 证据：提交 `d344a96a`（`docs(ai-service): drop sqlite wording`）

- ✅ 已完成（telegram-service）：
  - 清理源代码内 “SQLite” 误导文案（日志/注释/卡片说明）
  - 修复重复启动信号检测线程：只启动一次 PG 信号引擎
  - 证据：提交 `c4bade63`（`chore(telegram-service): remove sqlite wording`）

- ✅ 已完成（sheets-service）：
  - 幂等存储口径明确为 PG（`sheets_state.sent_keys`）
  - 删除遗留 `services/consumption/sheets-service/data/remote/market_data.db`
  - 证据：提交 `c4bc4495`（`chore(sheets-service): pg-only idempotency`）

- ✅ 已完成（全局 services 说明）：
  - `services/README.md` 修正 “写入 SQLite 指标库” 误导口径
  - 证据：提交 `82e99af5`（`docs(services): update indicator store to pg`）

- ✅ 已完成（遗留文件清理）：
  - 删除 `services/compute/trading-service/libs/database/services/telegram-service/market_data.db`
  - 删除 `services/consumption/sheets-service/data/remote/market_data.db`

- ✅ 验收扫描：
  - `rg -n --hidden --no-ignore-vcs "sqlite3|aiosqlite|sqlite_master" services/.../src` 无命中（排除 `.venv/node_modules`）

## Commands（审计用命令，供复现）

- 扫描服务侧 SQLite 残留：
  - `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_engine|market_data\\.db\" services`
- 列出仓库内 `.db` 文件（排除虚拟环境/外部 repo）：
  - `find . -type d \\( -name .git -o -name .venv -o -name node_modules -o -path './assets/repo' \\) -prune -o -type f \\( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \\) -print`

## Blockers

- 无
