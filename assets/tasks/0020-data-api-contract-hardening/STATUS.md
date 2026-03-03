# STATUS - 0020 data-api-contract-hardening

## 状态机

- Status: In Progress（P0 已完成）
- Owner: Codex CLI
- Updated: 2026-03-03

## 已执行命令记录（Evidence Log）

> 按要求记录：命令 + 关键输出片段（禁止粘贴敏感 DSN/密钥）。

- `curl -s -m 2 http://127.0.0.1:8088/api/v1/health | head`
  - `success=true`；sources 探测 OK（DSN 已脱敏）
- `curl -s -m 6 http://127.0.0.1:8088/api/v1/capabilities | head`
  - 返回 cards/intervals/sources/version
- `curl -s -m 6 "http://127.0.0.1:8088/api/v1/cards/atr_ranking?interval=15m&limit=5" | head`
  - 响应中不包含 `.py` / `tg_cards` / `market_data` / `交易对` / `周期`
- `cd services/consumption/api-service && make test`
  - `9 passed`
- `services/consumption/api-service/.venv/bin/ruff check services/ --ignore E501,E402 --select E,F`
  - `All checks passed!`

## 当前阻塞（Blocked）

- 无。

## 待办（P1+）

- futures 路由统一改用 `src/query/datasources.py`（减少 `get_pg_pool()` 的直连散落）
  - 已拆分为独立任务：`assets/tasks/0021-harden-futures-datasources-fallback/`
- 旧端点（table 直通）deprecated/token 保护策略完善
  - 已拆分为独立任务：`assets/tasks/0021-harden-futures-datasources-fallback/`
