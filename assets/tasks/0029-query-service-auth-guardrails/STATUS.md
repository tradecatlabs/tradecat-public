# STATUS - query-service-auth-guardrails

## 当前状态

- 状态：Done
- 最后更新：2026-03-05
- Owner：TBD

## 证据存证（执行过程中填写）

> 规则：
> - 只记录“事实与可复现命令”，不记录敏感信息（token/密码/SA JSON）。
> - 每个 Phase 通过后再进入下一 Phase。

### 基线证据（当前环境）

- `.env` Query Service 三件套存在性（只记录是否存在，不记录值）：
  - `grep -q '^QUERY_SERVICE_TOKEN=' assets/config/.env && echo yes || echo no` → `yes`
  - `grep -q '^QUERY_SERVICE_AUTH_MODE=' assets/config/.env && echo yes || echo no` → `yes`
  - `grep -q '^QUERY_SERVICE_BASE_URL=' assets/config/.env && echo yes || echo no` → `yes`
- Query Service 鉴权行为（示例，可能因当前进程启动参数而不同；不回显 token）：
  - 默认 required 场景：`curl -s -m 2 http://127.0.0.1:8088/api/v1/health` → `unauthorized`
  - 若临时设置 `QUERY_SERVICE_AUTH_MODE=disabled`：上述请求可能返回 `success=true`（风险：裸奔，仅限本地/受控调试）

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

### P1.1 执行记录（修复：telegram-service 内嵌 PG 信号引擎导入冲突）

- 现象（修复前）：telegram-service 启动日志出现 `PG信号服务启动失败: cannot import name 'COOLDOWN_SECONDS' from 'config'`（`config` 命名冲突）
- 根因：`ensure_runtime_sys_path()` 将 `telegram-service/src` 置于 `sys.path` 首位，导致 signal-service 的 `from config import ...` 被 telegram 的 `config/` 包“抢占”
- 修复：调整路径注入顺序（repo_root + 依赖服务在前，telegram 自身路径最后），避免 `config` 冲突
  - 证据：`sed -n '1,200p' services/consumption/telegram-service/src/path_setup.py`（可见 candidates 顺序与冲突说明）
- 验证（不依赖真实 TG 网络；仅验证模块可导入）：
  - `cd services/consumption/telegram-service && .venv/bin/python -c "import sys; sys.path.insert(0,'src'); import signals.adapter as a; print('adapter_import_ok'); a.get_pg_engine(); print('pg_engine_ok')"` → `adapter_import_ok` / `pg_engine_ok`

## 阻塞详情（如有）

- Blocked by: _None_
- Required Action: _None_
