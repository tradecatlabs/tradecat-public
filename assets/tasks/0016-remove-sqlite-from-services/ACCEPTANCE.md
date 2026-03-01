# ACCEPTANCE：验收标准（服务侧彻底去 SQLite）

## Happy Path（成功路径）

1. **服务代码无 SQLite 依赖**
   - Verify（逐服务）：
     - `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_master|market_data\\.db|cooldown\\.db|signal_history\\.db|signal_subs\\.db|idempotency\\.db\" services/consumption/api-service/src`
     - `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_master|market_data\\.db\" services/consumption/sheets-service/src`
     - `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_master|market_data\\.db\" services/consumption/telegram-service/src`
     - `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_master|market_data\\.db\" services/consumption/vis-service/src`
     - `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_master|market_data\\.db\" services/compute/ai-service/src`
     - `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_master|market_data\\.db\" services/compute/signal-service/src`
     - `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_master|market_data\\.db\" services/compute/trading-service/src`
   - Gate：以上命令 **均无命中**（空输出或 exit code=1）。

2. **signal-service 不再出现 sqlite 语义残留**
   - Verify：
     - `rg -n \"source: str = \\\"sqlite\\\"\" services/compute/signal-service/src/events/types.py`
     - `rg -n \"sqlite_engine|SQLiteSignalEngine\" services/compute/signal-service/tests`
   - Gate：以上命令 **均无命中**。

3. **signal-service 单测可运行（不依赖真实 PG）**
   - Verify：`cd services/compute/signal-service && make test`
   - Gate：退出码为 0（测试通过）。

4. **api-service 文档口径不再指向 SQLite**
   - Verify：`rg -n \"sqlite3|SQLite\" services/consumption/api-service/docs`
   - Gate：不再出现“SQLite 作为运行时数据源”的描述（允许在“历史迁移”语境出现，但需明确为 legacy）。

## Edge Cases（至少 3 个边缘路径）

1. **缺少 DATABASE_URL**
   - Verify：在空环境下启动相关服务（或运行其 config 解析）
   - Gate：报错信息明确指向缺失 `DATABASE_URL`，且无 SQLite 回退逻辑被触发。

2. **PG schema/表缺失**
   - Verify：将 `INDICATOR_PG_SCHEMA` 指向不存在 schema 或删表后运行（仅本地验证）
   - Gate：错误信息必须提示要执行的建表 SQL（例如 `assets/database/db/schema/021_tg_cards_sqlite_parity.sql` / `022_signal_state.sql` / `023_sheets_state.sql`）。

3. **历史遗留 `.db` 文件清理**
   - Verify：
     - `find services/consumption/sheets-service -path '*/data/*' -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3'`
     - `find services/compute/trading-service -path '*/libs/*' -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3'`
   - Gate：不存在“看起来像运行时依赖”的 `.db` 文件；若仍保留，必须在 README/注释中标记为 legacy cache（且代码不读取）。

## Anti-Goals（禁止项）

- 不允许引入新的 SQLite 依赖（Python/Go/Node 任何形式）。
- 不允许删除迁移脚本（仅允许把它们明确标记为 `tools/legacy` 或文档化其用途）。
- 不允许改写既有 PG 数据（禁止清表、禁止重算历史）。

