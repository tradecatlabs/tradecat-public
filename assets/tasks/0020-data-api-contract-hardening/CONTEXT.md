# CONTEXT - Data API 契约加固

## 现状追溯（Evidence）

### 1) 内部表名仍暴露给消费侧

- `api-service` 提供 `GET /api/v1/indicators/{table}`：调用方需要传入 `基础数据同步器.py` 等内部实现表名。
  - 位置：`services/consumption/api-service/src/routers/query_v1.py`
  - 读取实现：`services/consumption/api-service/src/query/dao.py:fetch_indicator_rows`

- `telegram-service` 维护 `TABLE_NAME_MAP` 把“卡片/别名”映射回内部表名（仍是实现细节外泄）。
  - 位置：`services/consumption/telegram-service/src/cards/data_provider.py`

### 2) `/api/v1/dashboard` 仍是 MVP（只聚合基础数据）

- 当前只返回 `基础数据同步器.py`（按周期 latest_at_max_ts），未覆盖“全部卡片/全部字段”的看板级抽象。
  - 位置：`services/consumption/api-service/src/query/service.py:dashboard_payload`

### 3) 映射规则分散且容易漂移

- `api-service` 有一套 `TABLE_FIELDS/TABLE_ALIAS` 用于快照结构化返回
  - 位置：`services/consumption/api-service/src/routers/indicator.py`
- `telegram-service` 的单币快照也维护了自己的 `TABLE_FIELDS/TABLE_ALIAS`
  - 位置：`services/consumption/telegram-service/src/bot/single_token_snapshot.py`

### 4) api-service 的“多数据源抽象”没有贯穿全部路由

- `/api/v1/*` 使用 `src/query/datasources.py` 的多 DSN 连接池抽象
  - 位置：`services/consumption/api-service/src/query/datasources.py`
- 但 `/api/futures/*`、`/api/indicator/*` 多数仍直接走 `src/config.get_pg_pool()`（单 DSN）
  - 例：`services/consumption/api-service/src/routers/futures_metrics.py`

### 5) 对外 futures API 强耦合底层表结构/派生表存在性

- 多周期 futures 指标硬编码指向 `market_data.binance_futures_metrics_*_last`
  - 位置：`services/consumption/api-service/src/routers/futures_metrics.py`、`funding_rate.py`、`open_interest.py`
- 当 `*_last` 不存在时，目前无统一降级策略（会直接失败）。

## 目标约束矩阵（Constraints）

| 约束 | 来源 | 含义 |
| :-- | :-- | :-- |
| 三层单向数据流 | `services/README.md` | consumption 必须只读派生结果，不允许直连 DB（除 Query Service 本身） |
| 消费侧必须通过 Query Service | `telegram-service` 文档 | TG/Sheets/Vis 只能 HTTP 调用 `/api/v1` |
| 不泄露敏感 DSN | 安全约束 | 健康检查/日志必须对 DSN 做脱敏 |
| 最小改动、可回滚 | 工程原则 | 分阶段迁移，先新增稳定端点，再迁移下游，最后清退旧接口 |

## 风险量化表（Risk Matrix）

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| TG/Sheets 看板输出变化 | High | 卡片字段缺失/排序变化/空值激增 | 契约端点对齐现有卡片字段；引入黄金样例对比；灰度迁移 |
| 多周期请求放大 DB 压力 | High | API p95 延迟上升、DB CPU 飙升 | 服务端缓存/请求合并；一次取全接口减少 N 次 round-trip |
| 旧接口被外部依赖误用 | Medium | 发现第三方调用 `/api/v1/indicators` | 加 `X-Internal-Token`；文档声明 deprecated；逐步下线 |
| futures `*_last` 缺表导致对外 500 | Medium | 监控到 500/表不存在错误 | 降级：回退 5m 聚合或返回可诊断错误码 |

## 假设与证伪（Assumptions & Falsification）

> 规则：每个假设都给一条可执行命令用于证伪。

1) **卡片稳定标识可用：card_id 是稳定主键**  
Verify:
```bash
rg -n \"card_id=\\\"\" services/consumption/telegram-service/src/cards -S | head
```

2) **消费侧目前仍依赖 `/api/v1/indicators/{table}`**  
Verify:
```bash
rg -n \"api/v1/indicators\" services/consumption/telegram-service/src services/consumption/sheets-service/src -S
```

3) **api-service 已具备多 DSN 抽象，但 futures 路由未使用**  
Verify:
```bash
rg -n \"QUERY_PG_\" services/consumption/api-service/src/query/datasources.py
rg -n \"get_pg_pool\\(\" services/consumption/api-service/src/routers -S
```

4) **指标库 schema 默认是 `tg_cards`**  
Verify:
```bash
rg -n \"INDICATOR_PG_SCHEMA\" services/consumption/api-service/src -S
```

