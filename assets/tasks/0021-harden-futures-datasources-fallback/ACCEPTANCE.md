# ACCEPTANCE - 验收标准（原子断言）

## Happy Path（成功路径）

1) **futures 路由统一使用 datasources(MARKET)，不再引用 `get_pg_pool()`**
   - Verify:
     ```bash
     rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/{futures_metrics,open_interest,funding_rate,ohlc}.py -S
     ```
   - Gate: 无匹配

2) **缺表（`*_last` 不存在）时不再返回 500**
   - 场景：请求 `interval=15m/1h/...`，对应表不存在
   - 期望：
     - 响应 `success=false` 且 `code=40004`（TABLE_NOT_FOUND）或 `success=true` 但 `data=[]` 且携带 `missing_table` meta（二选一，以 PLAN.md 最终方案为准）
     - HTTP 状态码保持 200（保持当前风格）或 4xx（二选一，以最终实现为准），但不得 500

3) **`/api/v1/indicators/{table}` 端点标记 deprecated 且强制内网 token**
   - 期望：未带 `X-Internal-Token` 调用被拒绝（`success=false`）
   - Verify:
     ```bash
     curl -s -m 3 "http://127.0.0.1:8088/api/v1/indicators/基础数据同步器.py?interval=15m&mode=latest_at_max_ts" | head
     ```
   - Gate: 返回 unauthorized 或明确拒绝提示

4) **契约端点不回退到 indicators 直通**
   - 期望：`/api/v1/cards/*` 与 `/api/v1/dashboard` 的实现不调用 indicators router 逻辑
   - Verify:
     ```bash
     rg -n "indicators/" services/consumption/api-service/src/query -S
     ```
   - Gate: 无“通过 URL 调 indicators”之类的逻辑

## Edge Cases（至少 3 条）

1) `interval` 不合法：返回 `code=40003`（INVALID_INTERVAL），不得 500。
2) `symbol` 不合法：返回 `code=40002`（INVALID_SYMBOL），不得 500。
3) 查询结果为空：返回 `success=true` + `data=[]`（或兼容空对象），不得 500。

## Anti-Goals（禁止性准则）

- 不新增/修改数据库 schema，不补建 `*_last` 表。
- 不让消费侧重新依赖 `/api/v1/indicators/{table}`。
- 不在日志/响应中输出带密码 DSN。

## 回归验证

```bash
cd services/consumption/api-service && make test
services/consumption/api-service/.venv/bin/ruff check services/ --ignore E501,E402 --select E,F
```

