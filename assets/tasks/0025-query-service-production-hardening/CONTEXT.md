# CONTEXT - 上下文与风险图谱

## 现状追溯（关键证据）

### 1) 环境门禁缺口：check_env 未校验 Query Service 鉴权/消费端配置

- 证据：`scripts/check_env.sh:161-186` 只检查 `BOT_TOKEN/DATABASE_URL`，未覆盖 `QUERY_SERVICE_AUTH_MODE/QUERY_SERVICE_TOKEN/QUERY_SERVICE_BASE_URL`。
- 后果：生产/服务器环境若漏配 token，会出现“消费端全部 unauthorized”或“临时把 auth_mode=disabled 止血”的高风险操作。

### 2) 失败语义不唯一：validation=400，general exception=500，其它端点多为 200

- 证据：`services/consumption/api-service/src/app.py:53-89`（validation handler 返回 400；general exception 返回 500）。
- 当前路由层大量 `error_response(...)` 仍返回 HTTP 200（CoinGlass 风格），形成“多世界失败语义”，会破坏网关/监控/重试策略与可观测口径。

### 3) 数值精度漂移：指标读取层把 Decimal 强制转 float

- 证据：`services/consumption/api-service/src/query/dao.py:198-201` 对 `Decimal` 执行 `float(v)`。
- 后果：精度不可逆丢失，且可能出现科学计数法/末位漂移；同一指标在不同端点/不同路径返回不一致字符串。

### 4) dashboard/snapshot 结构性查询放大：cards×intervals 双层循环无缓存

- 证据：`services/consumption/api-service/src/query/service.py:50-76` 每次 dashboard 都对每卡片每周期调用 `build_card_payload(...)`。
- 现状：0024 已加硬上限（防滥用），但“正常刷新”仍会对 DB 形成周期性冲击；缺少缓存/击穿保护。

### 5) telegram 消费端抗抖动不足：进程级缓存无锁 + 无重试 + 失败不可降级

- 证据：`services/consumption/telegram-service/src/cards/data_provider.py:121-220`
  - `_cache` 为普通 dict，无锁；并发时存在竞态风险。
  - 直接 `resp.raise_for_status()`，无指数退避重试。
  - 请求失败直接抛异常，无 `stale-if-error` 策略。

### 6) compute 缺口监控存在 Silent-Fallback：DB 异常直接返回 {}

- 证据：`services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py:55-67` 捕获异常后 `return {}`。
- 后果：看起来“正常无缺口”，实际是“根本没读到数据”，属于典型 Silent-Fallback。

### 7) 连接预算缺失：连接池仅设置 connect_timeout，无 statement_timeout

- 证据：`services/consumption/api-service/src/query/datasources.py:96-102` 仅 `kwargs={"connect_timeout": 3}`。
- 后果：慢查询可拖死线程池/连接池，尾延迟不可控。

## 约束矩阵

| 约束 | 说明 |
|:---|:---|
| 不改 `assets/config/.env` | 只允许改模板 `assets/config/.env.example` 与校验脚本 |
| consumption 禁止直连 DB | 仍需保证 `./scripts/verify.sh` 的直连守护全绿 |
| 安全默认 fail-closed | `QUERY_SERVICE_AUTH_MODE=required` 时必须有 token，否则拒绝 |
| 最小改动 + 可回滚 | 每个 Phase 单独提交，保证可 `git revert` |

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| 失败语义分裂 | High | 监控/网关对 400/500/200 的判错口径不一致 | 统一 HTTP status 策略并用测试固化 |
| 精度漂移 | High | 同一指标不同端点数值字符串不一致 | Decimal 策略统一（分阶段灰度） |
| DB 被刷新打爆 | High | dashboard P95/P99 上升、连接数飙升 | 短 TTL 缓存 + 击穿保护 + 上限 |
| 下游抖动放大 | Medium | Query Service 短暂异常导致 TG 全挂 | telegram client 重试 + stale-if-error |
| Silent-Fallback | Medium | 缺口监控输出空/正常但日志显示 DB 异常 | 明确错误输出 + 可观测日志 |

## 假设与证伪（最小集合）

- 假设：api-service 默认端口 8088  
  - 证伪：`rg -n \"API_SERVICE_PORT\" services/consumption/api-service -S`
- 假设：消费端通过 `QUERY_SERVICE_BASE_URL` 访问 Query Service  
  - 证伪：`rg -n \"QUERY_SERVICE_BASE_URL\" services/consumption -S`
- 假设：系统希望采用 CoinGlass 风格失败语义（HTTP 200）  
  - 证伪：检查现有 tests 对 status_code 的断言（目前均为 200）

