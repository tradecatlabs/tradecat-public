# TODO：可执行清单（按优先级）

> 每行格式：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

- [ ] P0: 变更前快照提交（可回滚点） | Verify: `git status --porcelain` | Gate: `git commit -m "chore: snapshot before data-service ban backoff fix"`

- [ ] P0: 复核 418 走 NetworkError 的证据链 | Verify: `rg -n "fetch_ohlcv 网络错误: binance 418" services/ingestion/data-service/logs/ws.log | tail -n 5` | Gate: 能看到带 `banned until` 的 418 行
- [ ] P0: 复核 ccxt.py 异常分支缺口 | Verify: `nl -ba services/ingestion/data-service/src/adapters/ccxt.py | sed -n '105,140p'` | Gate: NetworkError 分支未调用 `set_ban`

- [ ] P0: 在 `adapters/ccxt.py` 抽取 `maybe_set_ban_from_err(err_str)` 并在 NetworkError 分支调用 | Verify: `rg -n "maybe_set_ban|parse_ban\\(|set_ban\\(" services/ingestion/data-service/src/adapters/ccxt.py -S` | Gate: NetworkError 分支命中 `set_ban`
- [ ] P0: 为 ban 触发日志加“来源标签”（rest_gapfill/ws_gapfill/metrics） | Verify: `rg -n "IP ban 至" services/ingestion/data-service/src -S` | Gate: 日志能定位 ban 来自哪个调用方

- [ ] P0: backfill workers 可配置化（默认收敛） | Verify: `rg -n "RestBackfiller\\(.*workers" services/ingestion/data-service/src/collectors/backfill.py -S` | Gate: 默认值不再为 8，且可由 env 覆盖

- [ ] P0: start.sh 自愈逻辑对 ban 友好（ban 中跳过 ws 重启） | Verify: `rg -n "WS_DB_SELF_HEAL|ban_until|跳过本轮自愈" services/ingestion/data-service/scripts/start.sh -S` | Gate: 有明确 ban 检查分支与日志

- [ ] P0: 本地联调（至少 30 分钟）观察是否仍出现重启风暴 | Verify: `tail -n 200 services/ingestion/data-service/logs/daemon.log` | Gate: 30 分钟内无密集 `执行自愈重启 ws...`
- [ ] P0: 观察 ban 时是否进入等待而非刷屏 418 | Verify: `rg -n "等待 ban 解除" services/ingestion/data-service/logs/ws.log | tail -n 20` | Gate: 出现等待日志；418 频率显著下降

- [ ] P1: 增加最小单元测试（如项目已有测试框架）覆盖 ban 解析与默认冷却 | Verify: `pytest -q services/ingestion/data-service/tests -k ban` | Gate: 覆盖：418(含 banned until)、418(无时间)、429
- [ ] P1: 更新 `assets/config/.env.example` 添加新可选项与解释 | Verify: `rg -n "DATA_SERVICE_REST_BACKFILL_WORKERS|SELF_HEAL_SKIP_ON_BAN" assets/config/.env.example -S` | Gate: 文案清楚、默认值保守

- [ ] P2: 运维巡检脚本（可选）输出 limiter 状态与 ban until | Verify: `python3 -c "..."` | Gate: 一条命令可看到 tokens/ban_until/等待时长

## Parallelizable（可并行）

- `ccxt.py` 的 ban 识别与 `start.sh` 的 ban-aware 自愈可并行开发。
- backfill workers 可配置化可与上述并行，但联调时需一起验证。

