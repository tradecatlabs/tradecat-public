# STATUS - query-service-auth-guardrails

## 当前状态

- 状态：Not Started
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
- Query Service 鉴权行为（示例，可能因当前进程启动参数而不同）：
  - 默认 required 场景：`curl -s -m 2 http://127.0.0.1:8088/api/v1/health` → `unauthorized`
  - 若临时设置 `QUERY_SERVICE_AUTH_MODE=disabled`：上述请求可能返回 `success=true`（风险：裸奔）

### P0 执行记录（留空待填）

- `./scripts/check_env.sh`：待执行
- `cd services/consumption/api-service && ./scripts/start.sh restart`：待执行
- `curl -s -H "X-Internal-Token: $QUERY_SERVICE_TOKEN" .../api/v1/health`：待执行
- `cd services/consumption/telegram-service && ./scripts/start.sh restart`：待执行
- `./scripts/verify.sh`：待执行

## 阻塞详情（如有）

- Blocked by: _None_
- Required Action: _None_

