# STATUS - 0026 closeout-cagg-consumption-contract

## 当前状态

- 状态：In Progress
- 最后更新：2026-03-05
- 基线提交：2602689d
- Owner：TBD

## 证据存证（执行过程中填写）

> 记录所有已执行命令与关键输出片段；禁止写入明文 DSN 密码/Token。

- `git status --porcelain`（执行开始时）：
  - `M assets/tasks/INDEX.md`
  - `?? assets/tasks/0026-closeout-cagg-consumption-contract/`
- `git rev-parse --short HEAD`: `2602689d`
- `date -u +%Y-%m-%dT%H:%M:%SZ`: `2026-03-05T02:42:54Z`
- DSN 对齐探测（不回显明文）：
  - `.env` 文件：`assets/config/.env` 存在
  - `DATABASE_URL`: file_set=true（process_set=false）
  - `QUERY_PG_MARKET_URL`: file_set=false（process_set=false）→ api-service MARKET 回退 `DATABASE_URL`
  - `QUERY_PG_INDICATORS_URL`: file_set=false（process_set=false）→ api-service INDICATORS 回退 `DATABASE_URL`
- `psql "$DATABASE_URL" -c "SELECT 1"`: ✅ 通过
- `psql "$DATABASE_URL" -Atc "SELECT extversion FROM pg_extension WHERE extname='timescaledb';"`: `2.22.1`
- `psql "$DATABASE_URL" -Atc "SELECT to_regclass('market_data.binance_futures_metrics_5m'), count(*) FROM market_data.binance_futures_metrics_5m;"`:
  - `market_data.binance_futures_metrics_5m | 97869617`
- `psql "$DATABASE_URL" -Atc "SELECT to_regclass(...*_last...);"`:
  - `15m/1h/4h/1d/1w *_last` 均存在（to_regclass 非空）
- `psql "$DATABASE_URL" -Atc "SELECT iv, max(bucket) FROM ...*_last..."`（窗口最新点）：
  - `15m`: `2026-03-05 02:15:00`
  - `1h`: `2026-03-05 01:00:00`
  - `4h`: `2026-03-04 20:00:00`
  - `1d`: `2026-03-04 00:00:00`
  - `1w`: `2026-02-23 00:00:00`
- 说明：因运行库内已存在且有数据，本次未重复执行 `assets/database/db/schema/007_metrics_cagg_from_5m.sql` 与手动 refresh/backfill
- api-service 重启（生效最新代码）：
  - `make restart`（PID 1288106 → 2053376）
  - 本地开发模式：以 `QUERY_SERVICE_AUTH_MODE=disabled` 重启（便于无 token 冒烟，sources 中不再输出 optional OTHER 噪音）
- `curl -s -m 2 http://127.0.0.1:8088/api/v1/health | head`:
  - `success=true`，sources 仅包含 `indicators/market`
- `curl -s -m 2 http://127.0.0.1:8088/api/v1/capabilities | head`:
  - `success=true`，未出现 `missing_table:binance_futures_metrics_*_last`
- `curl -s -m 2 "http://127.0.0.1:8088/api/futures/open-interest/history?symbol=BTC&interval=1h&limit=2" | head`:
  - `success=true`
- `./scripts/verify.sh`: ✅ 通过（consumption 无 PG 直连/无 legacy `/api/futures/`）
- `cd services/consumption/api-service && make check`: ✅ 通过（`26 passed`）
- `cd services/consumption/telegram-service && make check`: ✅ 通过（`3 passed`）
- `cd services/compute/trading-service && make check`: ✅ 通过（`2 passed, 1 skipped`）

## 阻塞详情（如有）

- Blocked by: _None_
- Required Action: _None_
