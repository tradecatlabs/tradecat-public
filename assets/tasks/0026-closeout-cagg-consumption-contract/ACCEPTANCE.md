# ACCEPTANCE - 0026 closeout-cagg-consumption-contract

## 成功路径（Happy Path）

1) **运行库的 CAGG 视图存在**
   - Verify：
     - `psql \"$DATABASE_URL\" -Atc \"SELECT to_regclass('market_data.binance_futures_metrics_15m_last');\"`
     - `psql \"$DATABASE_URL\" -Atc \"SELECT to_regclass('market_data.binance_futures_metrics_1h_last');\"`
     - `psql \"$DATABASE_URL\" -Atc \"SELECT to_regclass('market_data.binance_futures_metrics_4h_last');\"`
     - `psql \"$DATABASE_URL\" -Atc \"SELECT to_regclass('market_data.binance_futures_metrics_1d_last');\"`
     - `psql \"$DATABASE_URL\" -Atc \"SELECT to_regclass('market_data.binance_futures_metrics_1w_last');\"`
   - Gate：上述返回值均为非空（关系名存在）

2) **运行库的 CAGG 已完成首次 refresh/backfill（至少覆盖最近 30 天）**
   - Verify：`psql \"$DATABASE_URL\" -Atc \"SELECT max(bucket) FROM market_data.binance_futures_metrics_1h_last;\"`
   - Gate：`max(bucket)` 非空（若源表确实有数据）

3) **Query Service 不再对这些高周期报 missing_table**
   - Verify（二选一，取决于鉴权模式）：
     - 生产/默认（required）：`curl -s -m 4 -H \"X-Internal-Token: $QUERY_SERVICE_TOKEN\" http://127.0.0.1:8088/api/v1/capabilities | head`
     - 本地临时（disabled）：`curl -s -m 4 http://127.0.0.1:8088/api/v1/capabilities | head`
   - Gate：响应 `success=true`，且不包含 `missing_table` 指向 `binance_futures_metrics_*_last`

4) **消费层无 DB 直连/无旧端点依赖**
   - Verify：
     - DB 直连/SQL 片段（仅消费端三件套）：`rg -n \"psycopg|psycopg_pool|(FROM|JOIN)\\s+market_data\\.|(FROM|JOIN)\\s+tg_cards\\.\" services/consumption/{telegram-service,sheets-service,vis-service}/src -S`
     - `rg -n \"/api/futures/\" services/consumption/{telegram-service,sheets-service,vis-service}/src -S`
   - Gate：两条检查均无匹配（允许测试/文档例外需显式标注）

5) **门禁与核心检查全绿**
   - Verify：
     - `./scripts/verify.sh`
     - `cd services/consumption/api-service && make check`
     - `cd services/consumption/telegram-service && make check`
     - `cd services/compute/trading-service && make check`
   - Gate：全部 exit code = 0

## 边缘路径（Edge Cases，至少 3 条）

1) **Timescale 扩展缺失**
   - 预期：执行 007 DDL 前应先 fail-fast，提示缺少 `timescaledb`，不允许“半创建”。
   - Verify：`psql \"$DATABASE_URL\" -Atc \"SELECT 1 FROM pg_extension WHERE extname='timescaledb';\"`

2) **源表存在但数据不足（最近 30 天为空）**
   - 预期：视图存在但 `max(bucket)` 为空；任务应将其判定为“数据源问题”而不是“缺表问题”，并在 `STATUS.md` 记录。
   - Verify：`psql \"$DATABASE_URL\" -Atc \"SELECT max(create_time) FROM market_data.binance_futures_metrics_5m;\"`

3) **运行库 DSN 漂移（服务实际读的不是你执行 DDL 的库）**
   - 预期：必须在任务中记录 trading-service/api-service 的 DSN 解析链路与脱敏后的最终 DSN；若不一致则禁止继续。
   - Verify：见 `TODO.md` 的“DSN 对齐”步骤与 Gate。

## 禁止性准则（Anti-Goals）

- 禁止修改表名/字段名（以 DDL 真相源为准）
- 禁止引入新的“计算服务手写聚合写库链路”（除非单独立项）
- 禁止在文档/日志中粘贴明文 DSN 密码、Token
