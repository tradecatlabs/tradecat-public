# ACCEPTANCE - futures-last-utc-openapi-hardening

## 原子断言（Atomic Assertions）

### A. 期货高周期 *_last 可用且有数据（Happy Path）

1) 表存在性（运行库）
- Verify：
  - `psql "$DATABASE_URL" -c "SELECT to_regclass('market_data.binance_futures_metrics_15m_last') IS NOT NULL AS ok;"`
  - 同理对 `1h/4h/1d/1w`
- Gate：5 个查询均返回 `ok = t`

2) 数据可读性（运行库）
- Verify：以任意一个常见 symbol（例如 BTCUSDT）抽样
  - `psql "$DATABASE_URL" -c "SELECT bucket, symbol FROM market_data.binance_futures_metrics_1h_last ORDER BY bucket DESC LIMIT 5;"`
- Gate：至少返回 1 行，且 bucket 为递减时间序

3) compute 指标真实产出（trading-service）
- Verify：
  - `cd services/compute/trading-service && make check`
  - （可选）用最小脚本调用 `get_latest_metrics('BTCUSDT','1h')`
- Gate：测试全绿；期货情绪指标在非 5m 周期不再长期为空（以日志/输出为证据）

### B. scheduler 的 UTC 口径一致（Edge Cases ≥3）

1) NOW() 比较口径统一
- Verify：`grep -n "NOW()" services/compute/trading-service/src/simple_scheduler.py`
- Gate：所有用于 `timestamp without time zone` 的窗口比较，均使用 `(NOW() AT TIME ZONE 'UTC')`

2) 解析 tg_cards.* 的“数据时间”稳定
- Verify：为 `_parse_tg_ts()` 添加/更新单测（覆盖：Z、+00:00、无时区）
- Gate：输出均为 tz-aware UTC；不出现本地时区漂移

3) 边界：startTime/endTime=0 不被当作未传（若涉及）
- Verify：`cd services/consumption/api-service && make check`
- Gate：相关 time filter 单测通过（见 api-service tests）

### C. OpenAPI/示例与真实响应对齐（Anti-Drift）

1) /docs 可打开且包含 /api/v1 关键端点
- Verify：启动 api-service 后访问：
  - `curl -s http://127.0.0.1:8088/docs | head`
- Gate：HTTP 200；文档中出现 `/api/v1/` 路由（最小检查即可）

2) API_EXAMPLES.md 不包含“伪造字段/旧行为”
- Verify：抽样对比 examples 与 curl 实际输出（脱敏后落盘）
- Gate：示例与实际字段/错误码一致；不出现“表缺失却返回空成功”的漂移

## 禁止性准则（Anti-Goals）

- 禁止引入“手写聚合写库”作为默认路径（除非 Timescale CAGG 明确不可用且有书面论证）
- 禁止 drop/rename 任何事实表（仅允许新增运维脚本或执行既有 DDL）
- 禁止在任务证据中写入明文密码/Token/SA JSON

