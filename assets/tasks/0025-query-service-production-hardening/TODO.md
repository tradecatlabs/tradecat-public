# TODO - 微步骤执行清单

> 每条遵循：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

## P0（阻塞/高风险）

- [x] P0: 更新 `check_env.sh` 增加 Query Service/消费端必配校验 | Verify: `./scripts/check_env.sh` | Gate: 缺 `QUERY_SERVICE_BASE_URL`/required 模式缺 token 时脚本失败（exit!=0）
- [x] P0: 错误语义统一为 HTTP 200（validation/general exception） | Verify: `cd services/consumption/api-service && make check` | Gate: 新增测试断言所有错误 HTTP 200
- [x] P0: 文档同步（README/README_EN）补齐鉴权与门禁口径 | Verify: `rg -n \"QUERY_SERVICE_AUTH_MODE\" README.md README_EN.md` | Gate: 文档与 `.env.example` 一致

## P1（稳定性/正确性）

- [ ] P1: open_interest 去 float 漂移（Decimal 保真） | Verify: `cd services/consumption/api-service && pytest -q -k open_interest` | Gate: 返回字符串稳定，不出现科学计数法
- [ ] P1: 引入 `QUERY_NUMERIC_MODE`（float|string）并补单测 | Verify: `cd services/consumption/api-service && pytest -q -k numeric_mode` | Gate: 两种模式均通过
- [ ] P1: dashboard/snapshot 加短 TTL 缓存+上限+击穿锁 | Verify: `cd services/consumption/api-service && pytest -q -k cache` | Gate: 同参数二次请求不重复计算
- [ ] P1: telegram QueryServiceClient 加锁+重试+stale-if-error | Verify: `cd services/consumption/telegram-service && make check` | Gate: 故障注入下仍可返回 stale（或不崩溃）
- [ ] P1: futures_gap_monitor 缓存加锁 + 禁止 silent fallback | Verify: `cd services/compute/trading-service && make check` | Gate: DB 异常时输出显式 error，日志有 warning

## P2（工程化/可维护性）

- [ ] P2: datasources 引入 statement_timeout（可配置） | Verify: 故障注入 `pg_sleep` | Gate: 请求在预算内失败，不拖死
- [ ] P2: sys.path 注入收敛到单点入口 | Verify: `rg -n \"sys\\.path\\.insert\" services | wc -l` | Gate: 数量显著减少且 imports 不回归

## 并行建议（Parallelizable）

- P1 的 telegram 与 compute 可并行推进，但必须在合并前分别跑各自门禁。
