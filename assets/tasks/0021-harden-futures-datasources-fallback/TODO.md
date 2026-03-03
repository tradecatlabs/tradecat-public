# TODO - 执行清单（可并行标注）

> 每行格式：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

## P0（必须）

[x] P0: 冻结基线（当前 futures 路由依赖证据） | Verify: `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/{futures_metrics,open_interest,funding_rate,ohlc}.py -S` | Gate: 有匹配
[x] P0: 新增 `market_dao.py`（datasources.MARKET + table_exists TTL cache） | Verify: `test -f services/consumption/api-service/src/query/market_dao.py` | Gate: 文件存在
[x] P0: 改造 `ohlc.py` 使用 `market_dao` + 缺表降级 | Verify: `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/ohlc.py -S` | Gate: 无匹配
[x] P0: 改造 `open_interest.py` 使用 `market_dao` + 缺表降级 | Verify: `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/open_interest.py -S` | Gate: 无匹配
[x] P0: 改造 `funding_rate.py` 使用 `market_dao` + 缺表降级 | Verify: `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/funding_rate.py -S` | Gate: 无匹配
[x] P0: 改造 `futures_metrics.py` 使用 `market_dao` + 缺表降级 | Verify: `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/futures_metrics.py -S` | Gate: 无匹配
[x] P0: /api/v1/indicators 端点 deprecated + 强制 token | Verify: `curl -s -m 3 "http://127.0.0.1:8088/api/v1/indicators/基础数据同步器.py?interval=15m&mode=latest_at_max_ts" | head` | Gate: 被拒绝或提示 deprecated+token
[x] P0: 补齐测试（缺表/拦截） | Verify: `cd services/consumption/api-service && make test` | Gate: 全绿
[x] P0: 运行 E/F 快检（CI 同款） | Verify: `services/consumption/api-service/.venv/bin/ruff check services/ --ignore E501,E402 --select E,F` | Gate: All checks passed!

## P1（重要）

[x] P1: 表存在性检查缓存化（TTL 可配置） | Verify: `rg -n "QUERY_MARKET_TABLE_EXISTS_TTL_SEC" services/consumption/api-service/src/query/market_dao.py -S` | Gate: 有环境变量或常量
[ ] P1: 在响应中附带 `missing_table`/`schema`/`table`（仅错误场景） | Verify: 缺表请求时返回 JSON 含该字段 | Gate: 可诊断且不泄露密码
[x] P1: 更新 `assets/tasks/0020-data-api-contract-hardening/STATUS.md` 引用本任务进度 | Verify: `rg -n "0021" assets/tasks/0020-data-api-contract-hardening/STATUS.md -S` | Gate: 有记录

## P2（优化）

[ ] P2: 统一 futures 路由的参数校验/错误码输出（封装 helper） | Verify: `rg -n "INVALID_INTERVAL" services/consumption/api-service/src/routers -S` | Gate: 逻辑集中
