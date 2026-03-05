# CONTEXT - 0026 closeout-cagg-consumption-contract

## 现状追溯（Evidence-Driven）

### 1) 高周期期货情绪依赖 `_last`，缺表会“静默变空”

- trading-service 的期货情绪指标在 `interval != "5m"` 时读取：
  - `market_data.binance_futures_metrics_{interval}_last`，时间列 `bucket`
  - 若表不存在：`_table_exists()` 直接使该周期缓存变空，上层 `compute()` 返回空 DataFrame（不会写占位行）。  
  证据：`services/compute/trading-service/src/indicators/incremental/futures_sentiment.py:63-75`

### 2) 仓库已内置 DDL 真相源：CAGG 从 5m 上推生成 `_last`

- `assets/database/db/schema/007_metrics_cagg_from_5m.sql:1-87` 定义 Timescale continuous aggregates：
  - 由 `market_data.binance_futures_metrics_5m(create_time)` 上推生成：
    - `market_data.binance_futures_metrics_15m_last`
    - `market_data.binance_futures_metrics_1h_last`
    - `market_data.binance_futures_metrics_4h_last`
    - `market_data.binance_futures_metrics_1d_last`
    - `market_data.binance_futures_metrics_1w_last`
  - 并内置 `add_continuous_aggregate_policy(...)`

### 3) 漂移根因高概率是“对错库执行 DDL/refresh”

- `.env.example` 同时存在两套库默认端口（LF=5433，HF=15432），且 api-service/trading-service 默认都回退 `DATABASE_URL`。  
  证据：
  - `assets/config/.env.example:46` `DATABASE_URL=...:5433/market_data`
  - `assets/config/.env.example:52` `BINANCE_VISION_DATABASE_URL=...:15432/market_data`
  - `assets/config/.env.example:102` `QUERY_PG_MARKET_URL=`（空则回退 `DATABASE_URL`）

> 结论：**必须先定位“服务运行时实际 DSN”**，再对齐执行 007 + refresh/backfill；否则会出现“某库有视图但服务仍缺表”的多世界分裂。

## 约束矩阵（Constraints）

| 约束 | 影响 | 本任务策略 |
| :-- | :-- | :-- |
| 只允许写 `assets/tasks/**` | 本任务只能产出可执行任务文档，不能直接改业务代码 | 以“可验证任务清单 + 命令 + Gate”为交付 |
| 不得泄露凭证 | `.env` 可能含密码/Token | 文档只记录脱敏 DSN；输出中禁止粘贴明文 |
| Timescale 依赖 | CAGG 需要 timescaledb extension | 必须先探测 `pg_extension.timescaledb`，否则 fail-fast |
| 刷新成本不可控 | 首次 refresh/backfill 可能压垮 DB | 默认小窗口（30d），分段执行，可回滚 policy |

## 风险量化表（Risk Register）

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :-- | :-- | :-- | :-- |
| 对错库执行 007/refresh | High | `*_last` 在某库存在，但服务仍 `missing_table` | 先定位 DSN；每次 DDL 后立刻 `to_regclass` + `max(bucket)` 双验证 |
| refresh/backfill 负载过大 | Medium | DB CPU/IO 飙升，查询超时 | 缩窗口/分段 refresh；必要时移除 policy 或先停 policy |
| consumption 仍直连 DB | High | 消费层出现 `psycopg*`/表名直通 | `rg` 审计 + `./scripts/verify.sh` 门禁 |
| API 示例与真实响应漂移 | Medium | 示例命令复制即失败 | 用 curl 真实跑一遍并将结果最小化落盘到文档（脱敏） |

## 假设与证伪（Assumptions & Falsification）

> 允许“最小假设推进”，但每条假设必须给出可执行证伪命令。

1) 假设：运行库启用了 TimescaleDB 扩展（可用 continuous aggregates）  
   - Verify：`psql \"$DATABASE_URL\" -Atc \"SELECT extversion FROM pg_extension WHERE extname='timescaledb';\"`
2) 假设：源表 `market_data.binance_futures_metrics_5m` 已存在且有数据  
   - Verify：`psql \"$DATABASE_URL\" -Atc \"SELECT count(*) FROM market_data.binance_futures_metrics_5m;\"`
3) 假设：trading-service 读取 DSN 来自 `assets/config/.env` → env vars（否则回退默认 5433）  
   - Verify：`rg -n \"assets/config/\\.env\" services/compute/trading-service/src/config.py -n`

