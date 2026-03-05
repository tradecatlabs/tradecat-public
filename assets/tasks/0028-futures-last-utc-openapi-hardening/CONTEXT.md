# CONTEXT - futures-last-utc-openapi-hardening

## 现状追溯（证据驱动）

### 1) compute 侧期货情绪依赖 *_last（高周期缺表会直接“无数据”）

- 代码：`services/compute/trading-service/src/indicators/incremental/futures_sentiment.py`
  - 证据（表名分支）：
    - `grep -n "binance_futures_metrics" services/compute/trading-service/src/indicators/incremental/futures_sentiment.py`
      - `65: table = "binance_futures_metrics_5m"`
      - `68: table = f"binance_futures_metrics_{interval}_last"`

影响：
- 当运行库只存在 `market_data.binance_futures_metrics_5m` 而缺失 `*_last` 时，15m/1h/4h/1d/1w 的期货情绪指标会长期为空，进一步导致下游卡片/告警“看起来正常但其实没算”。

### 2) 仓库已存在 CAGG DDL，但不保证被执行在“正确的运行库”

- DDL：`assets/database/db/schema/007_metrics_cagg_from_5m.sql`
  - 证据（视图名与注册列表）：
    - `grep -n "binance_futures_metrics_" assets/database/db/schema/007_metrics_cagg_from_5m.sql`
      - `2: -- 视图名：market_data.binance_futures_metrics_{interval}_last`
      - `78-82: ('binance_futures_metrics_15m_last' ... 'binance_futures_metrics_1w_last' ...)`

风险根因（常见）：
- DSN 漂移：DDL 在“开发库”执行，compute/api 实际连接的是“运行库”（或反之）
- `WITH NO DATA`：视图存在但未 refresh/backfill，导致查询仍为空

### 3) scheduler 的时间窗口比较仍混用 NOW()（需要统一 UTC 基准）

- 代码：`services/compute/trading-service/src/simple_scheduler.py`
  - 证据（出现 NOW()）：
    - `grep -n "NOW()" services/compute/trading-service/src/simple_scheduler.py`
      - `108/121/127` 使用 `NOW()`（未显式 UTC）
      - `160` 使用 `(NOW() AT TIME ZONE 'UTC')`

风险：
- 当被比较的列为 `timestamp without time zone` 且数据语义为 UTC 时，`NOW()` 的时区解释会随服务器时区漂移，造成“落后/超前”的假象，进而影响“新数据判断/优先级评估/回填窗口”。

### 4) Query Service 已启用 /docs，但 OpenAPI 与示例仍可能滞后

- 代码：`services/consumption/api-service/src/app.py`
  - 证据：`grep -n "docs_url\\|redoc_url\\|/api/v1" services/consumption/api-service/src/app.py`
    - `33: docs_url="/docs"`
    - `34: redoc_url="/redoc"`
    - `101: include_router(... prefix="/api/v1")`

## 约束矩阵

| 约束 | 说明 |
|:---|:---|
| 最少修改 | 优先复用仓库既有 DDL/能力（Timescale CAGG），避免新增“手写聚合写库链路” |
| 风险控制 | DB 变更必须可回滚（不 drop 事实表；refresh 窗口可缩小分段） |
| 证据可复现 | 每一步都必须有 Verify 命令与 Gate 断言，并写入 `STATUS.md` |

## 风险量化表

| 风险点 | 严重程度 | 触发信号（Signal） | 缓解方案（Mitigation） |
| :--- | :--- | :--- | :--- |
| 对错库执行 DDL/refresh | High | `SELECT current_database()` 与服务 DSN 不一致 | 先固定 DSN，执行前后记录库名与 to_regclass |
| refresh/backfill 过重 | High | DB CPU 飙升/锁等待/慢查询 | 缩小窗口分段 refresh；低峰执行；必要时先只 backfill 7~30 天 |
| 视图存在但无数据 | Medium | `to_regclass` 存在但 `COUNT(*)=0` | 执行手动 refresh；核对 policy 是否已挂载 |
| UTC 口径漂移 | Medium | scheduler 判断“无新数据/频繁重算”与实际不符 | 统一 `(NOW() AT TIME ZONE 'UTC')`；Python 侧统一 tz-aware UTC |
| OpenAPI/示例漂移 | Low | /docs 与实际返回字段不一致 | 在 CI 门禁中加入 examples 对齐脚本或最小 smoke |

## 假设与证伪（必须能跑）

1) 假设：运行库为 `DATABASE_URL` 指向的 TimescaleDB  
   - 证伪：`psql "$DATABASE_URL" -c "SELECT current_database(), version();"`
2) 假设：`market_data.binance_futures_metrics_5m` 存在且持续写入  
   - 证伪：`psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM market_data.binance_futures_metrics_5m WHERE create_time > (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day';"`
3) 假设：Timescale 扩展可用（否则 CAGG 不成立）  
   - 证伪：`psql "$DATABASE_URL" -c "SELECT extname FROM pg_extension WHERE extname='timescaledb';"`

