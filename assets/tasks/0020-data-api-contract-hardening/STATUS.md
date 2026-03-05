# STATUS - 0020 data-api-contract-hardening

## 状态机

- Status: Done（P0/P1 已完成；P2 可选）
- Owner: Codex CLI
- Updated: 2026-03-05

## 已执行命令记录（Evidence Log）

> 按要求记录：命令 + 关键输出片段（禁止粘贴敏感 DSN/密钥）。

- `curl -s -m 2 http://127.0.0.1:8088/api/v1/health | head`
  - `success=true`；sources 探测 OK（不记录明文 DSN）
- `curl -s -m 6 http://127.0.0.1:8088/api/v1/capabilities | head`
  - 返回 cards/intervals/sources/version
- `curl -s -m 6 "http://127.0.0.1:8088/api/v1/cards/atr_ranking?interval=15m&limit=5" | head`
  - 响应中不包含 `.py` / `tg_cards` / `market_data` / `交易对` / `周期`
- `curl -s -m 2 http://127.0.0.1:8088/openapi.json | rg -n "\"/api/v1/dashboard\"" | head -n 1`
  - 命中 `/api/v1/dashboard`（OpenAPI 已暴露契约端点）
- `rg -n "QUERY_DASHBOARD_CACHE_TTL_SEC|QUERY_SNAPSHOT_CACHE_TTL_SEC|_DASHBOARD_CACHE|_SNAPSHOT_CACHE|_get_inflight_lock" services/consumption/api-service/src/query/service.py | head`
  - dashboard/snapshot 已实现短 TTL 缓存 + in-flight lock（降低 N×M×K 放大）
- `cd services/consumption/api-service && make test`
  - `9 passed`
- `services/consumption/api-service/.venv/bin/ruff check services/ --ignore E501,E402 --select E,F`
  - `All checks passed!`

## 当前阻塞（Blocked）

- 无。

## 待办（P2，可选）

- 无。
