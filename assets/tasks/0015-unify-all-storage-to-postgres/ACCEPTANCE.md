# ACCEPTANCE（验收标准）

## 1) 原子断言（Atomic Assertions）

### A1. 指标库完全 PG 化（无 SQLite 依赖）

- 断言：当 `INDICATOR_STORE_MODE=pg` 且 `INDICATOR_READ_SOURCE=pg` 时：
  - trading-service 写入 `tg_cards.*`，不再写 `market_data.db`
  - telegram-service / sheets-service / api-service / ai-service 均从 PG 读取指标表
- Verify（示例）：
  - `rg -n "import sqlite3|sqlite3\\.connect" services/compute/trading-service services/consumption services/compute/ai-service` 无命中（或仅保留兼容层、且默认不走）
  - `psql "$DATABASE_URL" -c "\\dt tg_cards.*" | wc -l` > 0
  - 对任一表：`psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM tg_cards.\\\"基础数据同步器.py\\\";"` 返回非 0（按实际数据）

### A2. 信号状态库完全 PG 化（替代 cooldown/subs/history 三个 .db）

- 断言：signal-service 持续运行 24h 期间：
  - 冷却读写、订阅读写、历史写入均落 PG（`signal_state.*`）
  - 不再创建/读写 `assets/database/services/signal-service/*.db`
- Verify：
  - `psql "$DATABASE_URL" -c "\\dt signal_state.*"` 包含 `cooldown`/`signal_subs`/`signal_history`
  - `find assets/database/services/signal-service -name "*.db"` 为空（或仅保留 legacy 备份，且运行不依赖）

### A3. Sheets 幂等完全 PG 化（sent_keys）

- 断言：sheets-service 写入 Google Sheets 前后的幂等去重依赖 PG 表 `sheets_state.sent_keys`（或等价表），不再依赖本地 SQLite。
- Verify：
  - `psql "$DATABASE_URL" -c "\\dt sheets_state.*"` 包含 `sent_keys`
  - 重复运行同一次导出（同一 run_id/card_key）不会重复写入（以服务日志/计数器/Sheets 行数差量验证）

### A4. API 行为对齐（无破坏）

- 断言：以下 API 行为不因迁移而改变语义（字段名/排序/过滤）：
  - `/supported-coins`、`/base-data`、`/signal/cooldown`、`/indicator/*`
- Verify：
  - 迁移前后对同一 symbol/interval 的响应字段集合一致（允许新增 `source=pg` 标识，但不删除既有字段）

## 2) 边缘路径（Edge Cases，至少 3 个）

1. **表名包含中文/标点/`.py`**：写入与查询均使用安全引用（避免 SQL 注入与引用错误）。
2. **缺失列/新增列**：写端保持“缺失补 NULL、多余丢弃”的兼容语义（对齐现有 SQLite writer 行为）。
3. **NaN/空字符串**：统一写入 PG 为 `NULL` 或可比较值，避免聚合/排序异常。
4. **并发写入**：多线程/多进程写入时无死锁、无长期锁等待（需要连接池与批量事务策略）。

## 3) 禁止性准则（Anti-Goals）

- 不允许因迁移导致写入频率显著下降（例如 compute 周期翻倍）。
- 不允许引入新的“隐式本地状态库”（运行后又生成新的 `.db` 作为依赖）。
- 不允许在未提供回滚策略的情况下删除/破坏现存 SQLite 数据文件。

