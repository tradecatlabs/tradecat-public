# ACCEPTANCE

## Happy Path

1) WS 按分钟持续写入
- 证据：`services/ingestion/data-service/logs/ws.log` 出现连续分钟的 `WS写入: 4 条 | bucket_ts_max=...`（4 个 main4 符号）。

2) DB 新鲜度保持
- 证据：查询 `market_data.candles_1m` 的最新 `bucket_ts`，`age_s <= 120`。

3) daemon 不再自愈重启 ws
- 证据：`services/ingestion/data-service/logs/daemon.log` 不再在正常网络期持续出现 `执行自愈重启 ws...`。

## Edge Cases（至少 3 个）

1) WS 短暂断连后恢复
- 预期：cryptofeed 自动重连；`WS写入` 日志继续推进；daemon 不进入重启风暴。

2) backfill 触发（历史缺口）
- 预期：REST/ZIP 补齐只插入缺失 candle，不覆盖已有 WS 行（WS 优先）。

3) 依赖重建后仍可复现稳定
- 预期：执行 `make reset && make install` 后，仍安装 lock 中版本并保持 WS 稳定写入。

## Anti-Goals（禁止项）

- 不允许 backfill 覆盖 WS 行导致 `source` 从 `binance_ws` 回退为 `ccxt_gap/binance_zip`（至少在 WS 已写入的分钟内不应发生）。
- 不允许引入新依赖或大范围格式化导致 CI 波动。

