# ACCEPTANCE - 验收标准（原子断言）

## Happy Path（成功路径）

1) **服务器 api-service 已同步到最新 develop 并通过冒烟**
   - Verify（服务器执行）：
     ```bash
     cd <repo_root>
     git rev-parse HEAD
     cd services/consumption/api-service && make check
	     make restart
	     curl -s -m 4 http://127.0.0.1:8088/api/v1/capabilities | head
	     curl -s -m 4 "http://127.0.0.1:8088/api/v1/cards/atr_ranking?interval=15m&limit=5" | head
	     curl -s -m 4 "http://127.0.0.1:8088/api/v1/dashboard?cards=atr_ranking&intervals=15m&shape=wide" | head
	     curl -s -m 4 "http://127.0.0.1:8088/api/v1/ohlc/history?symbol=BTC&exchange=Binance&interval=2h&limit=1" | head
	     ```
	   - Gate：均返回 `success=true`，且 `capabilities/cards/dashboard/ohlc` 结构正确

	2) **高周期期货聚合视图存在且有数据**
   - Verify：
     ```bash
     psql "$DATABASE_URL" -c "SELECT to_regclass('market_data.binance_futures_metrics_15m_last');"
     psql "$DATABASE_URL" -c "SELECT MAX(bucket) FROM market_data.binance_futures_metrics_1h_last;"
     ```
   - Gate：`to_regclass` 非空，`MAX(bucket)` 非空且接近当前时间（按业务期望）

3) **/api/futures OI/FR/metrics 在 15m/1h/4h/1d/1w 不再长期缺表**
   - Verify：
     ```bash
     curl -s -m 4 "http://127.0.0.1:8088/api/futures/open-interest/history?symbol=BTC&interval=1h&limit=5" | head
     curl -s -m 4 "http://127.0.0.1:8088/api/futures/funding-rate/history?symbol=BTC&interval=1h&limit=5" | head
     curl -s -m 4 "http://127.0.0.1:8088/api/futures/metrics?symbol=BTC&interval=1h&limit=5" | head
     ```
   - Gate：返回 `success=true` 且 `data` 为非空 list（至少 BTC）

	4) **消费层（tg/sheets/vis）不再引用 /api/futures/**
	   - Verify：
	     ```bash
	     rg -n "/api/futures/" services/consumption/telegram-service/src services/consumption/sheets-service/src services/consumption/vis-service/src -S
	     rg -n "/api/v1/ohlc/history" services/consumption/vis-service/src/templates/registry.py -S
	     ```
	   - Gate：第一条无匹配；第二条必须命中（vis-service 的 OHLC 迁移）

5) **OTHER 健康探测噪音消失（未配置 QUERY_PG_OTHER_URL 时不报 missing_env）**
   - Verify：
     ```bash
     curl -s -m 4 http://127.0.0.1:8088/api/v1/health | head
     curl -s -m 4 http://127.0.0.1:8088/api/v1/capabilities | head
     ```
   - Gate：`data.sources` 不包含 `id=other` 的 `missing_env:*` 错误项（未配置时应跳过）

6) **scheduler UTC 口径统一（timestamp without time zone）**
   - Verify：
     ```bash
     rg -n "create_time\\s*>\\s*NOW\\(" services/compute/trading-service/src -S
     rg -n "bucket\\s*>\\s*NOW\\(" services/compute/trading-service/src -S
     ```
   - Gate：无匹配；同类窗口过滤统一使用 `(NOW() AT TIME ZONE 'UTC')`

7) **全仓门禁通过**
   - Verify：
     ```bash
     ./scripts/verify.sh
     cd services/consumption/api-service && make check
     cd ../telegram-service && make check
     cd ../sheets-service && make check
     cd ../../compute/signal-service && make check
     cd ../trading-service && make check
     ```
   - Gate：全部为绿色通过

## Edge Cases（至少 3 条）

1) CAGG 已存在再次执行 DDL：
   - Gate：幂等（不报错或可忽略 duplicate），视图仍可用

2) refresh 窗口太大导致压力：
   - Gate：允许切换为“小窗口分段 refresh”（本任务必须提供可执行回退命令）

3) Query Service token 为空：
   - Gate：`/api/v1/capabilities` 可访问；`/api/v1/indicators/*` 仍默认拒绝（保持调试端点安全）

## Anti-Goals（禁止性准则）

- 不新建数据库 schema/表名（仅执行仓库已有 DDL；不引入新命名）。
- 不删除 legacy `/api/futures/*` 端点（仅迁移消费方与补齐 v1 wrapper）。
- 不在文档/日志/STATUS 中写入明文密码 DSN。
