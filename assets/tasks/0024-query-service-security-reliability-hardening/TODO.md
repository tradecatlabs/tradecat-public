# TODO - 微步骤执行清单

> 每条遵循：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`  
> Parallelizable：标注可并行执行的步骤。

## P0（阻塞/高风险，必须优先）

- [x] P0: funding-rate 止血为 not_supported | Verify: `cd services/consumption/api-service && pytest -q -k funding_rate_not_supported` | Gate: 返回 `funding_rate_not_supported` 且不再冒充 funding_rate 列
- [x] P0: CORS 收敛为 allowlist + 禁止 credentials | Verify: `cd services/consumption/api-service && pytest -q -k cors_default` | Gate: 默认不对任意 Origin 下发 ACAO
- [x] P0: v1 鉴权改为 fail-closed（默认 required） | Verify: `cd services/consumption/api-service && pytest -q -k v1_requires_token_by_default` | Gate: 未带 token 时拒绝
- [x] P0: DSN 脱敏支持 key=value DSN | Verify: `cd services/consumption/api-service && pytest -q -k redact_dsn_scrubs_password_in_libpq` | Gate: 响应/日志不出现明文密码
- [x] P0: 异常/错误不回显 `str(exc)`（含 legacy /api/futures/*） | Verify: `cd services/consumption/api-service && rg -n \"\\{e\\}\" src/routers || true` | Gate: 路由层不拼接异常文本
- [x] P0: dashboard/snapshot 参数硬上限 | Verify: `cd services/consumption/api-service && pytest -q -k too_many_items` | Gate: 超限返回 `too_many_items` 且不触发 500
- [x] P0: futures 路由 startTime/endTime 支持 0 | Verify: `cd services/consumption/api-service && pytest -q -k end_time_zero_is_applied` | Gate: 参数 0 被当作“已传入”

## P1（稳定性/正确性收益大）

- [ ] P1: open_interest 数值不再 float→str(float) 漂移 | Verify: 对比修复前后 JSON 表示（无科学计数法） | Gate: 字符串稳定
- [ ] P1: dao Decimal 输出策略（兼容模式）落地 + 单测 | Verify: `cd services/consumption/api-service && make test` | Gate: 覆盖 Decimal 精度用例
- [ ] P1: telegram QueryServiceClient 加锁+重试+stale-if-error | Verify: 故障注入（API 500/超时） | Gate: Telegram 仍输出（stale），无崩溃
- [ ] P1: futures_gap_monitor 加锁+显式错误输出 | Verify: 断 DB 跑指标 | Gate: 不再静默 `{}`，日志有 warning
- [ ] P1: 错误语义收敛（按 PLAN 选型 A 或 B） | Verify: 抽样 10 个错误场景 | Gate: HTTP/status 策略一致且文档更新

## P2（可维护性/工程化）

- [ ] P2: 移除 sys.path.insert 运行时 hack（改部署 PYTHONPATH/包化） | Verify: `python -m` 方式启动服务 | Gate: imports 正常
- [ ] P2: statement_timeout 引入（防慢查询拖死） | Verify: `SELECT pg_sleep(...)` 故障注入 | Gate: 请求在预算内失败

## 并行建议（Parallelizable）

- CORS/鉴权/DSN/异常收敛可并行（但最终需要联调验证）。
- telegram-service 与 trading-service 的并发/失败语义改造可并行。
- 单测与文档同步可与代码改动并行推进，但必须在合并前全绿。
