# STATUS（进度与证据存档）

## 状态机

- Status: **Done**
- Owner: 执行 Agent
- Priority: P0

---

## 执行证据（执行 Agent 填写）

> 要求：每步完成后，把关键命令与输出片段粘贴在这里。

- [x] 基线提交（可回滚点）
  - 基线：`a78f4083`（无 data-service 代码改动）
  - 改动：
    - `f96ccb41`（ruff 修复：`make check` 变绿）
    - `ee184acb`（ban 来源标签 + native klines 异常也触发 ban + 单测补齐）
- [x] `git status --porcelain`
  - 输出：`(clean)`
- [x] 418 证据链（NetworkError 形态）
  - `rg -n "fetch_ohlcv 网络错误: binance 418" services/ingestion/data-service/logs/ws.log | tail -n 5`
    - `8728:... fetch_ohlcv 网络错误: binance 418 I'm a teapot ... IP banned until ...`
- [x] ban 冷却证据（等待而非刷屏）
  - `rg -n "IP ban 至|等待 ban 解除" services/ingestion/data-service/logs/ws.log | tail -n 5`
    - `8766:... IP ban 至 ...`
    - `8767:... 等待 ban 解除 ...s`
- [x] ban 期间 ws 自愈跳过（避免重启风暴）
  - `rg -n "ws DB 自愈跳过:.*ban 剩余" services/ingestion/data-service/logs/daemon.log | tail -n 5`
    - `1710:... ws DB 自愈跳过: ... ban 剩余 ...s`
- [x] 代码门禁
  - `cd services/ingestion/data-service && make check`
    - ✅ 通过（pytest：`6 passed`，含 `tests/test_ban_backoff.py`）

---

## 产物清单（执行 Agent 填写）

- [x] 418 触发时是否能 set_ban：`YES`（含 native klines 异常路径；并支持来源标签）
- [x] ban 期间是否能看到等待日志：`YES`
- [x] ws 自愈是否显著减少重启：`YES`（ban 期间跳过自愈重启）
- [x] backfill workers 是否可配置：`YES`（`DATA_SERVICE_REST_BACKFILL_WORKERS`，默认 2）

---

## Blocked（如阻塞必须写清）

- Blocked by: -
- Required action: -
