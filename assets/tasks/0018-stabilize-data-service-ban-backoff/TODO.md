# TODO：可执行清单（按优先级）

> 每行格式：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

- [x] P0: 变更前快照提交（可回滚点） | Verify: `git rev-parse --short HEAD` | Gate: 已有基线提交 `a78f4083`（后续变更可 `git revert` 回滚）

- [x] P0: 复核 418 走 NetworkError 的证据链 | Verify: `rg -n "fetch_ohlcv 网络错误: binance 418" services/ingestion/data-service/logs/ws.log | tail -n 5` | Gate: 能看到带 `banned until` 的 418 行
- [x] P0: 复核 ban 触发路径覆盖（含 native klines / NetworkError） | Verify: `cd services/ingestion/data-service && make check` | Gate: `tests/test_ban_backoff.py` 覆盖 native klines 418 触发 ban + short-circuit

- [x] P0: 在 `adapters/ccxt.py` 统一异常→ban 识别（含 418/429） | Verify: `cd services/ingestion/data-service && pytest -q -k ban_backoff` | Gate: 418/429 触发 `set_ban(..., source=...)`
- [x] P0: 为 ban 触发日志加“来源标签”（rest_gapfill/ws_gapfill/metrics） | Verify: `cd services/ingestion/data-service && pytest -q -k ban_backoff` | Gate: `rate_limiter.set_ban(..., source=...)` + 单测覆盖 native klines/rest_gapfill/metrics

- [x] P0: backfill workers 可配置化（默认收敛） | Verify: `rg -n "DATA_SERVICE_REST_BACKFILL_WORKERS" services/ingestion/data-service/src/collectors/backfill.py -S` | Gate: 默认值为 2，且可由 env 覆盖

- [x] P0: start.sh 自愈逻辑对 ban 友好（ban 中跳过 ws 重启） | Verify: `rg -n "ws DB 自愈跳过:.*ban 剩余" services/ingestion/data-service/logs/daemon.log | tail -n 5` | Gate: 守护日志出现跳过分支

- [x] P0: 观察 ban 时是否进入等待而非刷屏 418 | Verify: `rg -n "IP ban 至|等待 ban 解除" services/ingestion/data-service/logs/ws.log | tail -n 20` | Gate: 出现等待日志；418 频率显著下降

- [x] P1: 增加最小单元测试覆盖 ban 解析与默认冷却 | Verify: `cd services/ingestion/data-service && pytest -q -k ban_backoff` | Gate: 覆盖：418(含 banned until)、429
- [x] P1: 更新 `assets/config/.env.example` 添加新可选项与解释 | Verify: `rg -n "DATA_SERVICE_REST_BACKFILL_WORKERS|DATA_SERVICE_WS_DB_SELF_HEAL_SKIP_ON_BAN" assets/config/.env.example -S` | Gate: 文案清楚、默认值保守

- [ ] P2: 运维巡检脚本（可选）输出 limiter 状态与 ban until | Verify: `python3 -c "..."` | Gate: 一条命令可看到 tokens/ban_until/等待时长

## Parallelizable（可并行）

- `ccxt.py` 的 ban 识别与 `start.sh` 的 ban-aware 自愈可并行开发。
- backfill workers 可配置化可与上述并行，但联调时需一起验证。
