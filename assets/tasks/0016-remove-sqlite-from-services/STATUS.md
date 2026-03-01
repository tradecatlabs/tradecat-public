# STATUS：remove-sqlite-from-services

Status: Not Started

## Live Evidence（已完成的只读审计记录）

> 说明：本任务当前阶段仅完成“影响面证据收集”，未对业务代码做任何修改。

- 命中点（signal-service）：
  - `services/compute/signal-service/src/events/types.py:28` 默认 `source="sqlite"`
  - `services/compute/signal-service/tests/test_events.py:149` 引用不存在的 `src.engines.sqlite_engine`
  - `services/compute/signal-service/tests/test_history.py:10` 引用不存在的 `SignalHistory`
- 命中点（api-service docs）：
  - `services/consumption/api-service/docs/改动1.md:207` “psycopg + sqlite3”
  - `services/consumption/api-service/docs/改动1.md:229-231` 端点映射到 SQLite
- 运行态遗留文件（不一定被代码消费）：
  - `services/consumption/sheets-service/data/remote/market_data.db`
  - `services/compute/trading-service/libs/database/services/telegram-service/market_data.db`

## Commands（审计用命令，供复现）

- 扫描服务侧 SQLite 残留：
  - `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_engine|market_data\\.db\" services`
- 列出仓库内 `.db` 文件（排除虚拟环境/外部 repo）：
  - `find . -type d \\( -name .git -o -name .venv -o -name node_modules -o -path './assets/repo' \\) -prune -o -type f \\( -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \\) -print`

## Blockers

- 无（等待执行阶段按 TODO 逐项落地）

