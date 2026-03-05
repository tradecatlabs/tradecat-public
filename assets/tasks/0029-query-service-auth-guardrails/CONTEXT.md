# CONTEXT - query-service-auth-guardrails

## 现状追溯（Evidence）

### 1) `.env` 缺失 Query Service 鉴权关键键

- 证据（当前工作区）：
  - `assets/config/.env` 权限为 `600`，但缺失关键键：
    - `QUERY_SERVICE_TOKEN`
    - `QUERY_SERVICE_AUTH_MODE`
- 可复现命令：

```bash
cd /home/lenovo/tradecat/tradecat
grep -q '^QUERY_SERVICE_TOKEN=' assets/config/.env && echo yes || echo no
grep -q '^QUERY_SERVICE_AUTH_MODE=' assets/config/.env && echo yes || echo no
```

### 2) Query Service 默认鉴权是 fail-closed（required + token）

- 位置：`services/consumption/api-service/src/routers/query_v1.py::_require_token()`
- 关键逻辑（摘要）：
  - `QUERY_SERVICE_AUTH_MODE` 默认 `"required"`
  - 若 `QUERY_SERVICE_TOKEN` 缺失/为空 → `return False`
- 影响：一旦 `.env` 未配置 token，`/api/v1/*` 端点就会稳定返回 `unauthorized`（HTTP 200 + success=false）。

### 3) 消费端依赖 Query Service，且默认会带 token（若配置存在）

- 位置：`services/consumption/telegram-service/src/cards/data_provider.py:QueryServiceClient`
- 关键逻辑（摘要）：
  - 读取 `QUERY_SERVICE_BASE_URL`，缺失直接抛 `missing_env:QUERY_SERVICE_BASE_URL`
  - token 为空时 `_headers()` 返回 `{}`，会触发 Query Service `unauthorized`

### 4) 根因（Root Cause）

这是一个“配置缺失 + 启动链路不强制 + 失败不够显式”的组合问题：

- `.env` 缺失 token → Query Service 按设计 fail-closed → `/api/v1` 全 401（语义上）
- 根启动脚本 `./scripts/start.sh` 默认不包含 `api-service`（可选服务），导致“核心服务”启动后仍可能没有 Query Service
- 缺少强制 preflight，使得问题表现为“服务在跑但消费端取不到数据”，运维体验差
- 常见“临时绕过”是设置 `QUERY_SERVICE_AUTH_MODE=disabled`，但这会把内部接口裸奔（风险大且易被误用到生产）

## 约束矩阵（Constraints）

| 约束 | 内容 | 影响 |
|:---|:---|:---|
| 默认安全 | `required + token` 必须是默认 | 禁止通过默认值自动放行 |
| 密钥不入库 | `.env` 不提交 | 所有文档/日志必须脱敏 |
| consumption 禁直连 DB | 只能通过 Query Service | 任何回退到直连都视为违规 |

## 风险量化表（Risks）

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
|:---|:---|:---|:---|
| `/api/v1/*` 全 unauthorized | High | `curl /api/v1/health` 返回 `unauthorized` | 补齐 `.env` + preflight + 启动顺序 |
| 临时关鉴权裸奔 | High | `QUERY_SERVICE_AUTH_MODE=disabled` 出现在生产配置 | check_env 强制告警 + 文档明确禁止 |
| token 泄露 | High | git diff/日志出现 token 明文 | 禁止写入 tasks/日志；只给生成方式 |
| 运行时“假健康” | Medium | telegram 在跑但持续 Query 失败 | 启动脚本 preflight + status 输出提示 |

## 假设与证伪（Assumptions）

> 缺信息也必须推进；每条假设给出可执行证伪命令。

1) 假设：Query Service 本机地址为 `http://127.0.0.1:8088`
   - 证伪：`curl -s -m 2 http://127.0.0.1:8088/api/health`
2) 假设：消费端从 `assets/config/.env` 加载配置
   - 证伪：查看 `services/consumption/telegram-service/scripts/start.sh` 的 `ENV_FILE` 逻辑
3) 假设：生产环境必须启用鉴权（required）
   - 证伪：检查部署文档/系统服务文件是否显式设置 `QUERY_SERVICE_AUTH_MODE=disabled`

