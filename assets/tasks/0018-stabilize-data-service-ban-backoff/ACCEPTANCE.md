# ACCEPTANCE（验收标准）

## Happy Path（成功路径）

1) **418 ban 能被识别并进入全局冷却**
   - 操作：运行 data-service（含 ws + gap backfill），并在出现 418 的情况下观察日志。
   - 证据：
     - `services/ingestion/data-service/logs/ws.log` 出现 `IP ban 至 HH:MM:SS` 或 `等待 ban 解除`（来自 `rate_limiter.set_ban()`/`_wait_ban()` 的日志）
     - 在 ban 冷却期间，`fetch_ohlcv` 不再以高频率重复打印 418（应显著下降为“等待”日志）
   - Verify（命令示例）：
     - `rg -n "IP ban 至|等待 ban 解除" services/ingestion/data-service/logs/*.log | tail -n 50`

2) **ws 自愈不会在 ban 期间重启风暴**
   - 证据：`services/ingestion/data-service/logs/daemon.log` 在 ban 冷却期间不出现“每几分钟一次”的 `执行自愈重启 ws...`
   - Verify：
     - `rg -n "执行自愈重启 ws" services/ingestion/data-service/logs/daemon.log | tail -n 20`

3) **恢复后能自动续跑**
   - 证据：ban 到期后，`rows_written` 继续增长（或 `candles_1m` 新鲜度恢复到 < 120s），无需人工重启。
   - Verify（任选其一）：
     - `rg -n "批量写入" services/ingestion/data-service/logs/ws.log | tail -n 20`
     - `python3 - <<'PY'\n# 使用 DATABASE_URL 查询 candles_1m 最新 bucket_ts 与 now 的差值（执行 Agent 补全）\nPY`

---

## Edge Cases（至少 3 个边缘路径）

1) **418 文本存在但 parse_ban 解析失败（无 banned until 字段）**
   - 预期：仍设置一个保守 ban（例如 +120s），避免继续打爆；日志说明“解析失败，使用保守冷却”。
   - Verify：构造一条不含时间戳的 418 文本进行单元测试（或在 REPL 运行解析函数）。

2) **429 + Retry-After**
   - 预期：优先使用 Retry-After（秒）作为 ban 时长；不会错误解析为极长 ban。
   - Verify：单测覆盖 `429` 头部解析（如涉及）。

3) **短暂网络抖动（非 418/429）**
   - 预期：触发指数退避，但不会设置 ban；ws 自愈不会因一次 DB 检查失败而重启（`start.sh` 已有“检查失败跳过本轮自愈”的防抖逻辑）。
   - Verify：观察 `daemon.log` 出现 `ws DB 新鲜度检查失败，跳过本轮自愈` 但无重启。

4) **backfill 并发配置非法**
   - 预期：回退到安全默认值并记录警告；不 crash。
   - Verify：设置环境变量为非数字，启动服务并检查日志。

---

## Anti-Goals（禁止性准则）

- 不允许通过“删掉自愈/关掉 backfill”达成安静（必须保留核心能力，只做行为收敛）。
- 不允许把 ban 处理下沉为“静默吞错”（必须可观测、可解释）。
- 不允许引入新外部基础设施（Redis/队列）来解决本任务。

