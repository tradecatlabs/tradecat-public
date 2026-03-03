# PLAN - futures 路由收口与缺表降级

## 方案对比

### 方案 A：路由层“表存在性检查 + datasources(MARKET) 连接池”（推荐）

做法：
- 新增 `market_dao.py`（或同等内部模块）：
  - `table_exists(schema, table)`（TTL cache；默认 30s，可用 `QUERY_MARKET_TABLE_EXISTS_TTL_SEC` 调整）
- futures 路由全部改为：
  - 从 `datasources.get_pool(MARKET)` 获取连接
  - 在执行 SQL 前检查目标表存在
  - 缺表返回可诊断错误（不抛异常到 500）

Pros：
- 最小改动，不依赖 DB 侧改造
- 可渐进落地，每个路由可独立验收/回滚

Cons：
- 每次请求增加一次 `to_regclass()` 探测（需要缓存降低开销）

### 方案 B：自动回退到 5m 表或其它替代表（不推荐作为默认）

做法：
- 如果 `*_last` 缺失，自动用 `binance_futures_metrics_5m` 做降级替代

Pros：
- 用户“有数据可看”，不会空

Cons：
- 语义错误：高周期请求返回低周期数据，容易产生误判
- 隐蔽错误比显式错误更危险

### 方案 C：补建 `*_last` 表（不在本任务范围）

做法：
- compute/ingestion 提供连续聚合或物化视图

结论：本任务采用 **方案 A**。如需回退数据，必须显式标注 `fallback=true`，且默认不启用。

## 数据流（ASCII）

```text
Client
  │
  ▼
api-service
  ├─ futures routes (ohlc/open_interest/funding_rate/metrics)
  │     │
  │     ├─ datasources.get_pool(MARKET)  (统一连接池)
  │     ├─ table_exists()                (缺表判定 + TTL cache)
  │     └─ query rows -> map to CoinGlass response
  │
  └─ /api/v1/indicators/{table} (deprecated + token-only)
```

## 原子变更清单（文件级）

1) 新增市场库 DAO
- `services/consumption/api-service/src/query/market_dao.py`
  - `table_exists(schema, table)`（TTL cache）

2) 路由改造（统一数据源）
- `services/consumption/api-service/src/routers/ohlc.py`
- `services/consumption/api-service/src/routers/open_interest.py`
- `services/consumption/api-service/src/routers/funding_rate.py`
- `services/consumption/api-service/src/routers/futures_metrics.py`

3) indicators 退场
- `services/consumption/api-service/src/routers/query_v1.py`
  - `/api/v1/indicators/{table}` 强制 token + deprecated 标记

4) 测试补齐
- `services/consumption/api-service/tests/test_futures_missing_table_fallback.py`
- `services/consumption/api-service/tests/test_indicators_deprecated_token.py`

## 回滚协议

- 任一路由改造出问题：`git revert <commit>` 回滚单路由提交
- indicators 退场出问题：保留旧实现但改为仅 token（不会影响核心消费端）
