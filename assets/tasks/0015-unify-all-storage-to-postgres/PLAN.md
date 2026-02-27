# PLAN（方案、路径与回滚）

## 1) 方案对比（至少两种）

### 方案 A：阶段化灰度迁移（推荐）

**核心思路**：先把 PG 作为“真相源”跑起来，再逐步切读、最后再移除 SQLite。

Pros：
- 风险可控（可 dual-write/影子读/回滚）
- 可对账（SQLite vs PG 做一致性校验）
- 最少停机

Cons：
- 迁移期系统更复杂（同时维护两套后端）

### 方案 B：一刀切切换（激进）

**核心思路**：直接删除/禁用 SQLite 路径，所有服务只用 PG。

Pros：
- 实现周期短，复杂度一次性收敛

Cons：
- 风险极高（任何遗漏点都会在线上炸裂）
- 回滚成本大（需要重新启用 SQLite 与补数据）

**选择**：采用 **方案 A**，但以“最终达到 B 的效果”为目标（迁移完成后再删除 SQLite 代码路径）。

## 2) 目标数据流（Mermaid）

```mermaid
flowchart LR
  subgraph PG[PostgreSQL (DATABASE_URL)]
    MD[market_data.*]
    TG[tg_cards.*]
    SS[signal_state.*]
    SH[sheets_state.*]
  end

  IN[ingestion/*] --> MD
  TR[compute/trading-service] -->|write indicators| TG
  SI[compute/signal-service] -->|cooldown/subs/history| SS
  TGSRV[consumption/telegram-service] -->|read| TG
  API[consumption/api-service] -->|read| TG
  SHEETS[consumption/sheets-service] -->|read + idempotency| TG
  SHEETS --> SH
  AI[compute/ai-service] -->|read| TG
```

## 3) 原子变更清单（文件级，执行 Agent 用）

### 3.1 新增/调整 PG DDL（以 `assets/database/db/schema/` 为入口）

- 新增：`022_signal_state.sql`
  - `signal_state.cooldown`（替代 `cooldown.db`）
  - `signal_state.signal_subs`（替代 `signal_subs.db`）
  - `signal_state.signal_history`（替代 `signal_history.db`）
- 新增：`023_sheets_state.sql`
  - `sheets_state.sent_keys`（替代 `idempotency.db`）
  - （可选）`sheets_state.outbox`（用于异步写 Sheets 的幂等/补写）
- （可选）`024_tg_cards_indexes.sql`：为高频查询字段补索引（按真实查询路径决定）

### 3.2 服务代码改动点（只列“必须改”的）

- `services/compute/signal-service/src/storage/cooldown.py`：实现 PG 版存储（保留接口不变）。
- `services/compute/signal-service/src/storage/subscription.py`：实现 PG 版订阅管理（JSONB/数组存储 tables）。
- `services/compute/signal-service/src/storage/history.py`：实现 PG 版历史记录（timestamp/索引/保留策略）。
- `services/consumption/sheets-service/src/idempotency.py`：改为 PG 表 `sent_keys`。
- `services/consumption/sheets-service/src/remote_db.py`：迁移到“直连 PG 作为数据源”（可保留 ssh 模式作为临时兼容，但默认 off）。
- `services/consumption/api-service/src/routers/base_data.py`：从 `tg_cards."基础数据同步器.py"` 读（替代 sqlite）。
- `services/consumption/api-service/src/routers/signal.py`：从 `signal_state.cooldown` 读（替代 sqlite）。
- `services/consumption/api-service/src/routers/coins.py`：fallback 从 PG 读（替代 sqlite）。
- `services/compute/ai-service/src/data/fetcher.py`：指标数据读取改为 PG（沿用 telegram-service 的 PG provider 或复用统一读模块）。

### 3.3 配置与运维口径

- 统一开关策略（目标）：默认 `INDICATOR_STORE_MODE=pg`、`INDICATOR_READ_SOURCE=pg`
- 引入新的 state schema 配置（如 `SIGNAL_STATE_PG_SCHEMA=signal_state`、`SHEETS_STATE_PG_SCHEMA=sheets_state`，或固定常量）
- 清理/更新 `.env.example`、README、运维手册，明确不再依赖 `.db` 文件。

## 4) 灰度切换策略（推荐顺序）

1. **准备阶段**：PG 建表（`tg_cards` 已有；新增 `signal_state`/`sheets_state`）。
2. **双写阶段（dual-write）**：trading-service 写 `dual`（SQLite+PG），并跑对账脚本确保一致。
3. **影子读阶段（shadow read）**：读端仍用 SQLite，但后台对同请求在 PG 上跑一次校验（只打日志，不影响主响应）。
4. **切读阶段（pg-read）**：读端切 PG（保留 SQLite fallback 仅用于紧急回滚）。
5. **PG-only**：写端切 `pg`，并冻结 SQLite 文件（只读备份）。
6. **删除 SQLite**：移除 sqlite 代码路径、移除 `.db` 产物、收敛文档。

## 5) 回滚协议（必须可执行）

- **读端回滚**：将 `INDICATOR_READ_SOURCE=sqlite`（或恢复旧版本服务），立即恢复读取 SQLite。
- **写端回滚**：将 `INDICATOR_STORE_MODE=dual` 或 `sqlite`，保证 SQLite 仍有新数据。
- **状态库回滚**：保留 state 数据写入双写窗口期（PG+SQLite），确保切换不丢订阅/冷却。

> 强制要求：任何“删除/禁用 SQLite”的动作只能发生在完成对账与至少 24h 影子读验证之后。

