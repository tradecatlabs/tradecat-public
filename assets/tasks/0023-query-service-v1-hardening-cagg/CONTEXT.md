# CONTEXT - 现状证据与风险图谱

## 现状追溯（Evidence）

### 1) 高周期期货指标表被多处依赖，但运行库可能缺失

仓库已定义从 `market_data.binance_futures_metrics_5m` 上推的 Timescale continuous aggregate 视图：  
`assets/database/db/schema/007_metrics_cagg_from_5m.sql:1-87`

- 视图命名约定：`market_data.binance_futures_metrics_{interval}_last`  
  - `007_metrics_cagg_from_5m.sql:1-3`
- 注册的目标视图：`15m/1h/4h/1d/1w`  
  - `007_metrics_cagg_from_5m.sql:71-86`

对外 API 直接读这些表（缺表会长期触发 `missing_table`）：  
`services/consumption/api-service/src/routers/open_interest.py:15-24`

同时 compute 侧也硬依赖这些表：
- `services/compute/trading-service/src/core/storage.py:69-75`（聚合周期 totals）
- `services/compute/trading-service/src/simple_scheduler.py:256-270`（source latest：`MAX(bucket)`）
- `services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py:31-49`（缺口监控查询）

结论：**不补齐 `_last` 表，系统会长期处于“缺表降级/无法计算/误判落后”的不稳定态。**

### 2) 时间口径已出现不一致：同类表有的用 NOW()，有的用 UTC 基准

`market_data.binance_futures_metrics_5m.create_time` 是 `timestamp without time zone`（语义=UTC），但部分 SQL 使用 `NOW()` 做窗口过滤：
- `services/compute/trading-service/src/core/async_full_engine.py:250-258`  
  - `WHERE create_time > NOW() - INTERVAL '7 days'`
- `services/compute/trading-service/src/core/storage.py:61-63`
  - `WHERE create_time > NOW() - INTERVAL '1 hour'`
- `services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py:44-49`
  - `WHERE ... > NOW() - INTERVAL '30 days'`

而 scheduler 的另一处已显式用 UTC 基准：
- `services/compute/trading-service/src/simple_scheduler.py:160`
  - `WHERE create_time > (NOW() AT TIME ZONE 'UTC') - INTERVAL '7 days'`

结论：**需要统一规则**：`timestamp without time zone` 一律按 UTC 解读；SQL 过滤统一使用 `(NOW() AT TIME ZONE 'UTC')`。

### 3) 消费层“只走 /api/v1”尚未完全达成：vis-service 仍调用 legacy 路径

vis-service 仍在走 `/api/futures/ohlc/history`：
- `services/consumption/vis-service/src/templates/registry.py:324-346`

结论：要么新增 v1 wrapper（推荐），要么迁移/封禁 legacy 路径在消费层出现。

### 4) 文档与真实行为漂移：API_EXAMPLES 的 Base URL 仍是 8089

`services/consumption/api-service/docs/API_EXAMPLES.md:3-12` 指向 `http://localhost:8089`，但现行 api-service 默认端口为 8088（见 `services/consumption/api-service/src/config.py`）。

结论：必须完成 **“输出类型/单位标准化 + 文档示例可复制即跑通”** 的 P1 收尾。

### 5) 健康探测 sources 噪音：OTHER 未配置时会报 missing_env

`services/consumption/api-service/src/query/datasources.py:20-25` 把 `OTHER` 放进 `ALL_SOURCES`，  
`datasources.py:83-100` 的 `check_sources()` 会在未配置 `QUERY_PG_OTHER_URL` 时返回 `missing_env:*`。

结论：需要让 `OTHER` **可选**（未配置则不进入 health 输出），避免误报与运维噪音。

## 约束矩阵（Constraints）

- **禁止泄露 DSN 密码**：任何日志/文档/STATUS 仅允许 `datasources.redact_dsn` 级别的脱敏输出。
- **数据库栈区分**：LF/HF 两套库均为 `market_data`，但对象不同；本任务的 DDL 必须作用于 LF（`assets/database/db/stacks/lf.sql` 指向）。
- **消费侧禁止直连 DB**：由 `scripts/verify.sh:78-114` 进行门禁，迁移中不得放松门禁规则。

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| 在错误的库执行 DDL（跑到 HF） | High | `_last` 仍缺失 / 查询错库 | 执行前打印 `$DATABASE_URL` 并 `SELECT current_database(), current_setting('server_version')`；只用 LF 入口脚本 |
| refresh/backfill 过重导致 DB 压力 | High | refresh 慢/锁等待/IO 飙升 | 默认窗口回填（如 90d），逐视图逐段 refresh，必要时低峰执行 |
| v1 wrapper 改动引发消费侧解析失败 | Medium | vis-service 渲染异常 | wrapper 保持 data shape 与旧端点一致；先并行支持再切换消费侧 |
| OTHER health 噪音清理误伤真实探测 | Low | /api/v1/health sources 缺失某源 | 仅对“未配置 dsn 的源”跳过；已配置的仍探测 |

## 假设与证伪（最小假设）

1) **假设**：运行库的 LF DDL 尚未包含 007 或未 refresh，导致 `_last` 缺表/无数据。  
   证伪命令：
   ```bash
   psql "$DATABASE_URL" -c "SELECT to_regclass('market_data.binance_futures_metrics_1h_last');"
   ```

2) **假设**：服务器部署的 api-service 以仓库脚本/pm2/systemd 之一方式运行。  
   证伪命令：
   ```bash
   ssh <SSH_TARGET> 'ps aux | rg \"uvicorn|api-service|python -m src\" || true'
   ssh <SSH_TARGET> 'systemctl list-units --type=service | rg -i \"tradecat|api\" || true'
   ```
