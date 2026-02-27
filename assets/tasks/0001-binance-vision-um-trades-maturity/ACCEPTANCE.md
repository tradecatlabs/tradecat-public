# ACCEPTANCE - 精密验收标准

> 任务编号：0001
> 注意：验收必须按“原子断言”执行；不允许用“看起来差不多”替代。

## A. Happy Path（成功路径）

### A1) backfill：下载 + CHECKSUM 校验 + 入库 + 审计落地（单日）

- 操作
  - 运行：`cd services/ingestion/binance-vision-service && python3 -m src backfill --dataset crypto.data_download.futures.um.trades --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12`
- 断言（至少满足）
  - `storage.files` 中出现对应 `rel_path` 的记录，且 `checksum_sha256` 非空
  - `storage.import_batches` 出现 1 条 batch，状态为 `success`（或合理的 `partial`，但必须解释原因）
  - `storage.import_errors` 为 0（该 batch 下）
  - `crypto.raw_futures_um_trades` 在该日窗口内行数 > 0
  - `crypto.ingest_runs` 至少 1 条记录，状态最终为 `success/partial/failed` 之一且 `finished_at` 已填

### A2) monthly 404：自动降级日度并继续（智能边界）

- 操作
  - 运行（选择一个“确认月度不存在”的月份）：`python3 -m src backfill ... --start-date <...> --end-date <...>`
- 断言
  - 日志出现“月度不存在，降级按日”字样（或等价信号）
  - 仍能落地至少 1 个日度文件的 `storage.files` 记录

---

## B. Edge Cases（至少 3 个边缘路径）

### B1) CHECKSUM 缺失/404：行为必须可控且可追溯

- 预期策略（二选一，必须在实现中固定）：
  - 严格模式（推荐）：直接失败该文件导入，写 `storage.import_errors(error_type='checksum_missing')`
  - 逃生阀模式：允许 `--allow-no-checksum` 跳过，但必须写入 `storage.files.meta` 标记 “unverified”
- 断言
  - 任何情况下都不能“无声跳过校验且视为 success”

### B2) CHECKSUM 不一致：必须阻止脏数据入库

- 操作
  - 人为破坏下载文件（或构造测试桩）使 sha256 不一致
- 断言
  - 该文件不会进入事实表（或不会被标记为成功导入）
  - 写入 `storage.import_errors(error_type='checksum_mismatch')`
  - 若启用自动重试：重试耗尽后 status=failed/partial（不可假 success）

### B3) gap repair 闭环：open gap 必须能被自动关闭

- 操作
  - 制造 gap（例如停止 WS 一段时间，让实时侧写入 `crypto.ingest_gaps`）
  - 运行 repair：`python3 -m src repair --dataset futures.um.trades --symbols BTCUSDT --max-jobs 1`
- 断言
  - 对应 gap 的 `status` 从 `open -> repairing -> closed`（或 `open -> closed`，但必须有操作记录）
  - `crypto.ingest_watermark` 的 `last_time/last_id` 单调不减

---

## C. Anti-Goals（禁止性准则）

- 不得修改 `crypto.raw_futures_um_trades` 的现有字段集合（保持你已确认的极简事实表）。
- 不得引入非 `ccxt/ccxtpro` 的交易所 SDK 绕过数据契约。
- 不得在本任务中新增派生层物理表（`aggTrades/klines/*Klines` 等）。
