# STATUS - 0021 harden-futures-datasources-fallback

## 状态机

- Status: Done
- Owner: Codex CLI
- Updated: 2026-03-03

## 已执行命令记录（Evidence Log）

> 按要求记录：命令 + 关键输出片段（禁止粘贴敏感 DSN/密钥）。

- `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/{futures_metrics,open_interest,funding_rate,ohlc}.py -S`
  - futures 路由存在 `get_pg_pool()` 直连
- `rg -n "_last" services/consumption/api-service/src/routers/{futures_metrics,open_interest,funding_rate}.py -S`
  - 多周期依赖 `*_last` 表
- `rg -n "@router\\.get\\(\"/indicators" services/consumption/api-service/src/routers/query_v1.py -n`
  - indicators 直通端点仍存在
- `rg -n "MARKET\\s*=\\s*DataSourceSpec" services/consumption/api-service/src/query/datasources.py -n`
  - datasources 已具备 MARKET 数据源定义
- `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/{futures_metrics,open_interest,funding_rate,ohlc}.py -S`
  - 已无匹配：四个 futures 路由已不再直连 `get_pg_pool()`
- `cd services/consumption/api-service && make test`
  - `6 passed`
- `services/consumption/api-service/.venv/bin/ruff check services/ --ignore E501,E402 --select E,F`
  - `All checks passed!`

## 当前阻塞（Blocked）

- 无。
