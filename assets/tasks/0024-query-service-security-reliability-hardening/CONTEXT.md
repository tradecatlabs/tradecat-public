# CONTEXT - 现状证据与风险图谱

## 现状追溯（Evidence）

### 1) funding-rate 接口语义“撒谎”（错误列冒充资金费率）

`/api/futures/funding-rate/history` 实际查询列为 `sum_toptrader_long_short_ratio`，与 funding rate 完全不是一类数据：

- `services/consumption/api-service/src/routers/funding_rate.py:69-76`
  - `SELECT symbol, {time_col}, sum_toptrader_long_short_ratio`

结论：**这是“错误数据但看起来很对”的数据污染**，优先级高于一切性能/美化优化。

### 2) CORS 误配：`allow_origins=["*"]` + `allow_credentials=True`

api-service 的 CORS 目前为全开放且允许携带凭证：

- `services/consumption/api-service/src/app.py:31-38`
  - `allow_origins=["*"]`
  - `allow_credentials=True`

结论：一旦服务处于浏览器可达边界，这等价于把内部接口暴露给任意站点脚本（典型高危误配）。

### 3) v1 鉴权 fail-open：没配 token 即放行

Query Service v1 对 `X-Internal-Token` 的策略是：**环境变量空=不启用鉴权**：

- `services/consumption/api-service/src/routers/query_v1.py:26-33`
  - `if not expected: return True`

结论：同一套代码在不同环境产生“多世界语义”（漏配=裸奔）。

### 4) DSN 脱敏不完整：libpq `key=value` DSN 可能原样回显

`datasources.redact_dsn()` 仅对 URL 形式做脱敏；当 DSN 不是 URL 时直接返回原文：

- `services/consumption/api-service/src/query/datasources.py:47-59`
  - `if not p.scheme or not p.hostname: return dsn`

同时 `check_sources()` 会把 `error=str(exc)` 回给 `/api/v1/health|capabilities`：

- `services/consumption/api-service/src/query/datasources.py:100-102`

结论：**存在把密码/主机/库名打到响应里的风险**（尤其在连接失败/权限错误时）。

### 5) 异常对外直出：`服务器错误: {str(exc)}`

全局异常处理把异常文本直接写回响应：

- `services/consumption/api-service/src/app.py:64-75`
  - `"msg": f"服务器错误: {str(exc)}"`

结论：对外泄露内部实现与运行时细节，且会固化到消费端错误处理分支里。

### 6) dashboard/snapshot 结构性 N×M×K 放大，缺少硬上限与缓存

dashboard 的数据构造是 cards×intervals 的双层循环，每个组合会触发一次读库与整形：

- `services/consumption/api-service/src/query/service.py:50-76`
  - `for cid in cards: for itv in intervals: payload = build_card_payload(...)`

而 `build_card_payload()` 还可能为每个 interval 额外读一次 base 表构建 map（上限 5000）：

- `services/consumption/api-service/src/query/cards.py:46-61`
  - `_build_base_map(... limit=5000)`

symbol snapshot 更是 panels×tables×intervals 的嵌套查询：

- `services/consumption/api-service/src/query/service.py:127-161`

结论：缺少上限/缓存/隔离会导致 **轻易打爆 DB 连接池**（误用即事故）。

### 7) 时间过滤边界 bug：`startTime/endTime` 传 0 会被当成“没传”

多个路由使用 truthy 判断：

- `services/consumption/api-service/src/routers/ohlc.py:82-87`
- `services/consumption/api-service/src/routers/open_interest.py:82-91`
- `services/consumption/api-service/src/routers/funding_rate.py:82-91`

结论：`startTime=0`、`endTime=0` 等边界值必错，属于“复盘时最恶心”的隐性 bug。

### 8) 精度口径：Decimal 被强制转 float（不可逆丢精度）

指标库读取时把 `Decimal → float`：

- `services/consumption/api-service/src/query/dao.py:198-205`
  - `if isinstance(v, Decimal): return float(v)`

另有 futures 路由把数值 `float()` 再 `str(float)`：

- `services/consumption/api-service/src/routers/open_interest.py:110-118`
- `services/consumption/api-service/src/routers/funding_rate.py:110-118`

结论：会出现科学计数法/舍入漂移，导致排序、阈值、看板展示“偶发抖动”。

### 9) 消费端抗抖动不足：telegram-service HTTP 客户端无锁、无退避重试、无 stale-if-error

QueryServiceClient 是进程级单例，缓存 dict 无锁；请求无重试与降级：

- `services/consumption/telegram-service/src/cards/data_provider.py:121-186`

结论：下游抖动会被放大成“全失败”，并发下存在竞态风险。

### 10) compute 侧静默吞异常 + 共享缓存无锁：期货缺口监控可能“假正常”

期货缺口监控的 DB 读取异常会直接 `return {}`：

- `services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py:55-67`

同时 `_TIMES_CACHE/_CACHE_TS/_CACHE_SYMBOLS` 是共享可变状态，无锁更新：

- `services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py:21-24`

结论：属于 `Silent-Fallback` + `Shared-Mutable-State` 组合拳——最难排查、最容易误判“系统没问题”。

## 约束矩阵（Constraints）

- **正确性优先**：禁止继续输出“看起来正确的错误数据”（funding-rate）。
- **安全优先**：不得把 DSN 密码/内部异常文本返回给客户端；CORS 与鉴权必须“安全默认”。
- **契约优先**：`/api/v1/*` 必须保持稳定结构；若涉及类型变更（Decimal→string），必须提供兼容策略与迁移窗口。
- **最少修改原则**：优先补丁式修复；引入开关/缓存必须可关可测、可回滚。

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| v1 鉴权切 fail-closed 导致内部消费端全挂 | High | 401/unauthorized 暴增 | 先盘点消费端是否带 token；提供 `QUERY_SERVICE_AUTH_MODE=disabled` 临时回退；逐服务灰度 |
| CORS 收敛导致前端调试不便 | Medium | 浏览器跨域报错 | 仅在 dev 环境设置 allowlist；文档明确使用 `API_CORS_ALLOW_ORIGINS` |
| dashboard 硬上限误伤合法请求 | Medium | 被限流/too_many_items | 根据实际卡片数量与场景设置合理上限；提供服务端分页/limit 解释 |
| Decimal 类型策略导致消费端解析失败 | High | 下游格式化报错/排序异常 | 提供兼容模式（默认不破坏）；先在消费端支持两种类型再切换默认 |
| futures_gap_monitor 修复导致指标输出字段变化 | Low | 表头变动 | 保持三键不变，仅补充 error 字段；在计算层文档说明 |

## 假设与证伪（最小假设）

1) **假设**：当前没有真实 funding-rate 数据源（表/列）可用。  
证伪命令：
```bash
psql "$DATABASE_URL" -c "SELECT to_regclass('market_data.binance_funding_rate_5m');"
psql "$DATABASE_URL" -c \"SELECT column_name FROM information_schema.columns WHERE table_schema='market_data' AND table_name='binance_futures_metrics_5m' ORDER BY ordinal_position;\"
```

2) **假设**：生产/服务器环境会配置 `QUERY_SERVICE_TOKEN`，且消费端应当携带 `X-Internal-Token`。  
证伪命令：
```bash
rg -n \"QUERY_SERVICE_TOKEN|X-Internal-Token\" -S services/consumption | head
```

3) **假设**：api-service 未来可能被浏览器可达网络访问（否则 CORS 风险降低但仍不应误配）。  
证伪命令（服务器）：
```bash
ss -lntp | rg \"api-service|uvicorn|:8088|:8089\" || true
```

