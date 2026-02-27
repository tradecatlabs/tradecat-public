# CONTEXT（现状、约束、风险）

## 1) 现状追溯（以仓库证据为准）

### 1.1 当前并存的持久化后端

- **PostgreSQL/TimescaleDB（原始事实与派生）**
  - `DATABASE_URL`：默认 `localhost:5433/market_data`（`config/.env.example:46`）
  - `BINANCE_VISION_DATABASE_URL`：默认 `localhost:15432/market_data`（`config/.env.example:52`）
- **SQLite（指标派生 + 运行态状态 + 幂等/快照）**
  - 指标库路径：`INDICATOR_SQLITE_PATH=assets/database/services/telegram-service/market_data.db`（`config/.env.example:462`）
  - 指标默认写入模式仍为 SQLite：`INDICATOR_STORE_MODE=sqlite`（`config/.env.example:468`）
  - 指标读取来源默认 auto：`INDICATOR_READ_SOURCE=auto`（`config/.env.example:509`）

### 1.2 关键服务仍在“正式使用”SQLite（非死代码）

- **trading-service（计算层）**
  - 写入模式 `sqlite|pg|dual`：`services/compute/trading-service/src/core/storage.py:15`
  - SQLite writer：`services/compute/trading-service/src/db/reader.py:294`
  - PG writer（`tg_cards.*`）：`services/compute/trading-service/src/db/reader.py:433`
- **signal-service（信号层）**
  - CLI 显式提供 `--sqlite/--pg`：`services/compute/signal-service/src/__main__.py:28`
  - 冷却库 `cooldown.db`：`services/compute/signal-service/src/storage/cooldown.py:45`
  - 订阅库 `signal_subs.db`：`services/compute/signal-service/src/storage/subscription.py:38`
  - 历史库 `signal_history.db`：`services/compute/signal-service/src/storage/history.py:38`
- **api-service（消费层）**
  - `base_data` 路由直连 SQLite：`services/consumption/api-service/src/routers/base_data.py:1`
  - `signal/cooldown` 直连 SQLite：`services/consumption/api-service/src/routers/signal.py:14`
  - `supported-coins` 在无全局配置时回退 SQLite：`services/consumption/api-service/src/routers/coins.py:24`
  - `indicator` 路由虽支持 `INDICATOR_READ_SOURCE=pg`，但仍保留 sqlite 分支：`services/consumption/api-service/src/routers/indicator.py:52`
- **telegram-service（消费层）**
  - 订阅开关 `signal_subs.db`：`services/consumption/telegram-service/src/signals/ui.py:49`
  - 指标读取端支持 pg/sqlite 自动切换：`services/consumption/telegram-service/src/cards/data_provider.py:1242`
- **sheets-service（消费层）**
  - 幂等库 `sent_keys` 使用 SQLite：`services/consumption/sheets-service/src/idempotency.py:7`
  - 远端 SQLite 一致性快照（ssh 远端备份再 scp）：`services/consumption/sheets-service/src/remote_db.py:144`
- **ai-service（计算层）**
  - 明确“从 SQLite 获取全部指标数据”：`services/compute/ai-service/src/data/fetcher.py:5`

### 1.3 当前工作区存在的 `.db` 文件（易造成“到底用哪份”的混淆）

- 指标库（主要）：`assets/database/services/telegram-service/market_data.db`
- 远端缓存快照：`services/consumption/sheets-service/data/remote/market_data.db`
- trading-service 内部另有一份指标库副本：`services/compute/trading-service/libs/database/services/telegram-service/market_data.db`

> 以上结果来自：`find . -name "*.db" -not -path "*/.venv/*"`（详见 `STATUS.md`）。

## 2) 目标状态定义（“单 PG”口径）

### 2.1 “单 PG”的可执行定义（本任务采用）

把**所有长期持久化/跨服务共享**的数据，统一落到 `DATABASE_URL` 指向的同一个 PostgreSQL 实例内：

- `market_data.*`：原始事实/连续聚合（现有）
- `tg_cards.*`：指标/卡片派生表（对齐 SQLite）
- `signal_state.*`：冷却/订阅/信号历史（替代 `cooldown.db/signal_subs.db/signal_history.db`）
- `sheets_state.*`：幂等 keys / outbox / 写入检查点（替代本地 SQLite 幂等库）

### 2.2 重要说明：当前仓库仍有双 PG DSN

`BINANCE_VISION_DATABASE_URL` 的存在并不等价于 SQLite；但它会让“单 PG（单实例）”在运维口径上不够纯。`PLAN.md` 中会提供：

- **方案 A（推荐）**：先“废弃 SQLite + 单库管理派生/状态”，暂不强制合并 HF/LF 两个 DSN。
- **方案 B（激进）**：合并 HF/LF 为一个 PG 实例/一个 DSN（高风险，作为后续阶段）。

## 3) 关键约束矩阵

| 约束 | 说明 | 影响 |
| :-- | :-- | :-- |
| 中文/标点表名 | `tg_cards` 表名包含中文、标点、`.py`，PG 必须双引号引用 | 写入/查询必须使用 `sql.Identifier`/引用安全 |
| 数据量/频率 | 指标表按多交易对多周期滚动写入 | PG 写入需批量化 + 索引策略，避免退化 |
| 幂等/一致性 | 现有 SQLite 写入依赖 “删+插” 与 retention 清理 | PG 侧需保持语义一致并可验证 |
| 运维可回滚 | 迁移不能一刀切 | 需要 dual-write/dual-read 灰度与回退开关 |

## 4) 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :---: | :--- | :--- |
| 数据不一致（SQLite/PG 分裂） | High | 同一表同一 (交易对,周期,数据时间) 两端不一致 | 先 dual-write + 校验对账，切读前强制一致性检查 |
| PG 写入性能下降 | High | trading-service 计算周期变长/超时 | 预建索引、批量写、减少每表连接次数、按周期清理 |
| 迁移脚本破坏性操作 | High | 误删/误截断 `tg_cards` 表 | 迁移脚本默认只追加/只读对账；破坏性操作需显式 `--i-know` |
| 状态库语义漂移 | Medium | 冷却/订阅丢失导致重复推送或漏推送 | 先“PG 写 + SQLite 读”影子模式，观察 24h 再切换 |
| 字段类型漂移 | Medium | PG 插入失败/隐式 cast 错误 | 以 `021_*.sql` 为真相源，写端做类型归一与 NaN→NULL |

## 5) 假设与证伪（执行 Agent 用）

- 假设 A：目标 PG 可创建 schema/table  
  - Verify：`psql "$DATABASE_URL" -c "CREATE SCHEMA IF NOT EXISTS signal_state;"`
- 假设 B：`tg_cards` DDL 可在目标 PG 成功执行  
  - Verify：`psql "$DATABASE_URL" -f assets/database/db/schema/021_tg_cards_sqlite_parity.sql`
- 假设 C：现有 SQLite DB 可只读访问（用于一次性迁移）  
  - Verify：`sqlite3 assets/database/services/telegram-service/market_data.db ".tables"`

