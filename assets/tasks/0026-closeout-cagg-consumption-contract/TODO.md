# TODO - 0026 closeout-cagg-consumption-contract

> 每行格式：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

## P0（必须）

[ ] P0: 冻结基线（HEAD + 关键任务目标） | Verify: `git rev-parse --short HEAD && date -u +%F` | Gate: 将 HEAD/日期写入 `STATUS.md`

[ ] P0: DSN 对齐（定位运行库 DSN，禁止对错库执行） | Verify: `python3 - <<'PY'\nimport os\nfrom pathlib import Path\n\ndef parse_env(path: Path) -> dict[str,str]:\n    out: dict[str,str] = {}\n    if not path.exists():\n        return out\n    for line in path.read_text().splitlines():\n        line=line.strip()\n        if not line or line.startswith('#') or '=' not in line:\n            continue\n        k,v=line.split('=',1)\n        out[k.strip()] = v.strip()\n    return out\n\nassets_env = Path('assets/config/.env')\nlegacy_env = Path('config/.env')\nchosen = assets_env if assets_env.exists() else legacy_env\nparsed = parse_env(chosen) if chosen.exists() else {}\nprint('env_file=', str(chosen) if chosen.exists() else '(missing)')\nfor k in ['DATABASE_URL','QUERY_PG_MARKET_URL','QUERY_PG_INDICATORS_URL']:\n    pv = parsed.get(k, '')\n    print(f'{k}_file_set=', bool(pv.strip()))\n    print(f'{k}_process_set=', bool((os.getenv(k) or '').strip()))\nPY` | Gate: `STATUS.md` 记录“最终使用的 DSN 键名”（不记录明文密码）

[ ] P0: 运行库连通性探测（DATABASE_URL） | Verify: `psql \"$DATABASE_URL\" -c \"SELECT 1\"` | Gate: exit code=0

[ ] P0: Timescale 扩展存在性（运行库） | Verify: `psql \"$DATABASE_URL\" -Atc \"SELECT extversion FROM pg_extension WHERE extname='timescaledb';\"` | Gate: 输出非空（否则 Blocked）

[ ] P0: 源表存在性与数据量（metrics_5m） | Verify: `psql \"$DATABASE_URL\" -Atc \"SELECT to_regclass('market_data.binance_futures_metrics_5m'), count(*) FROM market_data.binance_futures_metrics_5m;\"` | Gate: to_regclass 非空；count 可为 0 但需记录（数据源问题）

[ ] P0: 检查 *_last 是否已存在（运行库） | Verify: `psql \"$DATABASE_URL\" -Atc \"SELECT to_regclass('market_data.binance_futures_metrics_15m_last'), to_regclass('market_data.binance_futures_metrics_1h_last'), to_regclass('market_data.binance_futures_metrics_4h_last'), to_regclass('market_data.binance_futures_metrics_1d_last'), to_regclass('market_data.binance_futures_metrics_1w_last');\"` | Gate: 若有任意空值 → 进入下一步执行 007

[ ] P0: 执行 007 DDL 创建 CAGG（幂等） | Verify: `psql \"$DATABASE_URL\" -f assets/database/db/schema/007_metrics_cagg_from_5m.sql` | Gate: exit code=0

[ ] P0: 首次 refresh/backfill（默认 30d；必要时分段） | Verify: `psql \"$DATABASE_URL\" -c \"CALL refresh_continuous_aggregate('market_data.binance_futures_metrics_1h_last', (NOW() AT TIME ZONE 'UTC')-INTERVAL '30 days', (NOW() AT TIME ZONE 'UTC'));\"` | Gate: exit code=0

[ ] P0: refresh 结果复核（max(bucket)） | Verify: `psql \"$DATABASE_URL\" -Atc \"SELECT '15m', max(bucket) FROM market_data.binance_futures_metrics_15m_last UNION ALL SELECT '1h', max(bucket) FROM market_data.binance_futures_metrics_1h_last UNION ALL SELECT '4h', max(bucket) FROM market_data.binance_futures_metrics_4h_last UNION ALL SELECT '1d', max(bucket) FROM market_data.binance_futures_metrics_1d_last UNION ALL SELECT '1w', max(bucket) FROM market_data.binance_futures_metrics_1w_last;\"` | Gate: 若源表有数据，则各行 max(bucket) 应非空

[ ] P0: Query Service 缺表消失（capabilities） | Verify: `curl -s -m 4 -H \"X-Internal-Token: $QUERY_SERVICE_TOKEN\" http://127.0.0.1:8088/api/v1/capabilities | head -n 40 || curl -s -m 4 http://127.0.0.1:8088/api/v1/capabilities | head -n 40` | Gate: `success=true` 且无 `missing_table:binance_futures_metrics_*_last`

[ ] P0: 高周期接口冒烟（open-interest 1h） | Verify: `curl -s -m 4 \"http://127.0.0.1:8088/api/futures/open-interest/history?symbol=BTC&interval=1h&limit=5\" | head -n 30` | Gate: `success=true`（data 可为空但不得 missing_table）

[ ] P0: 审计消费层直连 DB 残留（仅三件套） | Verify: `rg -n \"psycopg|psycopg_pool|(FROM|JOIN)\\s+market_data\\.|(FROM|JOIN)\\s+tg_cards\\.\" services/consumption/{telegram-service,sheets-service,vis-service}/src -S` | Gate: 无匹配（测试/文档例外需记录）

[ ] P0: 审计 consumption 旧端点依赖残留 | Verify: `rg -n \"/api/futures/\" services/consumption/{telegram-service,sheets-service,vis-service}/src -S` | Gate: 无匹配

[ ] P0: 门禁与核心服务检查 | Verify: `./scripts/verify.sh && (cd services/consumption/api-service && make check) && (cd services/consumption/telegram-service && make check) && (cd services/compute/trading-service && make check)` | Gate: 全部 exit code=0

## P1（重要）

[ ] P1: OTHER 数据源健康检查降噪复核 | Verify: `curl -s -m 4 http://127.0.0.1:8088/api/v1/health | head -n 60` | Gate: sources 不包含 `missing_env:QUERY_PG_OTHER_URL`（未配置时应跳过）

[ ] P1: scheduler/时间口径再审计（UTC 基准） | Verify: `rg -n \"timestamp without time zone\" services/compute/trading-service/src -S` | Gate: 关键窗口比较均使用 `(NOW() AT TIME ZONE 'UTC')`

## P2（可选优化）

[ ] P2: statement_timeout 收敛（DB 查询预算） | Verify: `rg -n \"statement_timeout\" services/consumption/api-service/src -S` | Gate: 支持 env 配置且默认安全
[ ] P2: OpenAPI(/docs) 补齐契约端点说明 | Verify: `curl -s -m 4 http://127.0.0.1:8088/docs | head` | Gate: 可见 v1 端点字段/错误码/示例

## 可并行（Parallelizable）

- P0: “CAGG DDL/refresh” 与 “consumption 审计” 可并行（不同资源）
- P1: “health 降噪复核” 与 “scheduler UTC 审计” 可并行
