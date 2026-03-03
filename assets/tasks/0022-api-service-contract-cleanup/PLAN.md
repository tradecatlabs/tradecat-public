# PLAN - 契约层收口与一致性修复

## 技术选型分析（至少两案）

### 方案 A：最小改动（推荐）

做法：
1) 扩展 `error_response` 支持 `extra: dict | None`（默认 `None`，保持兼容）。  
2) 缺表错误统一补齐结构化 `missing_table:{schema,table}`。  
3) 把 `routers/coins/base_data/signal/indicator` 的 `get_pg_pool()` 替换为 `datasources.get_pool(INDICATORS)`（不强迫引入 `OTHER` DSN，避免额外配置）。  
4) 单测覆盖新增字段与“路由不再直连 get_pg_pool”。

Pros：
- 影响面小，可逐文件提交、逐端点回滚
- 无新增环境变量强依赖（复用 `INDICATORS` 的 default_from_env）
- 输出结构完全向后兼容（只新增字段）

Cons：
- `INDICATORS` 可能承载多个 schema（tg_cards + signal_state），后续想拆库需要再迁一次

### 方案 B：新增专用数据源 `STATE`（不推荐作为本轮默认）

做法：
- 在 `datasources.py` 新增 `STATE = DataSourceSpec(... default_from_env="DATABASE_URL")`
- signal/状态类路由只用 STATE

Pros：
- 语义更清晰（state 与 indicators 解耦）

Cons：
- 需要改 `ALL_SOURCES` 与 health 探测输出，改动更大
- 仍然是同 DSN 时收益有限

结论：采用 **方案 A**。

## 逻辑流图（ASCII）

```text
Client
  │
  ▼
api-service (Query/Contract)
  │
  ├─ routers/* (legacy endpoints)
  │     └─ datasources.get_pool(INDICATORS/MARKET)  (统一连接治理)
  │
  ├─ futures routes
  │     └─ market_dao.table_exists + error_response(extra=missing_table)
  │
  └─ /api/v1/*
        ├─ stable contract endpoints (cards/dashboard/capabilities)
        └─ indicators/{table} (token-only debug; deprecated)
```

## 原子变更清单（文件级）

1) 错误响应扩展
- `services/consumption/api-service/src/utils/errors.py`
  - `error_response(..., extra: dict[str, Any] | None = None)`

2) 缺表结构化诊断
- `services/consumption/api-service/src/routers/ohlc.py`
- `services/consumption/api-service/src/routers/open_interest.py`
- `services/consumption/api-service/src/routers/funding_rate.py`
- `services/consumption/api-service/src/routers/futures_metrics.py`

3) 清理 get_pg_pool 散落（统一 datasources）
- `services/consumption/api-service/src/routers/coins.py`
- `services/consumption/api-service/src/routers/base_data.py`
- `services/consumption/api-service/src/routers/signal.py`
- `services/consumption/api-service/src/routers/indicator.py`

4) 测试补齐
- `services/consumption/api-service/tests/`
  - 新增：`test_missing_table_meta.py`（或在现有 fallback 测试中扩展）
  - 新增：`test_no_get_pg_pool_in_routers.py`（或用 rg 门禁脚本化）

5) tasks/文档状态对齐（仅 assets/tasks）
- `assets/tasks/INDEX.md`
- `assets/tasks/0020-data-api-contract-hardening/TODO.md`
- `assets/tasks/0020-data-api-contract-hardening/STATUS.md`

## 回滚协议（Rollback）

1) 若仅 meta 字段导致外部解析问题：回滚 `errors.py` 的 `extra` 合并逻辑即可（不影响主数据）。  
2) 若路由连接池切换引发连接异常：逐文件 `git revert` 回滚该路由提交（保持可分步回滚）。  
3) 任一回滚后必须跑：

```bash
cd services/consumption/api-service && make test
```

