# README - 任务门户

## Why（价值）

0024 已把 Query Service 的“安全默认值”止血到可上线边界，但要做到“可长期跑”，仍需把环境配置、失败语义、数值口径、缓存与下游抗抖动做成**唯一语义**，否则系统会在漏配/抖动/放大请求/精度漂移时以不可预测方式失效。

## In Scope（做什么）

- 环境变量门禁：`check_env.sh` 明确校验 Query Service 鉴权与消费端配置，避免漏配即裸奔/全挂。
- 错误语义唯一化：收敛 HTTP status 策略（默认 CoinGlass 风格：HTTP 200 + body 表达错误），并用测试固化。
- 数值口径：消灭 `Decimal -> float -> str(float)` 漂移；为指标数据提供可灰度的 `numeric_mode`。
- dashboard/snapshot：加“短 TTL + 上限”的服务端缓存与并发击穿保护，降低 DB 压力与尾延迟。
- telegram 客户端：加锁 + 重试退避 + stale-if-error，提升下游抖动时的可用性。
- compute 缺口监控：缓存加锁，异常不再静默吞掉，输出显式错误状态并可观测。
- PG 预算：引入 `statement_timeout`（可配置），防止慢查询拖死服务线程/连接池。

## Out of Scope（不做什么）

- 不新增/重构数据库 schema（不做跨表大迁移）。
- 不引入 Redis/Kafka 等新基础设施（缓存先用进程内短 TTL）。
- 不重写整个 API 路由体系（只做策略收敛与关键路径治理）。
- 不修改 `assets/config/.env`（只更新模板与校验脚本）。

## 执行顺序（必须）

1) `CONTEXT.md`（现状证据与风险）
2) `PLAN.md`（选型与收敛策略）
3) `TODO.md`（逐条执行 + 验证）
4) `ACCEPTANCE.md`（验收口径）
5) `STATUS.md`（写入证据与提交点）

