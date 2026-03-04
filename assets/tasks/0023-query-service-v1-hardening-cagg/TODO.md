# TODO - 执行清单（可并行标注）

> 每行格式：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

## P0（必须）

[ ] P0: 冻结基线（本地 commit + 关键接口快照） | Verify: `git rev-parse HEAD && curl -s -m 4 http://127.0.0.1:8088/api/v1/capabilities | head` | Gate: 记录到 STATUS.md

[ ] P0: 服务器拉取 develop 并重启 api-service | Verify: `ssh <SSH_TARGET> 'cd <repo_root> && git switch develop && git pull --ff-only && cd services/consumption/api-service && make check && make restart'` | Gate: restart 成功
[ ] P0: 服务器冒烟（capabilities/cards/dashboard + v1 OHLC） | Verify: `ssh <SSH_TARGET> 'curl -s -m 4 http://127.0.0.1:8088/api/v1/capabilities | head && curl -s -m 4 \"http://127.0.0.1:8088/api/v1/cards/atr_ranking?interval=15m&limit=5\" | head && curl -s -m 4 \"http://127.0.0.1:8088/api/v1/ohlc/history?symbol=BTC&exchange=Binance&interval=2h&limit=1\" | head'` | Gate: JSON success 字段符合预期

[ ] P0: LF 库执行 007 DDL 创建 metrics CAGG | Verify: `psql \"$DATABASE_URL\" -f assets/database/db/schema/007_metrics_cagg_from_5m.sql` | Gate: 执行成功/幂等成功
[ ] P0: 验证 *_last 视图存在 | Verify: `psql \"$DATABASE_URL\" -c \"SELECT to_regclass('market_data.binance_futures_metrics_1h_last');\"` | Gate: 返回非空

[ ] P0: 首次 refresh/backfill（窗口默认 90d，可调整） | Verify: `psql \"$DATABASE_URL\" -c \"CALL refresh_continuous_aggregate('market_data.binance_futures_metrics_1h_last', (NOW() AT TIME ZONE 'UTC')-INTERVAL '90 days', (NOW() AT TIME ZONE 'UTC'));\"` | Gate: MAX(bucket) 非空
[ ] P0: 高周期接口复验（不再缺表） | Verify: `curl -s -m 4 \"http://127.0.0.1:8088/api/futures/open-interest/history?symbol=BTC&interval=1h&limit=5\" | head` | Gate: success=true 且 data 非空

[ ] P0: 0020-P1 输出类型/单位标准化（契约字段） | Verify: `cd services/consumption/api-service && make test` | Gate: 契约测试全绿（必要时新增）
[ ] P0: 更新 API_EXAMPLES.md（端口/路径/示例可跑） | Verify: `nl -ba services/consumption/api-service/docs/API_EXAMPLES.md | sed -n '1,20p'` | Gate: Base URL 为 8088 且包含 /api/v1 示例

[ ] P0: 0017 收口：消费层禁止出现 /api/futures/ | Verify: `rg -n \"/api/futures/\" services/consumption/{telegram-service,sheets-service,vis-service}/src -S` | Gate: 无匹配
[ ] P0: 0017 收口：vis-service 改用 /api/v1/ohlc/history | Verify: `rg -n \"/api/v1/ohlc/history\" services/consumption/vis-service/src/templates/registry.py -S` | Gate: 必须命中 1 处（OHLC 查询）
[ ] P0: 门禁加固：verify.sh 阻止消费层引用 /api/futures/ | Verify: `rg -n \"/api/futures/\" scripts/verify.sh -S` | Gate: verify.sh 内存在 fail-fast 守护

## P1（重要）

[ ] P1: datasources OTHER 健康噪音清理（未配置则跳过） | Verify: `curl -s -m 4 http://127.0.0.1:8088/api/v1/health | head` | Gate: sources 不含 missing_env:QUERY_PG_OTHER_URL

[ ] P1: scheduler 时间口径统一为 UTC（timestamp without tz） | Verify: `rg -n \"create_time\\s*>\\s*NOW\\(\" services/compute/trading-service/src -S` | Gate: 无匹配

[ ] P1: 全仓门禁（verify + 核心 make check） | Verify: `./scripts/verify.sh` | Gate: 全绿

## P2（优化）

[ ] P2: OpenAPI 完整化（/docs 解释 v1 契约） | Verify: 访问 `/docs` 可见 v1 端点说明 | Gate: 字段/错误码/示例齐全

## 可并行（Parallelizable）

- P0: “服务器冒烟” 与 “本地 DDL/refresh” 可并行（不同机器）
- P1: “OTHER 噪音清理” 与 “scheduler UTC” 可并行
