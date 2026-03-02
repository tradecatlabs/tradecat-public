# CONTEXT（现状、证据、风险与假设）

## 1) 现状追溯（仓库事实 + 证据）

### 1.1 consumption 仍存在“直连 PG”的实现（必须出清）

- Telegram 侧当前通过 `PgRankingDataProvider` 直连 `tg_cards.*`：
  - `services/consumption/telegram-service/src/cards/data_provider.py:3-7`：明确声明数据源为 PG（`tg_cards`）。  
  - `services/consumption/telegram-service/src/cards/data_provider.py:263`：`class PgRankingDataProvider`（内部包含 `psycopg`、SQL 查询、表字段扫描）。  
- Sheets 侧的“幂等”当前直连 PG（`sheets_state.sent_keys`）：
  - `services/consumption/sheets-service/src/idempotency.py:6-47`：`PgIdempotencyStore` 使用 `psycopg.connect` 与 `INSERT/SELECT`。  
  - 这与“consumption 层禁止 DB 直连（只能走 Query Service）”的新增约束冲突。

### 1.2 consumption 服务之间存在不稳定耦合（需要收敛）

- api-service 当前通过动态 import 复用 telegram-service 的 `data_provider` 构建快照：
  - `services/consumption/api-service/src/routers/indicator.py:21-45`：`_ensure_telegram_imports()` + `_get_snapshot_provider()` 把 telegram-service 路径注入 `sys.path` 并 `spec_from_file_location` 加载模块。
  - 这属于“路径耦合 + 部署耦合 + 行为漂移”的高风险实现，应改为 api-service 内部的 query 层实现（单一真相源）。

### 1.3 Sheets 导出器间接依赖 telegram-service 的数据时间（需要重新定义口径）

- `services/consumption/sheets-service/src/tg_cards_exporter.py:75-109`：`get_current_time_display()` 会尝试 `from cards.data_provider import get_latest_data_time` 获取“最近一次读取到的数据时间”。  
  - 在直连 PG 被移除后，该“最近时间”应由 Query Service 响应中的 `ts_utc` 驱动（由 HTTP provider 更新模块级 latest）。

### 1.4 当前 verify 脚本未 enforce “consumption 禁止直连 PG”

- `scripts/verify.sh` 已包含“顶层目录结构守护”和“SQLite 依赖守护”（`import sqlite3` 等），但尚未对 `psycopg`/`tg_cards.*`/`market_data.*` 做消费层禁用扫描。

---

## 2) 新增硬约束（本任务必须遵守）

1) **只保留新逻辑**：移除旧直连 PG 的逻辑与代码；不保留 fallback。  
2) **唯一读出口**：除 Query Service 外，`services/consumption/**` 禁止任何 DB 连接与 SQL。  
3) **契约优先**：消费端只依赖 `/api/v1` 结构化 JSON；禁止文本伪表格与字段口径各自实现。  
4) **多数据源可扩展**：Query Service 必须可同时连接多个数据源（不止行情/指标）。

---

## 3) 风险量化表（Risk Map）

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| Query Service 成为读侧单点 | High | TG/Sheets 同时无数据；HTTP 5xx/timeout | 缓存（TTL→Redis）、超时与限流、health check、清晰错误提示 |
| 无 fallback 导致“坏就全坏” | High | Query Service 抖动时直接影响消费端 | 先把 Query Service 做到可观测/可自愈（重试上限、熔断日志），并提供回滚步骤（git revert） |
| 动态 import 耦合导致部署炸裂 | High | api-service 找不到 telegram-service 路径/模块 | 删除动态 import；在 api-service 内实现 query 层 |
| 幂等存储从 PG 迁出导致重复写 | Medium | Sheets 重复刷写/配额爆炸 | 幂等 keys 存到工作簿隐藏 tab/DeveloperMetadata；限制增长并可清理 |
| 多数据源配置漂移 | Medium | 不同 DSN 指向不同 schema/同名表冲突 | datasource registry + 明确 domain（indicators/market/other）+ health 输出每个源状态 |

---

## 4) 假设与证伪（Safe-Inference）

> 原则：即便信息缺失也不阻塞规划；但每个假设必须给出可执行证伪命令。

### A1. telegram-service 的卡片主要通过 `get_ranking_provider()` 访问数据

- 证伪命令：  
  - `rg -n "get_ranking_provider\\(" services/consumption/telegram-service/src/cards -S`

### A2. sheets-service 当前复用 telegram-service 的 cards registry（并不需要 DB 直连）

- 证伪命令：  
  - `rg -n "find_telegram_service_src|sys\\.path\\.insert\\(" services/consumption/sheets-service/src -S`

### A3. consumption 侧 PG 直连命中点主要集中在 data_provider 与 idempotency

- 证伪命令：  
  - `rg -n "psycopg|psycopg_pool|ConnectionPool" services/consumption/telegram-service/src services/consumption/sheets-service/src -S`

### A4. api-service 具备承载 Query Service 的运行与测试骨架（FastAPI/Makefile/pytest）

- 证伪命令：  
  - `ls -la services/consumption/api-service && cat services/consumption/api-service/Makefile | sed -n '1,60p'`

