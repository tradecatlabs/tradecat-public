# TODO - futures-last-utc-openapi-hardening

> 规则：每一行遵循  
> `[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

## P0（先做：期货 *_last 缺表/缺数据闭环）

- [ ] P0: 对齐“运行库 DSN”并落盘 | Verify: `psql "$DATABASE_URL" -c "SELECT current_database(), inet_server_addr(), inet_server_port();"` | Gate: 输出写入 `STATUS.md`（禁止包含密码）
- [ ] P0: 验证 Timescale 扩展存在 | Verify: `psql "$DATABASE_URL" -c "SELECT extname FROM pg_extension WHERE extname='timescaledb';"` | Gate: 返回 1 行
- [ ] P0: 验证 source 表存在且近 1 天有数据 | Verify: `psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM market_data.binance_futures_metrics_5m WHERE create_time > (NOW() AT TIME ZONE 'UTC') - INTERVAL '1 day';"` | Gate: count > 0
- [ ] P0: 执行 CAGG DDL（幂等） | Verify: `psql "$DATABASE_URL" -f assets/database/db/schema/007_metrics_cagg_from_5m.sql` | Gate: 无报错；`to_regclass` 可见
- [ ] P0: 确认 5 个 *_last 视图存在 | Verify: `psql "$DATABASE_URL" -c "SELECT to_regclass('market_data.binance_futures_metrics_15m_last'), to_regclass('market_data.binance_futures_metrics_1h_last'), to_regclass('market_data.binance_futures_metrics_4h_last'), to_regclass('market_data.binance_futures_metrics_1d_last'), to_regclass('market_data.binance_futures_metrics_1w_last');"` | Gate: 均非 NULL
- [ ] P0: 若视图无数据，执行 refresh/backfill（默认 30 天，必要时分段） | Verify: `psql "$DATABASE_URL" -c "\\df refresh_continuous_aggregate"` | Gate: 能找到函数签名；refresh 后 `COUNT(*)>0`
- [ ] P0: 抽样验证 1h_last 读取得到最新 bucket | Verify: `psql "$DATABASE_URL" -c "SELECT bucket, symbol FROM market_data.binance_futures_metrics_1h_last ORDER BY bucket DESC LIMIT 5;"` | Gate: 返回行数 > 0

## P1（再做：UTC 时间口径统一）

- [ ] P1: 审计 scheduler 的 NOW() 使用点 | Verify: `grep -n \"NOW()\" services/compute/trading-service/src/simple_scheduler.py` | Gate: 列出所有命中行号并写入 `STATUS.md`
- [ ] P1: 修改窗口比较为 UTC 基准（仅针对 timestamp without time zone 列） | Verify: `grep -n \"NOW()\" services/compute/trading-service/src/simple_scheduler.py` | Gate: 仅保留 `(NOW() AT TIME ZONE 'UTC')` 用法（或明确注释“该列为 timestamptz 可用 NOW()”）
- [ ] P1: trading-service 门禁 | Verify: `cd services/compute/trading-service && make check` | Gate: ✅ 全绿

## P2（最后做：OpenAPI/示例/可观测）

- [ ] P2: 补齐 /api/v1 端点 OpenAPI 元数据（summary/description/response_model） | Verify: 启动 api-service 后 `curl -s http://127.0.0.1:8088/openapi.json | head` | Gate: JSON 可读；包含关键 /api/v1 路由
- [ ] P2: 更新 `services/consumption/api-service/docs/API_EXAMPLES.md` 与真实响应一致 | Verify: 以 `curl` 抽样对比（脱敏落盘） | Gate: examples 与实际字段一致
- [ ] P2: 全仓门禁复验 | Verify: `./scripts/verify.sh` | Gate: ✅ 通过

## Parallelizable（可并行）

- P0 的“DDL/存在性验证”与 P1 的“scheduler 审计”可并行，但 refresh/backfill 需独占窗口执行。

