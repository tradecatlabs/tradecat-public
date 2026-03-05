# STATUS - 进度真相源

## 当前状态

- 状态：In Progress
- 最后更新：2026-03-05
- 基线提交：ab5e5ac48583ce906c7bdd7a337865c8386771ef
- Owner：TBD

## 证据存证（执行过程中填写）

- `git rev-parse HEAD`: `5015cfe3564067f403044c37c5b596cd86550344`
- `./scripts/check_env.sh`: ✅ 已执行（本机环境输出缺失 `QUERY_SERVICE_BASE_URL`/`QUERY_SERVICE_TOKEN`，符合 fail-fast 门禁预期）
- `rg -n "QUERY_SERVICE_AUTH_MODE" README.md README_EN.md`: ✅ 已补齐（文档与 `.env.example` 同步）
- `./scripts/verify.sh`: ✅ 通过（本机无顶层 `.venv`/`ruff`，脚本按预期跳过）
- `cd services/consumption/api-service && make check`: ✅ 通过（ruff + pytest，`26 passed`；新增 dashboard/snapshot TTL 缓存 + 防“ignored_cards 污染缓存”测试用例）
- statement_timeout 故障注入：✅ `QUERY_PG_STATEMENT_TIMEOUT_MS=1200` + `SELECT pg_sleep(5)` → `QueryCanceled`（≈1.2s）
- `cd services/consumption/telegram-service && make check`: ✅ 通过（ruff + pytest，`3 passed`；覆盖 retry + stale-if-error）
- `cd services/compute/trading-service && make check`: ✅ 通过（pytest，`2 passed, 1 skipped`；读库失败不再静默吞掉）

## 阻塞详情（如有）

- Blocked by: _None_
- Required Action: _None_
