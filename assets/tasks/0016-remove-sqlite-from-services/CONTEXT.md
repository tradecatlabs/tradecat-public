# CONTEXT：服务侧 SQLite 残留清理

## 现状结论（基于仓库扫描）

- 核心运行链路已是 **PG-only**：
  - trading-service 写 `tg_cards.*`
  - signal-service 写 `signal_state.*`
  - sheets-service 幂等写 `sheets_state.*`
  - telegram/api/vis/ai 侧读取 `DATABASE_URL` 指向的 PG
- 但服务侧仍存在 **SQLite 时代残留**，主要集中在：
  1) `signal-service` 的测试与事件默认字段仍假设 “sqlite”  
  2) `api-service` 文档仍把多个端点映射为 SQLite  
  3) `sheets-service` 目录下存在历史 remote sqlite 文件与 local_meta 中的遗留字段（代码不消费但会误导）  
  4) `trading-service` 目录下仍存在历史 `market_data.db` 文件副本（代码不引用但会误导）
  5) `nofx-dev` 是外部预览镜像，内部自用 SQLite（不应被当作 TradeCat 核心链路）

## 关键证据（文件定位）

### signal-service（SQLite 残留：默认值 + 测试）

- `services/compute/signal-service/src/events/types.py:28`：`SignalEvent.source` 默认 `"sqlite"`  
- `services/compute/signal-service/src/events/types.py:78`：`from_dict()` 默认 `"sqlite"`  
- `services/compute/signal-service/tests/test_events.py:23`：断言默认 source 为 `"sqlite"`  
- `services/compute/signal-service/tests/test_events.py:149`：引用 `src.engines.sqlite_engine`（文件不存在），并使用 `SQLiteSignalEngine`（应移除/替换）  
- `services/compute/signal-service/tests/test_history.py:10`：引用 `SignalHistory`（实现不存在），并以 `history.db` 文件作为存储（应改为 PG mock/unit 测试或移除）

### api-service（文档残留：数据源映射仍写 SQLite）

- `services/consumption/api-service/docs/改动1.md:207`：技术栈包含 `sqlite3`  
- `services/consumption/api-service/docs/改动1.md:229`：`/futures/supported-coins` 映射到 SQLite  
- `services/consumption/api-service/docs/改动1.md:230`：`/indicator/*` 映射到 SQLite  
- `services/consumption/api-service/docs/改动1.md:231`：`/signal/cooldown` 映射到 SQLite

### sheets-service（运行态文件残留：不消费但误导）

- `services/consumption/sheets-service/src/idempotency.py:51`：幂等存储已明确 “只走 PG，不支持 sqlite”。  
- `services/consumption/sheets-service/data/local_meta.json:1`：含 `remote_db.*` 与 `.../remote/market_data.db` 字段（历史遗留；目前 `src/` 无对应消费代码）。
- `services/consumption/sheets-service/data/remote/market_data.db`：历史快照文件（在 `data/` 下，默认被 `.gitignore` 忽略）。

### trading-service（遗留文件：不消费但误导）

- `services/compute/trading-service/src/core/storage.py`：写入 `tg_cards`（PG-only）。  
- `services/compute/trading-service/libs/database/services/telegram-service/market_data.db`：历史副本（未发现代码引用）。

### nofx-dev（外部预览镜像：自用 SQLite）

- `services/consumption/nofx-dev/go.mod:21`：依赖 `modernc.org/sqlite`  
- `services/consumption/nofx-dev/main.go:43-44`：默认 `data/data.db`
- 根仓 `.gitignore:165` 忽略 `services/consumption/nofx-dev/`，且该目录内部自带 `.git/`（外部镜像定位）

## 约束矩阵

| 约束 | 说明 | 影响 |
| :--- | :--- | :--- |
| `.env` 不提交 | `assets/config/.env` 被 `.gitignore` 忽略 | 不能通过提交修改 `.env` 来达成“去 SQLite”，应以代码/文档口径为准 |
| 迁移脚本保留 | `scripts/migrate_sqlite_*` / `scripts/sync_market_data_to_rds.py` 仍需可用 | 验收扫描必须“限定在服务侧”，避免误伤迁移工具 |
| nofx-dev 外部镜像 | 自用 SQLite，且不属于核心链路 | 需要在验收与文档中明确排除或单独处理 |

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| 误删仍被使用的文件 | High | 线上/本地启动时报 “file not found” 或功能缺失 | 先用 `rg` 定位引用面；删除前做快照提交；必要时回滚 |
| signal-service 测试失真 | Medium | pytest 仍依赖 sqlite/不存在模块 | 将测试改为 unit + fake psycopg；或标记为 skip 并解释原因 |
| 文档口径漂移 | Medium | README/服务 docs 仍写 SQLite 数据源 | 在本任务中集中更新“数据源映射表”，并在验收里用 `rg` 约束 |
| 扫描规则误伤外部仓库/镜像 | Low | `rg` 扫描命中 nofx-dev/外部 repo | 统一在验收命令中加 glob 排除，或将 nofx-dev 迁出 `services/`（P2） |

## 假设与证伪（默认假设：SQLite 不再是核心运行依赖）

| 假设 | 证伪命令（执行后若有命中则假设不成立） |
| :--- | :--- |
| `INDICATOR_SQLITE_PATH` 已无服务代码读取 | `rg -n --hidden --no-ignore-vcs \"INDICATOR_SQLITE_PATH\" services scripts` |
| sheets-service 不再消费 `remote_db.*` | `rg -n --hidden --no-ignore-vcs \"remote_db\\.\" services/consumption/sheets-service/src` |
| trading-service 不再引用 `market_data.db` | `rg -n --hidden --no-ignore-vcs \"market_data\\.db\" services/compute/trading-service/src` |

