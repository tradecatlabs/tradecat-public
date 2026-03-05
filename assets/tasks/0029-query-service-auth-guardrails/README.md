# 任务门户：query-service-auth-guardrails

## Why（价值，100字内）

当前环境下 Query Service（`/api/v1/*`）的鉴权配置缺失会导致消费链路“看起来服务都在跑，但数据读取全 401 / 或被迫临时关鉴权裸奔”。本任务把鉴权配置、启动顺序与 preflight 守护一次性收敛成可重复执行的闭环，保证默认安全与可运维性。

## In Scope（范围）

- 修复“缺失 env → /api/v1 全 401”的结构性故障：
  - `.env` 补齐 `QUERY_SERVICE_BASE_URL / QUERY_SERVICE_AUTH_MODE / QUERY_SERVICE_TOKEN`
  - 统一“required + token”作为默认安全模式
- 启动顺序与 guardrails：
  - 统一启动链路纳入 `api-service`（避免只启动 telegram 但 query 未起）
  - 为消费端（telegram/sheets）增加 Query Service preflight（fail-fast + 可执行提示）
- 冒烟验证与门禁：`./scripts/check_env.sh` + `curl` 断言 + `./scripts/verify.sh`

## Out of Scope（不做）

- 不引入 Vault/KMS/mTLS/网关鉴权（属于更大范围的基础设施建设）
- 不改变 Query Service 现有 API 契约（仅保障“能按契约稳定工作”）
- 不把运行时密钥提交到 git（`.env` 永不纳入版本控制）

## 执行顺序（流程锁）

1. `CONTEXT.md`（现状证据与风险图谱）
2. `PLAN.md`（方案选择与回滚协议）
3. `TODO.md`（逐条执行 + 证据写入 `STATUS.md`）
4. `ACCEPTANCE.md`（验收断言对照）
5. `STATUS.md`（进度真相源）

