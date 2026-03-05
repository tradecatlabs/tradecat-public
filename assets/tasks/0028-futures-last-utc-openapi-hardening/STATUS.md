# STATUS - futures-last-utc-openapi-hardening

## 当前状态

- 状态：Done
- 最后更新：2026-03-05
- Owner：TBD

## 证据存证（执行过程中填写）

> 规则：
> - 只记录“事实与可复现命令”，不记录敏感信息（DSN 密码/Token/SA JSON）。
> - 每个 Phase 通过后再进入下一 Phase。

- 基线提交：`c6b982c4`（创建任务文档）

### P0（期货 *_last 缺表/缺数据闭环）

- 运行库指纹（不含密码）：
  - `psql "$DATABASE_URL" -c "SELECT current_database(), inet_server_addr(), inet_server_port();"`
  - 输出：
    - `db=market_data host=127.0.0.1 port=5433`
- Timescale 扩展：
  - `psql "$DATABASE_URL" -c "SELECT extname FROM pg_extension WHERE extname='timescaledb';"`
  - 输出：`timescaledb`
- source 表近 1 天数据量：
  - `psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM market_data.binance_futures_metrics_5m WHERE create_time > (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day';"`
  - 输出：`1091`
- 执行 CAGG DDL（幂等）：
  - `psql "$DATABASE_URL" -f assets/database/db/schema/007_metrics_cagg_from_5m.sql`
  - 输出：视图/索引/policy 已存在（NOTICE skipping），DDL 可重复执行
- *_last 视图存在性：
  - `psql "$DATABASE_URL" -c "SELECT to_regclass(...);"`
  - 输出：15m/1h/4h/1d/1w 均存在
- refresh 工具函数存在性：
  - `psql "$DATABASE_URL" -c "\\df refresh_continuous_aggregate"`
  - 输出：`public.refresh_continuous_aggregate(...)`
- *_last 数据量（确认无需 refresh/backfill）：
  - 15m: `32885360`；1h: `8229954`；4h: `2061429`；1d: `345977`；1w: `50315`
- 抽样读取最新 bucket：
  - `psql "$DATABASE_URL" -c "SELECT bucket, symbol FROM market_data.binance_futures_metrics_1h_last ORDER BY bucket DESC LIMIT 5;"`
  - 输出：`2026-03-05 05:00:00`（BTCUSDT/ETHUSDT/SOLUSDT/BNBUSDT）

### P1（UTC 时间口径统一）

- 审计 scheduler 的 NOW() 命中行：
  - `grep -n "NOW()" services/compute/trading-service/src/simple_scheduler.py`
  - 输出：
    - `108/121/127`：candles_5m.bucket_ts（timestamptz）窗口过滤
    - `160`：binance_futures_metrics_5m.create_time（timestamp）窗口过滤（已使用 `(NOW() AT TIME ZONE 'UTC')`）
- 字段类型证据（运行库）：
  - `candles_5m.bucket_ts` = timestamptz；`binance_futures_metrics_5m.create_time` = timestamp without time zone
- 收敛动作：
  - 在 `services/compute/trading-service/src/simple_scheduler.py` 为 timestamptz 场景补充注释：对 timestamptz 使用 NOW()，对 timestamp(UTC 语义) 使用 `NOW() AT TIME ZONE 'UTC'`
- 门禁：
  - `cd services/compute/trading-service && make check`：✅ `2 passed, 1 skipped`

### P2（OpenAPI/示例对齐）

- OpenAPI：为 `/api/v1/*` 端点补齐 `summary/description/response_model`
  - 代码：
    - `services/consumption/api-service/src/schemas/models.py`：新增 `ApiEnvelope`（extra=allow，避免过滤诊断字段）
    - `services/consumption/api-service/src/routers/query_v1.py`：为 v1 端点挂载 `response_model=ApiEnvelope`
  - 验证：
    - `cd services/consumption/api-service && make start`
    - `curl -s http://127.0.0.1:8088/openapi.json | head`
    - 断言：JSON 可读；`/api/v1/*` 路由存在；响应 schema 引用 `ApiEnvelope`
- API 示例对齐：
  - 更新：`services/consumption/api-service/docs/API_EXAMPLES.md`
  - 关键修正：
    - v1 默认鉴权为 fail-closed（需 `QUERY_SERVICE_TOKEN`，或显式 `QUERY_SERVICE_AUTH_MODE=disabled`）
    - dashboard/ohlc 示例补齐 `code/msg/success/data` 统一封套
- 全仓门禁：
  - `./scripts/verify.sh`：✅ 通过

## 阻塞详情（如有）

- Blocked by: _None_
- Required Action: _None_
