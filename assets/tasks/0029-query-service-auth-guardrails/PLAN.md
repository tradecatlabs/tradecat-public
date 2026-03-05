# PLAN - query-service-auth-guardrails

## 技术选型分析（至少两案对比）

### 方案 A（推荐）：required + token + 启动链路守护

**核心做法**

- `.env` 补齐 `QUERY_SERVICE_*` 三件套
- root `./scripts/start.sh` 默认纳入 `api-service`
- telegram/sheets 启动脚本做 `/api/v1/health` preflight（带 token）

**Pros**

- 默认安全（fail-closed），不会因漏配而“裸奔”
- 失败显式化：问题从“隐蔽 401”变为“启动即报错 + 指引”
- 运维体验好：减少“服务都在跑但没数据”的假象

**Cons**

- 需要修改启动脚本（但属于低风险工程化改动）

### 方案 B：disabled（仅本地调试）+ 明确隔离

**核心做法**

- 统一用 `QUERY_SERVICE_AUTH_MODE=disabled` 临时关闭鉴权
- 通过文档/门禁提示“仅本地可用”

**Pros**

- 本地调试更省事

**Cons（不可接受点）**

- 容易误用到生产（风险极高）
- 破坏“默认安全”原则；只要一个环境变量就能把内部接口裸奔

**结论**

- 选择 **方案 A** 作为默认；方案 B 只作为“临时调试”路径写入文档，并在 `check_env.sh` 中持续告警。

## 逻辑流图（ASCII）

```text
assets/config/.env
  ├─ QUERY_SERVICE_BASE_URL ─────────────┐
  ├─ QUERY_SERVICE_AUTH_MODE=required    │
  └─ QUERY_SERVICE_TOKEN ───────┐        │
                                │        │
                         api-service (/api/v1/*)
                                │  验证 token
                                │
          ┌─────────────────────┴─────────────────────┐
          │                                           │
telegram-service (cards/snapshot)              sheets/vis (dashboard)
  └─ preflight /api/v1/health (带 token)           └─ preflight（同上）
```

## 原子变更清单（文件级别，执行 Agent 用）

> 注意：本任务文档不直接改代码；这里只写“需要改哪些文件、改什么逻辑”。

1) 配置补齐（运行时，不提交）
   - `assets/config/.env`：新增/修正 `QUERY_SERVICE_*`
2) 启动链路守护（代码/脚本变更）
   - `scripts/start.sh`：把 `api-service` 加入默认 `SERVICES`（或提供 `--with-api` 开关并在文档中强制使用）
   - `services/consumption/telegram-service/scripts/start.sh`：
     - 启动前做 Query Service preflight（带 token），失败则退出并打印修复指引
   - （可选）`services/consumption/sheets-service/scripts/start.sh`：同样 preflight
3) 文档与门禁
   - `assets/config/.env.example`：确保示例键齐全且解释清晰（已存在，但需复核）
   - `README.md` / `AGENTS.md`：强调“consumption 只能走 Query Service”，并给出最小启动命令

## 回滚协议（100% 可还原）

- 回滚脚本改动：`git revert <commit>`
- 回滚运行时配置：从 `assets/config/.env` 删除新增的 `QUERY_SERVICE_*`（不会影响 git）
- 回滚运行时进程：`./scripts/start.sh stop` + 单服务 `./scripts/start.sh stop`

