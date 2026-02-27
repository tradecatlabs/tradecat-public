# ACCEPTANCE - 精密验收标准

## 1) Happy Path（成功路径）

### A1. 单卡片写入成功（事实表 + 看板，SA 模式）
- 操作：运行一次 CLI（SA 模式写入）
- 示例：
  - `cd services/consumption/sheets-service && SHEETS_WRITE_MODE=sa SHEETS_SPREADSHEET_ID=... GOOGLE_APPLICATION_CREDENTIALS=... .venv/bin/python -m src --once --cards super_trend_ranking`
- 期望：
  1) 返回 `ok=true`
  2) `cards_index` 新增 1 行（card_key 唯一）
  3) `card_fields_eav` 至少包含 `header.* / params.* / hint.*`
  4) 若存在表格明细：`card_rows` 与 `row_fields_eav` 行数与 rows_count 对齐
  5) `看板` 出现一块卡片（title/update/sort/table/hint/last_update 版式完整）
- Verify（示例）：
  - 观察 stdout：包含 `✅ flush 完成 ... mode=sa`
  - 在 Sheet 中检查新增行（或用 Sheets API 读取对应 range）
- Gate：满足 1-5

## 2) Edge Cases（至少 3 条边缘路径）

### E1. 幂等去重（重复投递不重复落盘/不重复渲染）
- 操作：同一数据时间窗口内重复执行 2 次（SA 模式）
- 期望：
  - 第二次运行 `skipped_append>0` 且 `sent=0`（或仅写入新增卡片）
  - outbox/checkpoint/idempotency 机制保证不会重复发送相同 `card_key`
- Gate：重复写入为 0（以本地 idempotency 口径）

### E2. Sheets 写入配额（WriteRequestsPerMinutePerUser=60）不再触发 429
- 操作：远端 daemon 连续运行 10 分钟（`SHEETS_SA_WRITE_RPM<=55`，推荐 50）
- 期望：
  - 日志不再出现：`Quota exceeded ... Write requests per minute`
  - outbox backlog 最终可下降（checkpoint 单调增长）
- Gate：无 429 / 最终一致

### E3. raw 超长不丢（无遗漏）
- 操作：发送超长 `raw.telegram_text_full`（超过单元格安全阈值）
- 期望：
  - 触发 blob 策略（Drive/对象存储/分块存储之一），`blobs_index` 有记录
  - hash 校验一致（sha256 与原文一致）
- Gate：raw 可通过 URL 取回且 hash 匹配

### E4. 下游失败不阻塞（旁路 outbox）
- 操作：制造写入失败（例如临时断网/错误 spreadsheet_id），再恢复
- 期望：
  - outbox backlog 增长但进程不崩溃（daemon 继续循环）
  - 恢复后自动补写（最终一致）
- Gate：最终补写成功

### E5. Webhook（可选路径）鉴权失败可观测
- 操作：缺失/错误签名请求
- 期望：
  - Webhook 返回非 200（或 `ok=false`）
  - 不落任何事实表、不渲染看板
  - 错误被记录（Webhook 日志/错误表）
- Gate：零落盘

## 3) 禁止性准则（Anti-Goals）
- 不允许：telegram-service 因写 Sheets 而阻塞/崩溃。
- 不允许：把逐笔/订单簿等高频明细写入 Sheets。
- 不允许：事实表依赖看板才能恢复（看板必须可重建）。
