# ACCEPTANCE（验收标准）

> 本任务的验收口径必须能“硬证明”两件事：  
> 1) consumption 层不再直连 DB；2) 业务功能仍可跑通且契约稳定。

## 1) Happy Path（成功路径）

### A1. Query Service `/api/v1` 可用且返回结构化 JSON

- Verify：
  - `curl -sS http://127.0.0.1:8088/api/v1/health | jq .success`
- Expected：
  - 输出 `true`

### A2. Query Service 能返回看板聚合（dashboard）

- Verify：
  - `curl -sS \"http://127.0.0.1:8088/api/v1/dashboard?intervals=5m,15m,1h,4h,1d,1w&shape=wide\" | jq '.data'`
- Expected：
  - `.data` 非空对象；并包含时间字段（`ts_utc`/`ts_ms`/可选 `ts_shanghai`）

### A3. Telegram 服务可在“无 psycopg 依赖”下运行

- Verify（代码层硬证据）：
  - `rg -n \"psycopg|psycopg_pool\" services/consumption/telegram-service/src -S` 无命中
- Gate：
  - `python3 -m py_compile services/consumption/telegram-service/src/bot/app.py`

### A4. Sheets 服务可在“无 psycopg 依赖”下运行

- Verify（代码层硬证据）：
  - `rg -n \"psycopg|psycopg_pool\" services/consumption/sheets-service/src -S` 无命中
- Gate：
  - `python3 -m compileall -q services/consumption/sheets-service/src`

---

## 2) Edge Cases（至少 3 个边缘场景）

### E1. Query Service 不可达时，消费端必须显式失败（无 DB fallback）

- Verify：
  - 临时停掉 query-service 后启动 telegram/sheets
- Expected：
  - 明确日志：`query_service_unavailable`（或等价错误），且不出现任何 DB 连接尝试

### E2. Query Service 返回空数据时，卡片渲染不崩溃

- Verify：
  - 请求一个不存在/无数据的 symbol/interval
- Expected：
  - 返回 `success=true` 但 `data` 为空结构；TG 文本展示为“无数据/占位符”，而非异常栈

### E3. 多数据源配置缺失时，health 能给出可诊断信息

- Verify：
  - 移除某个 DSN（例如 `QUERY_PG_MARKET_URL`）后访问 `/api/v1/health`
- Expected：
  - health 中标记该数据源为 degraded，并包含可行动提示（缺哪个 env）

---

## 3) Anti-Goals（禁止性准则）

### G1. consumption 层禁止出现任何 DB 直连痕迹

- Verify（强制）：
  - `rg -n \"psycopg|psycopg_pool|FROM\\s+tg_cards|tg_cards\\.|FROM\\s+market_data|market_data\\.\" services/consumption -S`
- Expected：
  - 命中仅允许出现在 `services/consumption/api-service/src`（Query Service）内；其它目录为 0 命中

### G2. api-service 禁止再动态 import telegram-service（消除部署耦合）

- Verify：
  - `rg -n \"spec_from_file_location|find_telegram_service_src|services/consumption/telegram-service\" services/consumption/api-service/src -S`
- Expected：
  - 0 命中（或仅存在于明确标注 deprecated 的兼容层，且不在运行路径）

### G3. verify/CI 必须 enforce 新约束

- Verify：
  - `./scripts/verify.sh`
- Expected：
  - 全绿；若在 consumption 任意位置故意加入 `import psycopg` 必须立刻失败

