# CONTEXT - 现状证据与风险图谱

## 现状（可复核证据）

### 1) futures 路由仍在使用 `get_pg_pool()`（非 datasources）

- `services/consumption/api-service/src/routers/futures_metrics.py:52`
- `services/consumption/api-service/src/routers/open_interest.py:54`
- `services/consumption/api-service/src/routers/funding_rate.py:54`
- `services/consumption/api-service/src/routers/ohlc.py:60`

证据命令：

```bash
rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/{futures_metrics,open_interest,funding_rate,ohlc}.py -S
```

### 2) 多个接口依赖 `market_data.*_last` 派生表（高概率缺失）

硬编码映射位置（节选）：

- `services/consumption/api-service/src/routers/futures_metrics.py:18-22`
- `services/consumption/api-service/src/routers/open_interest.py:18-22`
- `services/consumption/api-service/src/routers/funding_rate.py:18-22`

证据命令：

```bash
rg -n "_last" services/consumption/api-service/src/routers/{futures_metrics,open_interest,funding_rate}.py -S
```

### 3) 旧的“表名直通”端点仍存在（易被误用/泄露内部实现）

- `services/consumption/api-service/src/routers/query_v1.py:202`：`@router.get("/indicators/{table}")`

证据命令：

```bash
rg -n "@router\\.get\\(\"/indicators" services/consumption/api-service/src/routers/query_v1.py -n
```

### 4) 已有可用的多数据源抽象（本任务应复用）

`MARKET` 数据源定义：

- `services/consumption/api-service/src/query/datasources.py:21`

证据命令：

```bash
rg -n "MARKET\\s*=\\s*DataSourceSpec" services/consumption/api-service/src/query/datasources.py -n
```

## 问题本质（Root Cause）

1) futures 路由绕过 `datasources`，导致“单 DSN + 直连散落”，无法统一治理（多库/脱敏/探活/连接池参数）。
2) 高周期 `*_last` 属于派生聚合表，不保证必存在；路由缺少“表存在性检查/降级返回”，导致生产中出现 500。
3) `indicators/{table}` 属于调试性质接口，若不收口，会长期泄露内部表名与字段口径，违背“契约层遮蔽实现”的目标。

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| 缺表导致 500 | High | 日志出现 `relation does not exist` / 接口 5xx 上升 | 增加表存在性检查；缺表返回 `40004` 或空数据 + meta |
| 输出语义变化破坏外部调用 | Medium | 外部图表/前端解析失败 | 保持响应字段不变；仅在错误时增加可选 meta |
| 多库 DSN 混用 | Medium | 连接错误库/错读 | futures 全部改用 `datasources.MARKET`；health 输出脱敏 dsn |
| 调试端点被外部依赖 | Medium | 出现第三方/脚本依赖 indicators 直通 | 先强制 token + deprecated；再统计调用再下线 |

## 假设与证伪（最小假设）

1) **假设**：当前数据库中仅保证存在 `market_data.binance_futures_metrics_5m`，其它 `*_last` 可能缺失。  
   **证伪命令**（执行 Agent 运行）：

```bash
psql "$DATABASE_URL" -c \"select table_name from information_schema.tables where table_schema='market_data' and table_name like 'binance_futures_metrics_%' order by 1;\"
```

2) **假设**：/api/v1 现已成为消费侧主入口（TG/Sheets/Vis 无 indicators 依赖）。  
   **证伪命令**：

```bash
rg -n "/api/v1/indicators" services/consumption -S
```

