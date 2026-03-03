# STATUS - 0022 api-service-contract-cleanup

## 状态机

- Status: Done
- Owner: Codex CLI
- Updated: 2026-03-03

## 已执行命令记录（Evidence Log）

> 按要求记录：命令 + 关键输出片段（禁止粘贴敏感 DSN/密钥）。

- `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers -S`
  - 无匹配（routers 不再直连 `get_pg_pool()`）
- `rg -n "def error_response\\(.*extra" services/consumption/api-service/src/utils/errors.py -S`
  - 命中 `error_response(..., extra=...)`（保持旧调用兼容）
- `curl -s -m 4 "http://127.0.0.1:8088/api/futures/ohlc/history?symbol=BTC&interval=2h&limit=1"`
  - `...,"missing_table":{"schema":"market_data","table":"candles_2h"}}`
- `cd services/consumption/api-service && make test`
  - `9 passed`
- `services/consumption/api-service/.venv/bin/ruff check services/ --ignore E501,E402 --select E,F`
  - `All checks passed!`
- `rg -n "\\| 0015 \\|" assets/tasks/INDEX.md && sed -n '1,12p' assets/tasks/0015-unify-all-storage-to-postgres/STATUS.md`
  - Index 与任务 STATUS 状态一致（`In Progress`）
- `cd services/consumption/api-service && ./scripts/start.sh status`
  - API 运行中（日志无异常）

## 当前阻塞（Blocked）

- 无。
