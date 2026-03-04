# STATUS - 0023 query-service-v1-hardening-cagg

## 状态机

- Status: Not Started
- Owner: (待分配)
- Updated: 2026-03-04

## 证据存证（Planning 阶段只读审计）

### 已执行命令（本地）

- `nl -ba assets/database/db/schema/007_metrics_cagg_from_5m.sql | sed -n '1,120p'`
- `nl -ba services/consumption/api-service/src/routers/open_interest.py | sed -n '1,120p'`
- `nl -ba services/consumption/api-service/docs/API_EXAMPLES.md | sed -n '1,40p'`
- `nl -ba services/consumption/vis-service/src/templates/registry.py | sed -n '320,360p'`
- `nl -ba services/consumption/api-service/src/query/datasources.py | sed -n '1,110p'`
- `nl -ba services/compute/trading-service/src/core/async_full_engine.py | sed -n '240,270p'`
- `nl -ba services/compute/trading-service/src/core/storage.py | sed -n '55,85p'`
- `nl -ba services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py | sed -n '30,60p'`

### 关键观察（摘要）

- 007 DDL 已提供 CAGG 视图定义，但是否已在运行库执行/refresh 未知（需按 TODO 证伪）。
- vis-service 仍调用 `/api/futures/ohlc/history`（需迁移到 `/api/v1` wrapper）。
- `API_EXAMPLES.md` Base URL 仍为 8089，已与现行服务端口漂移。
- `datasources.ALL_SOURCES` 包含 `OTHER`，未配置时 health 输出会出现 `missing_env:QUERY_PG_OTHER_URL` 噪音。
- trading-service 对 `timestamp without time zone` 的窗口过滤存在 `NOW()` 与 UTC 基准混用，需统一。

## 阻塞项（Blocked）

- 无（执行阶段需要服务器 SSH + psql 权限）。

