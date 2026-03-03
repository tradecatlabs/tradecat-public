# ACCEPTANCE - 验收标准（原子断言）

## Happy Path（成功路径）

1) **路由层不再引用 `get_pg_pool()`（连接池统一到 datasources）**
   - Verify:
     ```bash
     rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers -S
     ```
   - Gate: 无匹配（允许 `src/config.py` 保留 `get_pg_pool` 定义，但 routers 禁止调用）

2) **缺表错误返回结构化诊断字段**
   - 场景：请求一个不存在的表（例如 `interval=6h` 或缺失的 `*_last`）
   - 期望（示例）：
     - `success=false`
     - `code=40004`
     - JSON 顶层包含 `missing_table`：
       - `missing_table.schema` = `market_data`
       - `missing_table.table` = `candles_6h`（或对应 *_last）

3) **`/api/v1/indicators/{table}` 仍为 token-only + deprecated**
   - 未带 `X-Internal-Token`：`success=false` + `code=40001`
   - 带正确 token：`success=true`，且 `data.deprecated=true`

4) **tasks 状态不再漂移**
   - `assets/tasks/INDEX.md` 中 `0015` 状态与 `assets/tasks/0015-unify-all-storage-to-postgres/STATUS.md` 对齐
   - `assets/tasks/0020-data-api-contract-hardening/TODO.md` P0 项已用 `[x]` 标记完成，并在 `STATUS.md` 更新证据（至少包含最近一次 `make test` 数量）

## Edge Cases（至少 3 条）

1) `QUERY_SERVICE_TOKEN` 为空：
   - `/api/v1/capabilities` 仍可访问（沿用现有逻辑）
   - `/api/v1/indicators/*` 必须拒绝（调试端点默认关闭）
2) 缺表但服务不崩：不得出现 HTTP 500（仍保持 CoinGlass 风格 200 + success=false）。
3) `error_response` 兼容：旧调用点不需要改参数也能正常工作。

## Anti-Goals（禁止性准则）

- 不新增 DB schema，不补建缺失表。
- 不删除旧端点（只增强可诊断性与连接治理）。
- 不在日志/响应中泄露 DSN 密码（继续使用 `datasources.redact_dsn` 口径）。

## 回归验证（硬门禁）

```bash
cd services/consumption/api-service && make test
services/consumption/api-service/.venv/bin/ruff check services/ --ignore E501,E402 --select E,F
```

