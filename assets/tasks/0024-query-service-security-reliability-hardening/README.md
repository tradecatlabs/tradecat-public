# 任务门户：query-service-security-reliability-hardening

## Why（价值，100字内）

把 Query Service（api-service）从“能跑”提升到“可安全长期跑”：止血 funding-rate 假数据，修复 CORS 与 v1 鉴权 fail-open，杜绝 DSN/异常泄露；为 dashboard/snapshot 增加硬上限与缓存，统一时间/精度口径，并加固 telegram-service/compute 的并发与失败语义，避免隐性数据污染与 DoS。

## In Scope（范围）

- **语义正确性止血**：`/api/futures/funding-rate/history` 不再返回错误列（无真实数据源前返回 `not_supported`）。
- **安全默认值收敛**：
  - CORS：禁止 `* + credentials`，改为环境变量 allowlist。
  - 鉴权：v1 默认 **fail-closed**；如需关闭鉴权必须显式开关（可审计）。
  - 脱敏：health/capabilities/sources 不得回显 DSN 密码（含 libpq `key=value` DSN）。
  - 错误：对外不回显 `str(exc)`，细节仅进日志（带 trace_id）。
- **可靠性/资源上限**：为 `/api/v1/dashboard`、`/api/v1/symbol/*/snapshot` 增加参数硬上限 + 短 TTL 缓存（避免 cards×intervals×symbols 放大）。
- **边界正确性**：`startTime/endTime` 允许 `0`，避免 truthy 判断导致过滤失效。
- **精度口径治理**：避免 `Decimal → float → str(float)` 的不可控漂移；给出契约升级/兼容策略并落地单测。
- **消费侧抗抖动**：telegram-service QueryServiceClient 增加锁/退避重试/stale-if-error；compute futures_gap_monitor 去除静默吞异常 + 缓存并发保护。
- **测试与门禁**：补齐最小单测/集成测试与可执行验证命令；文档同步 `.env.example` 与运行说明。

## Out of Scope（不做）

- 不引入新的鉴权体系（mTLS/OIDC/RBAC）——仅收敛现有 `X-Internal-Token` 模型到“安全默认值”。
- 不重构为消息队列/事件总线；不做观测体系的大建设（只做必要日志/错误码与最小指标）。
- 不在本任务内“补齐真实 funding rate 采集链路”（若缺源数据，只止血并给出接入规划）。

## 执行顺序（强制）

1. `CONTEXT.md`（现状证据与风险）
2. `PLAN.md`（方案选择与回滚）
3. `TODO.md`（逐条执行 + 验证门禁）
4. `ACCEPTANCE.md`（验收断言对照）
5. `STATUS.md`（记录命令与证据）

