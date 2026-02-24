# PLAN

## 1) 方案对比与取舍

### 1.1 `prune_tabs` 调度化

方案 A（现状）：每轮 dashboard 同步都 prune  
- Pros：永远保持 tab 集合“最干净”  
- Cons：写入次数高、对弱网极不友好、噪音大、失败率上升

方案 B（推荐）：按间隔 + keep hash 触发  
- Pros：写入大幅减少；弱网抖动被“稀释”；仍能保证最终一致性  
- Cons：tab 清理不是即时发生（延迟到下一次 prune 窗口）

方案 C：仅手动 CLI 执行 prune  
- Pros：最省配额  
- Cons：需要人工运维；容易遗忘导致 tab 漂移

结论：采用 **方案 B**。默认 interval 取一个“足够保守”的值（例如 6h），并允许 env 覆盖。

### 1.2 读请求弱网重试

方案 A（现状）：只重试 `TimeoutError`  
- Cons：`SSLError/ConnectionResetError` 直接冒泡，造成 prune/读元数据等操作不稳定

方案 B（推荐）：扩展“可重试错误集合”  
- Pros：改动小；对核心路径收益大  
- Cons：需要谨慎确保只重试幂等请求（读请求天然幂等）

结论：采用 **方案 B**，并记录重试次数/退避策略。

### 1.3 列宽固化 CLI

方案 A（现状）：手工 python snippet + 改 `.env`  
- Cons：不可审计、不可复用、容易操作失误

方案 B（推荐）：提供 `--snapshot-col-widths` 输出 env 行  
- Pros：统一入口；能进入 runbook；利于自动化  
- Cons：需要补充 CLI 参数与 README

结论：采用 **方案 B**。

## 2) 目标数据流（ASCII）

```text
daemon loop
  ├─(optional) prune tabs (scheduled)
  ├─export cards -> dashboard v5 write
  ├─(optional) refresh symbol query tabs
  └─(optional) export polymarket -> 3 tabs

All network IO
  └─ SaSheetsWriter._exec
       ├─ write: rpm limiter + 429 retry
       └─ read: transient retry (timeout/ssl/reset)
```

## 3) 原子变更清单（文件级别）

- `services/consumption/sheets-service/src/__main__.py`
  - 为 `prune_tabs` 增加“按间隔/keep hash”判定；失败后更新 meta（节流），避免下一轮立刻重试。
  - 新增 CLI：输出列宽固定 env（看板/币种查询/Polymarket 三表）。

- `services/consumption/sheets-service/src/sa_sheets_writer.py`
  - 扩展 `_exec` 的读请求可重试错误集合（`SSLError/ConnectionResetError` 等）。
  - 读取/写入 meta 的辅助函数（若需要统一）。

- `services/consumption/sheets-service/README.md`
  - 追加新的 CLI 使用说明与建议默认值。

## 4) 回滚协议

- 如调度化 prune 出现异常：
  - 设置 `SHEETS_SCHEMA_MODE=full` 或直接关闭调度（例如 `SHEETS_PRUNE_TABS_INTERVAL_SECONDS=0`）回到“每轮 prune/不 prune”的兼容分支。
- 如弱网重试导致阻塞：
  - 将 `SHEETS_SA_READ_RETRIES` 调小到 0（立即禁用读重试）。

