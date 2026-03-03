# PLAN - Data API 契约加固（决策与路径）

## 方案对比（至少两案）

### 方案 A：增量加固（推荐）

做法：
- 在 `api-service` 新增稳定契约端点（capabilities/cards/dashboard）。
- 消费端（TG/Sheets/Vis）迁移到新端点。
- 旧的“表名直通/调试接口”暂留但不再被消费端依赖，最后再逐步加 token 并下线。

Pros:
- 风险可控：可逐服务迁移、逐端点验收
- 易回滚：消费端回滚到上个版本即可（无需 DB 回滚）
- 便于并行：契约层与消费迁移可分 PR 推进

Cons:
- 迁移期会短暂存在“双路径”（新旧端点并存）

### 方案 B：硬切（不推荐）

做法：
- 直接删除 `/api/v1/indicators/{table}` 等旧端点，并同时改完所有消费端与文档。

Pros:
- 代码更“干净”，少一段过渡期

Cons:
- 风险极高：一次性改动面过大，回归难定位
- 一旦线上问题，必须整包回滚

结论：采用 **方案 A**，但在里程碑末尾要求“旧接口清退”完成，保证最终状态仍是“只剩稳定契约”。

## 目标架构（数据流图）

```text
TimescaleDB/PG(事实&派生)
  - market_data.*  (candles, futures metrics)
  - tg_cards.*     (指标/卡片数据)
  - signal_state.* (冷却/历史)
          │
          ▼
api-service (Data API / Contract Layer)
  - /api/v1/capabilities
  - /api/v1/cards/{card_id}
  - /api/v1/dashboard
          │ HTTP
          ├──────────────► telegram-service (只渲染)
          ├──────────────► sheets-service   (只导出)
          └──────────────► vis-service      (只可视化)
```

## 契约设计要点（实现准则）

1) **只暴露稳定 ID**
- `card_id`：来自 `telegram-service` card registry（稳定主键）
- `field_id`：使用卡片内部的字段 id（如 `atr_pct/upper/price/quote_volume`）
- `symbol`：统一输出 `BTCUSDT`（或同时提供 `base_symbol=BTC`）
- `interval`：统一 `5m/15m/1h/4h/1d/1w`（是否包含 `1m` 由 capabilities 决定）

2) **输出形状稳定**
- 推荐返回结构：
  - `meta`：`ts_*`、`latest_ts_*`、`data_freshness`、`source_health`
  - `rows[]`：每行 `symbol` + `rank` + `fields{field_id: value}`

3) **单一真相源（映射收敛）**
- 把 `TABLE_FIELDS/TABLE_ALIAS` 与卡片字段定义收敛到 `assets/common/` 下一个模块（例如 `assets/common/contracts/cards.py`）
- api-service 与 telegram-service 同源引用（避免两套漂移）

4) **贯穿多数据源抽象**
- futures/indicator/ohlc 等路由全部改用 `src/query/datasources.py` 获取连接池（为未来多库做准备）

## 原子变更清单（按文件级别）

> 只列“要改哪些文件/加哪些模块”，不写代码。

1) 新增契约模块（单一真相源）
- `assets/common/contracts/`（新目录）
  - `cards_contract.py`：card_id -> datasource/table -> field_id 映射；字段类型/单位；默认排序字段

2) api-service：新增稳定端点与内部服务层
- `services/consumption/api-service/src/routers/query_v1.py`：新增 `capabilities` / `cards` / 强化 `dashboard`
- `services/consumption/api-service/src/query/`：
  - 新增 `cards.py`（按 card_id 读取并组装 rows）
  - 复用 `dao.fetch_indicator_rows` 但在服务层完成“列名→field_id”的映射与输出整形
- futures 路由迁移到 datasources 抽象：
  - `services/consumption/api-service/src/routers/ohlc.py`
  - `services/consumption/api-service/src/routers/futures_metrics.py`
  - `services/consumption/api-service/src/routers/open_interest.py`
  - `services/consumption/api-service/src/routers/funding_rate.py`

3) telegram-service：迁移数据访问层
- `services/consumption/telegram-service/src/cards/data_provider.py`
  - 删除/废弃 `TABLE_NAME_MAP`
  - 改为调用 `GET /api/v1/cards/{card_id}`（或 `/api/v1/cards/{card_id}/ranking`）

4) sheets-service：同步迁移
- `services/consumption/sheets-service/src/tg_cards_exporter.py`
- `services/consumption/sheets-service/src/symbol_query_exporter.py`
  - 若继续复用 TG provider，确保 provider 已迁移即可；否则直接对接新端点

5) vis-service：迁移到稳定端点
- `services/consumption/vis-service/src/api/` 下的 query client（如存在）统一改用新端点

6) 测试与文档
- api-service：新增 `tests/test_query_contract_v1.py`（capabilities/cards/dashboard）
- 更新相关文档：`services/consumption/api-service/docs/`、`README.md`、`AGENTS.md`（仅记录契约与迁移说明）

## 回滚协议（Rollback）

1) 立即止血：`git revert <本任务相关提交>`（不做 DB 回滚）
2) 保留兼容：迁移期旧端点仍可用（但消费端不再依赖），回滚消费端后可继续使用旧链路
3) 证据检查：回滚后执行
```bash
./scripts/verify.sh
```

