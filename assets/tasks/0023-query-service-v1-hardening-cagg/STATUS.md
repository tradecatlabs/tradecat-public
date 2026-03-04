# STATUS - 0023 query-service-v1-hardening-cagg

## 状态机

- Status: Done
- Owner: Codex CLI
- Updated: 2026-03-04

## 证据存证（Execution Evidence）

### 已执行命令（本地）

- `nl -ba assets/database/db/schema/007_metrics_cagg_from_5m.sql | sed -n '1,120p'`
- `nl -ba services/consumption/api-service/src/routers/open_interest.py | sed -n '1,120p'`
- `nl -ba services/consumption/api-service/docs/API_EXAMPLES.md | sed -n '1,40p'`
- `nl -ba services/consumption/vis-service/src/templates/registry.py | sed -n '320,360p'`
- `nl -ba services/consumption/api-service/src/query/datasources.py | sed -n '1,110p'`
- `nl -ba services/compute/trading-service/src/core/async_full_engine.py | sed -n '240,270p'`
- `nl -ba services/compute/trading-service/src/core/storage.py | sed -n '55,85p'`
- `nl -ba services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py | sed -n '30,60p'`

### 已执行命令（数据库：本地 LF TimescaleDB）

- `PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d market_data -Atc "SELECT to_regclass('market_data.binance_futures_metrics_15m_last'), to_regclass('market_data.binance_futures_metrics_1h_last'), to_regclass('market_data.binance_futures_metrics_4h_last'), to_regclass('market_data.binance_futures_metrics_1d_last'), to_regclass('market_data.binance_futures_metrics_1w_last');"`
  - `*_last` 均存在
- `PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d market_data -Atc "SELECT '15m' as iv, max(bucket) FROM market_data.binance_futures_metrics_15m_last UNION ALL SELECT '1h', max(bucket) FROM market_data.binance_futures_metrics_1h_last UNION ALL SELECT '4h', max(bucket) FROM market_data.binance_futures_metrics_4h_last UNION ALL SELECT '1d', max(bucket) FROM market_data.binance_futures_metrics_1d_last UNION ALL SELECT '1w', max(bucket) FROM market_data.binance_futures_metrics_1w_last;"`
  - `max(bucket)` 非空（有数据）

### 已执行命令（服务器：nvidia@100.91.176.84）

- `ssh -i ~/.ssh/tradecat_nvidia -o IdentitiesOnly=yes nvidia@100.91.176.84 "PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d market_data -Atc \\\"SELECT view_name FROM timescaledb_information.continuous_aggregates WHERE view_schema='market_data' AND view_name LIKE 'binance_futures_metrics_%_last' ORDER BY view_name;\\\" | head"`
  - CAGG 列表包含 `binance_futures_metrics_{15m,1h,4h,1d,1w}_last`

### 已执行命令（本地 API 冒烟）

- `curl -s -m 2 http://127.0.0.1:8088/api/health | head`
  - `success=true`
- `curl -s -m 4 "http://127.0.0.1:8088/api/futures/open-interest/history?symbol=BTC&interval=1h&limit=5" | head`
  - `success=true` 且 `data` 非空

### 关键观察（摘要）

- 已执行 `assets/database/db/schema/007_metrics_cagg_from_5m.sql` 并完成首次刷新/可读（本地与服务器均可查到）。
- vis-service 已迁移到 `/api/v1/ohlc/history`。
- `API_EXAMPLES.md` 已对齐现行端口（8088）与 v1 端点，并保留 CoinGlass 兼容端点说明。
- `datasources.OTHER` 已标记为 optional，未配置时 health/capabilities 不再输出噪音。
- trading-service 关键窗口过滤已统一以 UTC 基准比较（对 `timestamp without time zone` 的源表）。

## 阻塞项（Blocked）

- 无。
