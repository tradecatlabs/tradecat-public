# ACCEPTANCE - 精密验收标准

## Atomic Assertions（原子断言）

### A1. v1 默认鉴权为 fail-closed（无 token 必须拒绝）

- Verify：
  - `curl -s http://127.0.0.1:<PORT>/api/v1/capabilities | jq -r '.success'`
- Expected：
  - `false`
  - `msg` 包含 `unauthorized`（或统一错误码 `UNAUTHORIZED`，以实现为准）

### A2. 显式关闭鉴权开关后允许访问（仅用于 dev/受控环境）

- Precondition：`QUERY_SERVICE_AUTH_MODE=disabled`
- Verify：同 A1
- Expected：`success=true` 且 `data.cards/data.intervals/data.sources/data.version` 存在

### A3. CORS 不允许 `* + credentials`（默认无 allowlist 时不下发 ACAO）

- Verify：
  - `curl -I -H 'Origin: https://evil.example' http://127.0.0.1:<PORT>/api/health | rg -i 'access-control-allow-origin|access-control-allow-credentials' || true`
- Expected：
  - **无输出**（即不返回 ACAO/credentials 头）

### A4. CORS allowlist 生效（仅允许配置的 Origin）

- Precondition：`API_CORS_ALLOW_ORIGINS=https://tradecat.example`
- Verify：
  - `curl -I -H 'Origin: https://tradecat.example' http://127.0.0.1:<PORT>/api/health | rg -i 'access-control-allow-origin'`
- Expected：
  - `access-control-allow-origin: https://tradecat.example`

### A5. DSN 脱敏：响应/日志不得包含明文密码（含 key=value DSN）

- Precondition：配置 `QUERY_PG_MARKET_URL='host=127.0.0.1 user=postgres password=secret dbname=market_data'`
- Verify：
  - `curl -s -H "X-Internal-Token: $QUERY_SERVICE_TOKEN" http://127.0.0.1:<PORT>/api/v1/capabilities | rg -F 'secret' || true`
- Expected：
  - **无输出**

### A6. funding-rate 止血：无真实数据源时返回 not_supported（不再返回错数据）

- Verify：
  - `curl -s 'http://127.0.0.1:<PORT>/api/futures/funding-rate/history?symbol=BTC&interval=5m' | jq -r '.success,.msg'`
- Expected：
  - `success=false`
  - `msg=funding_rate_not_supported`（或明确的 not_supported 文案）

### A7. startTime/endTime 边界值：`0` 必须被当作“传了参数”

- Verify：
  - `curl -s 'http://127.0.0.1:<PORT>/api/futures/ohlc/history?symbol=BTC&interval=1h&endTime=0&limit=5' | jq '.data|length'`
- Expected：
  - `0`（窗口被限制到 epoch，通常无数据）

### A8. dashboard 参数硬上限生效（避免资源无上限）

- Verify（示例，cards 构造 100 个）：
  - `curl -s 'http://127.0.0.1:<PORT>/api/v1/dashboard?cards='\"$(python - <<'PY'\nprint(','.join(['volume_ranking']*100))\nPY)\" | jq -r '.success,.msg'`
- Expected：
  - `success=false`
  - `msg=too_many_items`（或等价错误）

### A9. 异常信息不对外回显（只给通用错误）

- Verify：断开数据库/传入必触发异常的路径后请求（以实际可控方式为准）
- Expected：
  - 响应 `msg` 不包含 host/table/sql/traceback
  - 服务端日志可定位（必须包含 trace_id 或请求路径）

## Edge Cases（至少 3 个边缘路径）

1) `QUERY_SERVICE_TOKEN` 未设置 + `QUERY_SERVICE_AUTH_MODE=required`：v1 全部拒绝。  
2) DSN 使用 URL 形式含密码：capabilities/health 输出仍不得泄露密码。  
3) DB 不可用：不得把原始异常文本/DSN 打回客户端；错误语义必须一致（HTTP/status 策略按 PLAN 选型）。

## Anti-Goals（禁止性准则）

- 禁止再引入 “返回错数据但看起来很对” 的临时映射（funding-rate 只能真数据或 not_supported）。
- 禁止把密钥/DSN/内部异常堆栈写入响应体（包括 health/capabilities）。
- 禁止通过“放松鉴权/CORS”来临时解决问题（只能通过显式开关并记录到文档）。

