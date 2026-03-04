# ACCEPTANCE - 精密验收标准

## 总体目标

在不引入新基础设施、不修改生产 `.env` 的前提下，把 Query Service 与关键消费端收敛到：
**唯一失败语义、可观测错误、稳定数值口径、可控的刷新压力、下游抖动可降级**。

## 原子断言（Atomic Assertions）

### A) 环境变量门禁（P0）

1. **缺 token 必须失败（required 模式）**
   - Given: `assets/config/.env` 中 `QUERY_SERVICE_AUTH_MODE=required` 且 `QUERY_SERVICE_TOKEN` 为空或为默认占位值
   - When: 运行 `./scripts/check_env.sh`
   - Then: 脚本退出码非 0，输出包含 `QUERY_SERVICE_TOKEN: 未配置或为默认值`

2. **缺 base_url 必须失败（消费端）**
   - Given: `assets/config/.env` 未配置 `QUERY_SERVICE_BASE_URL`
   - When: 运行 `./scripts/check_env.sh`
   - Then: 脚本退出码非 0，输出包含 `QUERY_SERVICE_BASE_URL: 未配置`

Edge cases（至少 3 个）：
- `QUERY_SERVICE_AUTH_MODE=disabled` 时允许 token 为空，但必须输出明确 warning（避免误用到生产）。
- `QUERY_SERVICE_TOKEN=dev-token-change-me` 必须被当作“未配置”（防止把示例值带上生产）。
- `.env` 不存在时仍应给出明确创建指令（保持现有行为）。

### B) 错误语义唯一化（P0）

选择策略：**HTTP 永远 200**（CoinGlass 风格），错误靠 body 表达。

1. **参数校验错误也返回 HTTP 200**
   - When: 请求 `GET /api/v1/cards/atr_ranking?limit=abc`
   - Then: HTTP 200；body `success=false`；`code=40001`

2. **未捕获异常返回 HTTP 200 + trace_id**
   - When: 构造触发未捕获异常路径（例如注入 mock 抛异常）
   - Then: HTTP 200；body `code=50002`；包含 `trace_id`

3. **unauthorized 仍为 HTTP 200**
   - When: 不带 `X-Internal-Token` 请求 `GET /api/v1/capabilities`
   - Then: HTTP 200；`success=false`；`msg=unauthorized`

### C) 数值精度（P1）

1. **Open Interest 不再 float 漂移**
   - Given: DB 返回 NUMERIC/Decimal（或 mock row[2] 为 Decimal）
   - When: 请求 `/api/futures/open-interest/history`
   - Then: `open/high/low/close` 使用 `str(Decimal)`，不出现科学计数法，不丢末位

2. **dao numeric_mode 可灰度**
   - Given: `QUERY_NUMERIC_MODE=string`
   - When: `/api/v1/*` 读取到 Decimal
   - Then: 返回值为字符串；切换回 `float` 时保持兼容

### D) dashboard/snapshot 缓存与击穿保护（P1）

1. **相同参数短时间内命中缓存**
   - When: 连续两次请求同一 `/api/v1/dashboard?...`
   - Then: 第二次不触发底层 `build_card_payload`（用 monkeypatch 断言调用次数）

2. **缓存上限可控**
   - Given: 超过 `max_entries`
   - Then: 不发生无界内存增长（有明确淘汰策略）

### E) telegram 客户端抗抖动（P1）

1. **并发安全**
   - When: 多线程并发调用 `QueryServiceClient.get_card`
   - Then: 不抛 KeyError/竞态异常

2. **stale-if-error 生效**
   - Given: 缓存存在 + 下游返回 5xx/超时
   - Then: 返回缓存结果并标记 `stale=true`（或日志可观测）

### F) compute 缺口监控（P1）

1. **DB 异常不再静默**
   - When: DB 连接失败
   - Then: 输出明确 `信号=DB读取失败`（或 error 字段），并记录 warning 日志

### G) statement_timeout（P2）

1. **慢查询在预算内失败**
   - When: 故障注入 `SELECT pg_sleep(...)`
   - Then: 请求在预算内失败并返回结构化错误（不拖死服务）

## 禁止性准则（Anti-Goals）

- 不允许把示例 token/密钥写入仓库（只允许 `.env.example` 存占位说明）。
- 不允许新增“隐式 fallback”把错误当成功（禁止 Silent-Fallback）。
- 不允许引入无限缓存/无限参数组合导致内存与 DB 无界增长。

