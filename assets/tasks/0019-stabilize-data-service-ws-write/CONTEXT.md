# CONTEXT

## 现象（Symptoms）

1) `daemon.log` 持续出现：

- `ws DB 新鲜度陈旧: age=... 连续=...`
- `ws DB 连续陈旧，执行自愈重启 ws...`

导致 ws 进程每 5~10 分钟被重启一次，`ws.log` 反复出现 `FH: System Exit received - shutting down`。

2) DB 侧表现：

- `market_data.candles_1m` 的 `bucket_ts` 不随时间推进（或只在重启后被 REST 补齐推进一次）
- `source=binance_ws` 最新数据不前进（甚至被 `ccxt_gap/binance_zip` 覆盖）

## 根因（Root Causes）

### 根因 A：WSCollector 的 delayed flush 逻辑错误（多币种同分钟永不 flush）

`services/ingestion/data-service/src/collectors/ws.py` 的 `_delayed_flush()` 旧实现仅 sleep 一次：

- 同一分钟内多币种 candle 会在 1~2 秒内“成批到达”
- `_last_candle_time` 会被最后一条更新
- `sleep(FLUSH_WINDOW)` 醒来时 `idle < FLUSH_WINDOW`，于是直接退出，不再 flush、也不再重试

结果：buffer 会一直攒到进程退出，只有 finally 的 `_final_flush()` 才会一次性写入，daemon 误判 DB 新鲜度为陈旧并不断重启。

### 根因 B：cryptofeed → WSCollector 回调桥接不稳（事件循环/任务调度）

旧逻辑通过同步 wrapper `_on_candle_sync()` 调度协程，遇到 event loop 绑定/调度差异时会导致写入链路不可靠。

### 根因 C：backfill/zip 通过 upsert 覆盖 WS 行（source/字段被覆盖）

`TimescaleAdapter.upsert_candles()` 的 `ON CONFLICT DO UPDATE` 会更新 `source` 等字段；当 gapfill/backfill 对同一 `(exchange,symbol,bucket_ts)` 写入时，会把 WS 行覆盖为 `ccxt_gap/binance_zip`。

### 根因 D：依赖漂移（未优先使用 lock）导致 `websockets` 版本不一致

仓库已提供 `requirements.lock.txt`（示例：`websockets==15.0.1`），但：

- `services/ingestion/data-service/Makefile` 与 `scripts/init.sh` 旧逻辑优先安装 `requirements.txt`
- 会拉取最新 `websockets`（曾观察到 `websockets==16.0`）
- 在不稳定网络/代理下更易触发连接异常与内部错误，进一步恶化 ws 链路

## 修复点概览（Where we fixed）

- `services/ingestion/data-service/src/collectors/ws.py`
  - `_delayed_flush()` 改为循环等待 idle>=window 后 flush
  - flush 成功时输出低频观测日志 `WS写入: ...`
- `services/ingestion/data-service/src/adapters/cryptofeed.py`
  - callback 支持 async：`inspect.isawaitable(ret)` → `await ret`
- `services/ingestion/data-service/src/adapters/timescale.py`
  - `upsert_candles(..., update_on_conflict=...)`，backfill 选择 `DO NOTHING`
- `services/ingestion/data-service/src/collectors/backfill.py`
  - REST/ZIP 导入调用 `update_on_conflict=False`，避免覆盖 WS
- `services/ingestion/data-service/Makefile`、`scripts/init.sh`
  - 优先使用 `requirements.lock.txt` 安装依赖

