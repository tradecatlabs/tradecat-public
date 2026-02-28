# STATUS

状态：In Progress

## 1) 证据存证（Planning 阶段只读审计）

### 已执行命令

- `rg -n --hidden --no-ignore-vcs "^(DATABASE_URL|BINANCE_VISION_DATABASE_URL|INDICATOR_STORE_MODE|INDICATOR_READ_SOURCE|INDICATOR_SQLITE_PATH|INDICATOR_PG_SCHEMA)=" config/.env.example`
- `rg -n --hidden --no-ignore-vcs "import sqlite3" services config assets -S --glob '!**/.venv/**'`
- `find . -type f -name "*.db" -not -path "*/.venv/*" -not -path "*/dist/*"`

### 关键观察（摘要）

- 默认写端仍为 SQLite：`config/.env.example:468`（`INDICATOR_STORE_MODE=sqlite`）
- `tg_cards` PG 对齐 DDL 已存在：`assets/database/db/schema/021_tg_cards_sqlite_parity.sql`
- 运行态 SQLite 状态库仍被多服务依赖（冷却/订阅/历史/幂等/快照），详见 `CONTEXT.md`。

## 2) 阻塞项（Blocked）

无（已进入执行阶段）。

## 3) 已落地（关键里程碑）

- ✅ 新增 PG DDL：
  - `assets/database/db/schema/022_signal_state.sql`（cooldown/signal_subs/signal_history）
  - `assets/database/db/schema/023_sheets_state.sql`（sent_keys）
- ✅ signal-service 状态库切换（默认 PG，保留 sqlite 回退）：
  - `services/compute/signal-service/src/storage/cooldown.py`
  - `services/compute/signal-service/src/storage/subscription.py`
  - `services/compute/signal-service/src/storage/history.py`
- ✅ sheets-service 幂等切换（默认 PG，保留 sqlite 回退）：
  - `services/consumption/sheets-service/src/idempotency.py`
- ✅ telegram-service 信号订阅存储去重：复用 signal-service SubscriptionManager（避免重复实现/多份 DB）：
  - `services/consumption/telegram-service/src/signals/ui.py`
- ✅ api-service 读端优先 PG（base-data / supported-coins / signal-cooldown）：
  - `services/consumption/api-service/src/routers/base_data.py`
  - `services/consumption/api-service/src/routers/coins.py`
  - `services/consumption/api-service/src/routers/signal.py`
- ✅ ai-service 指标全量读取优先 PG(tg_cards)（必要时回退 SQLite）+ 修复 telegram-service 路径：
  - `services/compute/ai-service/src/data/fetcher.py`
- ✅ 一次性迁移工具（dry-run 默认）：
  - `scripts/migrate_sqlite_state_to_pg.py`

## 4) 版本证据（可回滚点）

- `git show --oneline -1`：`feat(storage): migrate runtime state/idempotency to postgres`
- `./scripts/verify.sh`：通过（语法检查 + i18n + 文档入口）
