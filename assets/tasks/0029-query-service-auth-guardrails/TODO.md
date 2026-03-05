# TODO - query-service-auth-guardrails

> 规则：每一行遵循  
> `[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

## P0（先止血：恢复 required+token 的“默认安全可用”）

- [ ] P0: 记录基线：`.env` 缺失 Query Service 关键键 | Verify: `grep -E '^(QUERY_SERVICE_BASE_URL|QUERY_SERVICE_AUTH_MODE|QUERY_SERVICE_TOKEN)=' -n assets/config/.env || true` | Gate: 输出写入 `STATUS.md`（禁止包含 token 值）
- [ ] P0: 生成 token（本地，不入库）并写入 `assets/config/.env` | Verify: `openssl rand -hex 32`（或 python secrets） | Gate: `.env` 权限保持 600；git diff 不出现 `.env`
- [ ] P0: 运行环境门禁 | Verify: `./scripts/check_env.sh` | Gate: Query Service 相关项全绿（required 模式下 token 必须非默认）
- [ ] P0: 重启 api-service（不得用 disabled 覆盖启动） | Verify: `cd services/consumption/api-service && ./scripts/start.sh restart && ./scripts/start.sh status` | Gate: status 显示运行中
- [ ] P0: 鉴权语义双断言（无 token 拒绝/有 token 放行） | Verify: `curl -s -m 2 http://127.0.0.1:8088/api/v1/health` + `curl -s -m 2 -H "X-Internal-Token: $QUERY_SERVICE_TOKEN" http://127.0.0.1:8088/api/v1/health` | Gate: 前者 unauthorized；后者 success=true
- [ ] P0: 重启 telegram-service 重新加载 `.env` | Verify: `cd services/consumption/telegram-service && ./scripts/start.sh restart && ./scripts/start.sh status` | Gate: 最近日志无持续 unauthorized
- [ ] P0: 全仓门禁复验 | Verify: `./scripts/verify.sh` | Gate: ✅ 通过

## P1（防复发：启动顺序与 preflight guardrails）

- [ ] P1: root 启动链路纳入 api-service | Verify: `rg -n \"SERVICES=\\(\" scripts/start.sh` | Gate: 默认启动包含 api-service（或显式开关并在 README/AGENTS 强制）
- [ ] P1: telegram-service 启动前增加 Query Service preflight（带 token） | Verify: `rg -n \"preflight|/api/v1/health\" services/consumption/telegram-service/scripts/start.sh` | Gate: 缺 token/不可达时 fail-fast 并打印修复指引
- [ ] P1: sheets-service 同步 preflight（如启用） | Verify: `rg -n \"preflight|/api/v1/health\" services/consumption/sheets-service/scripts/start.sh` | Gate: 行为与 telegram 一致
- [ ] P1: 新增一键冒烟脚本 | Verify: `ls -la scripts/smoke_query_service.sh` | Gate: 脚本可运行且不打印 token

## P2（文档收口）

- [ ] P2: README/AGENTS 补齐“Query Service 必需配置与启动顺序” | Verify: `rg -n \"QUERY_SERVICE_BASE_URL|QUERY_SERVICE_TOKEN\" README.md AGENTS.md assets/config/.env.example` | Gate: 文档与示例一致

## Parallelizable（可并行）

- P0 的“token 生成 + check_env”与“api-service 重启”必须串行；P1 的脚本改动可并行进行（但最终需统一冒烟验证）。

