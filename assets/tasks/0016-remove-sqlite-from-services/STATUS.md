# STATUS：remove-sqlite-from-services

Status: In Progress

## Live Evidence（已完成的只读审计记录）

> 说明：本任务已开始执行；signal-service 已完成“去 SQLite 残留”并通过单测。

- ✅ 已完成（signal-service）：
  - 修复默认事件来源：`source="sqlite"` → `source="pg"`
  - 移除/替换不存在的 sqlite_engine 测试引用
  - 重写 history 测试为纯 unit（不依赖真实数据库）
  - 证据：提交 `ea5e626c`（`fix(signal-service): remove sqlite remnants`）
  - 证据：`cd services/compute/signal-service && make test` → `15 passed`

- 待处理命中点（api-service docs）：
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
