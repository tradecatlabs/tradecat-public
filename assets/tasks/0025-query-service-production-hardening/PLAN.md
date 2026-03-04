# PLAN - 任务决策与路径

## 技术选型（关键决策）

### 1) 错误语义：统一 HTTP status

**方案 A（推荐）**：HTTP 永远 200，错误靠 body 的 `success/code/msg` 表达  
- Pros：最小破坏；符合现有大量端点与测试口径（当前 tests 均断言 200）。  
- Cons：网关/监控必须按 body 判错（需要运维/监控口径同步）。

**方案 B**：标准 HTTP status + body code  
- Pros：更工程化；标准客户端更友好。  
- Cons：改动面更大（现有端点默认 200）；回归风险更高。

结论：选择 **方案 A**，并用测试固化“所有错误 HTTP 200”。

### 2) 数值口径：Decimal 输出策略

**阶段 1（P1）**：修复最明显漂移点（OI 路由去 float）。  
**阶段 2（P1→P2）**：引入 `QUERY_NUMERIC_MODE`（float|string），默认 float 保兼容，允许灰度切换到 string 正确口径。

### 3) dashboard/snapshot：缓存策略

**方案**：进程内短 TTL 缓存（1-3 秒）+ 上限（max_entries）+ 击穿锁  
- Pros：无需新增基础设施；能显著降低“频繁刷新”导致的 DB 压力。  
- Cons：多实例下缓存不共享（但短 TTL 的目标就是抗抖动与削峰）。

### 4) telegram 客户端抗抖动

**方案**：Lock + 指数退避重试（仅网络/超时/5xx）+ stale-if-error  
- Pros：实现简单，能显著提升“短时抖动”可用性。  
- Cons：需要定义 stale 的可观测信号（字段或日志）。

### 5) statement_timeout

**方案 A（推荐）**：连接级 options 设置 `-c statement_timeout=...`  
**方案 B**：每次查询 `SET LOCAL statement_timeout`  
结论：优先 A（全局一致，易于运维配置），必要时 B 作为补充。

## 逻辑流图（ASCII）

```text
┌──────────────┐     HTTP /api/v1/*      ┌──────────────────┐
│ telegram/sheets│ ─────────────────────> │ api-service(Query)│
└──────────────┘                          └───────┬──────────┘
                                                  │
                                  SQL (pool+timeout+cache)
                                                  │
                           ┌──────────────────────┴──────────────────────┐
                           │                                               │
                  TimescaleDB market_data.*                       PostgreSQL tg_cards.*
```

## 原子变更清单（文件级）

### Phase 1：环境变量门禁

- `scripts/check_env.sh`
  - 增加 Query Service/消费端配置校验：`QUERY_SERVICE_BASE_URL`、`QUERY_SERVICE_AUTH_MODE`、`QUERY_SERVICE_TOKEN`（required 时必填且不允许默认占位）。

### Phase 2：错误语义唯一化（HTTP 200）

- `services/consumption/api-service/src/app.py`
  - validation/general exception handler 的 HTTP status 收敛为 200。
- `services/consumption/api-service/tests/*`
  - 增加覆盖：validation error / unhandled exception / unauthorized 的 HTTP status 断言。

### Phase 3：数值口径

- `services/consumption/api-service/src/routers/open_interest.py`
  - 消灭 `float(row[2])`，改用 Decimal 原始字符串表示。
- `services/consumption/api-service/src/query/dao.py`
  - 引入 `QUERY_NUMERIC_MODE` 并补单测。

### Phase 4：dashboard/snapshot 缓存

- `services/consumption/api-service/src/query/service.py`
  - 为 `dashboard_payload` 与 `symbol_snapshot_payload` 增加短 TTL 缓存 + 上限 + 击穿锁。
- `services/consumption/api-service/src/routers/query_v1.py`
  - 只做参数规范化与 cache key 统一（避免 key 爆炸）。
- tests：增加“同参数不重复计算”的断言。

### Phase 5：telegram 抗抖动

- `services/consumption/telegram-service/src/cards/data_provider.py`
  - `QueryServiceClient`：cache 加锁、重试退避、stale-if-error。
- tests：增加故障注入（httpx 抛错）用例。

### Phase 6：compute 缺口监控

- `services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py`
  - 缓存加锁；异常输出显式 error；禁止 `except: return {}`。
- tests（如该服务已有测试框架）：增加断 DB 断言。

### Phase 7：statement_timeout + sys.path 收敛（P2）

- `services/consumption/api-service/src/query/datasources.py`
  - 连接参数加入 statement_timeout（可配置）。
- 逐步收敛散落 sys.path 注入（至少做到“只剩一个入口点”）。

## 回滚协议

- 每个 Phase 独立 commit；出现事故直接 `git revert <sha>`。
- 若鉴权导致全挂：临时 `QUERY_SERVICE_AUTH_MODE=disabled` 止血（必须记录），修复消费端后再切回 required。
- 若 numeric/string 导致展示异常：保持 `QUERY_NUMERIC_MODE=float`，先让消费端兼容后再灰度切换。

