# PLAN（决策与路径）

## 1) 方案对比

### 方案 A：在 `adapters/ccxt.py` 统一异常 → ban 识别（推荐）

**做法**

- 引入 `maybe_set_ban_from_exception(e)`：
  - 对所有异常统一取 `err_str = str(e)`；
  - 若包含 `418` 或 `banned until`：`parse_ban(err_str)`，`set_ban(...)`；
  - 若包含 `429`：设置短 ban（或读取 Retry-After，如可得）；
  - 其余网络类异常走指数退避，不 set_ban。

**优点**

- 改动最小、定位最准确：修复“418 走 NetworkError 分支”这一根因。
- 复用现有全局 limiter（跨进程 `.ban_until`）。

**缺点**

- 仍可能因为 backfill 并发过高触发 ban（但能更快自愈恢复）。

### 方案 B：把 ban 处理完全下沉到 `rate_limiter.acquire()`（不推荐）

**做法**

- 在 limiter 内对“最近错误消息”做共享与解析，自动调整等待。

**优点**

- 调用方更简单。

**缺点**

- limiter 变成“业务解析中心”，耦合 ccxt/HTTP 文本；难以维护与验证。

### 方案 C：只改 backfill 并发（不推荐作为单独方案）

**做法**

- 将 `RestBackfiller(workers=8)` 固定降到 2/3。

**优点**

- 立刻降低触发 ban 的概率。

**缺点**

- 仍无法解释 “一旦 ban 发生为什么不停”；根因未修复。

---

## 2) 选择与组合（最终决策）

采用 **A 为主**，并做两个“低风险护栏”：

1) backfill 并发改为可配置，默认更保守（A 修根因 + C 减少触发概率）。
2) ws 自愈在检测到 ban 期间跳过重启（避免放大故障）。

---

## 3) 数据流/控制流（ASCII）

```text
          ┌────────────────────────────────────────────┐
          │ collectors.ws / collectors.backfill        │
          │  - gap scan → REST fetch_ohlcv → upsert    │
          │  - WS stream → batch upsert                │
          └───────────────┬────────────────────────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ adapters.ccxt     │
                 │ - acquire(weight) │
                 │ - fetch_ohlcv     │
                 │ - maybe_set_ban() │
                 └───────┬──────────┘
                         │ set_ban(until)
                         ▼
                 ┌──────────────────┐
                 │ rate_limiter      │
                 │ - .ban_until file │
                 │ - _wait_ban()     │
                 └───────┬──────────┘
                         │
                         ▼
                 ┌──────────────────┐
                 │ TimescaleAdapter  │
                 │ candles_1m write  │
                 └──────────────────┘

  start.sh daemon_loop:
    if candles_1m stale AND NOT in ban → restart ws
```

---

## 4) 原子变更清单（文件级）

> 注意：这里只写“要改什么”，不写具体代码实现。

- `services/ingestion/data-service/src/adapters/ccxt.py`
  - 抽取 `maybe_set_ban(err_str)`，在 `RateLimitExceeded` 与 `NetworkError` 分支统一调用
  - ban 触发时写清晰日志（包含 until 时间与来源）
- `services/ingestion/data-service/src/collectors/backfill.py`
  - `RestBackfiller(workers=8)` 改为从 env/settings 读取，默认收敛
  - 单个 gap 分页循环中增加“若进入 ban 冷却则退出/等待”（依赖 limiter）
- `services/ingestion/data-service/scripts/start.sh`
  - 自愈重启前检查 `.ban_until`（或通过 python 查询 limiter 状态）：ban 中则跳过本轮重启并记录日志
- `assets/config/.env.example`（如需新增可选项）
  - `DATA_SERVICE_REST_BACKFILL_WORKERS=...`
  - `DATA_SERVICE_WS_DB_SELF_HEAL_SKIP_ON_BAN=1`（示例）

---

## 5) 回滚协议

- 单 PR 回滚：`git revert <this_task_commits...>`
- 回滚后止血手段（临时）：
  - 下调 `RATE_LIMIT_PER_MINUTE/MAX_CONCURRENT`（现有 env）
  - 或临时将 `DATA_SERVICE_WS_DB_SELF_HEAL_ENABLED=0`（仅止血，不作为最终方案）

