# STATUS - query-service-auth-guardrails

## 当前状态

- 状态：In Progress
- 最后更新：2026-03-05
- Owner：TBD

## 证据存证（执行过程中填写）

> 规则：
> - 只记录“事实与可复现命令”，不记录敏感信息（token/密码/SA JSON）。
> - 每个 Phase 通过后再进入下一 Phase。

### 基线证据（当前环境）

- `.env` 缺失键（只记录是否存在，不记录值）：
  - `grep -q '^QUERY_SERVICE_TOKEN=' assets/config/.env && echo yes || echo no` → `no`
  - `grep -q '^QUERY_SERVICE_AUTH_MODE=' assets/config/.env && echo yes || echo no` → `no`
- `.env` 当前未配置 Query Service 三件套（仅记录“无匹配”，不记录值）：
  - `grep -E '^(QUERY_SERVICE_BASE_URL|QUERY_SERVICE_AUTH_MODE|QUERY_SERVICE_TOKEN)=' -n assets/config/.env || true`
  - 输出：无匹配（空输出）
- Query Service 鉴权行为（示例，可能因当前进程启动参数而不同）：
  - 默认 required 场景：`curl -s -m 2 http://127.0.0.1:8088/api/v1/health` → `unauthorized`
  - 若临时设置 `QUERY_SERVICE_AUTH_MODE=disabled`：上述请求可能返回 `success=true`（风险：裸奔）

### P0 执行记录（留空待填）

- `.env` 补齐 Query Service 三件套（仅记录存在性与非默认）：
  - `QUERY_SERVICE_BASE_URL=http://127.0.0.1:8088`
  - `QUERY_SERVICE_AUTH_MODE=required`
  - `QUERY_SERVICE_TOKEN_set=true`（非默认占位值）
  - 验证命令（不回显 token）：
    - `python3 - <<'PY' ... print(QUERY_SERVICE_TOKEN_set/QUERY_SERVICE_TOKEN_is_default) ... PY`
- `./scripts/check_env.sh`：✅ 通过（1 个可选警告：binance-vision-service .venv 缺失）
- `cd services/consumption/api-service && ./scripts/start.sh restart`：✅ 已执行（PID 更新）
- 鉴权语义双断言（不回显 token）：
  - 无 token：`curl -s -m 2 http://127.0.0.1:8088/api/v1/health` → `success=false msg=unauthorized`
  - 有 token：`curl -s -m 2 -H "X-Internal-Token: $QUERY_SERVICE_TOKEN" http://127.0.0.1:8088/api/v1/health` → `success=true msg=success`
- `cd services/consumption/telegram-service && ./scripts/start.sh restart`：✅ 已执行（Bot PID 更新）
  - 备注：启动日志出现 `PG信号服务启动失败: cannot import name 'COOLDOWN_SECONDS' from 'config'`（疑似 sys.path + 模块名冲突；需单独修复/建任务）
- `./scripts/verify.sh`：✅ 通过

### P1 执行记录（防复发：启动顺序与 preflight guardrails）

- root 启动链路已纳入 `api-service`（Query Service 先于 telegram）：
  - `rg -n "SERVICES=\\(" scripts/start.sh` → `13:SERVICES=(ai-service signal-service api-service telegram-service trading-service)`
- `scripts/init.sh` 已把 `api-service` 纳入 core 初始化链路（避免 start 时 .venv 缺失）：
  - `rg -n "CORE_SERVICES=\\(" scripts/init.sh` → `18:CORE_SERVICES=(trading-service api-service telegram-service ai-service signal-service)`
- `telegram-service` 启动脚本已增加 Query Service preflight（fail-fast）：
  - `rg -n "preflight_query_service|/api/v1/health" services/consumption/telegram-service/scripts/start.sh` →
    - `97:preflight_query_service()`
    - `110:local url=\"$base/api/v1/health\"`
    - `227:start) ... preflight_query_service ...`
    - `231:restart) ... preflight_query_service ...`
- `sheets-service` 启动脚本已增加 Query Service preflight（fail-fast）：
  - `rg -n "preflight_query_service|/api/v1/health" services/consumption/sheets-service/scripts/start.sh` →
    - `71:preflight_query_service()`
    - `84:local url=\"$base/api/v1/health\"`
    - `201:start) preflight_query_service; start_svc`
    - `205:restart) preflight_query_service; stop_svc; ...`
- 一键冒烟脚本已创建并通过（不回显 token）：
  - `./scripts/smoke_query_service.sh` → `✅ smoke ok`

## 阻塞详情（如有）

- Blocked by: _None_
- Required Action: _None_
