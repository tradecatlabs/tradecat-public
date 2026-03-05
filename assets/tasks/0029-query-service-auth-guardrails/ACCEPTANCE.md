# ACCEPTANCE - query-service-auth-guardrails

## 原子断言（Atomic Assertions）

### Happy Path（成功路径）

1) `.env` 配置完备且安全
   - 断言：`assets/config/.env` 同时包含：
     - `QUERY_SERVICE_BASE_URL=...`
     - `QUERY_SERVICE_AUTH_MODE=required`
     - `QUERY_SERVICE_TOKEN=...`（非默认值）
   - 证据命令：`./scripts/check_env.sh`

2) Query Service 鉴权语义唯一且可验证
   - 断言 A（无 token）：`curl /api/v1/health` 返回 `success=false` 且 `msg=unauthorized`
   - 断言 B（有 token）：`curl -H X-Internal-Token:$QUERY_SERVICE_TOKEN /api/v1/health` 返回 `success=true`

3) telegram-service 能稳定取数（无 401 风暴）
   - 断言：重启后日志不再出现持续 `unauthorized`；能正常生成卡片/快照取数
   - 证据命令：
     - `cd services/consumption/telegram-service && ./scripts/start.sh restart`
     - `cd services/consumption/telegram-service && ./scripts/start.sh status`（查看最近日志）

### Edge Cases（至少 3 个边缘路径）

1) token 不一致（消费端 token ≠ Query Service token）
   - 期望：Query Service 返回 `unauthorized`；消费端 preflight 失败并给出修复提示（而不是静默重试风暴）

2) `QUERY_SERVICE_BASE_URL` 缺失或不可达
   - 期望：消费端启动失败（fail-fast），提示缺失键或连接失败原因（不进入“假运行”）

3) `QUERY_SERVICE_AUTH_MODE=disabled`
   - 期望：`./scripts/check_env.sh` 输出明确 Warning；文档声明仅限本地/受控环境

## 禁止性准则（Anti-Goals）

- 禁止把 `.env` / token / 密钥写入 git 或 tasks 文档
- 禁止让 Query Service 在缺 token 的情况下“默认放行”（fail-open）
- 禁止消费端回退直连 DB（违背 consumption 边界）

