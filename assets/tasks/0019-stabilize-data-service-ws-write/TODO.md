# TODO

> 每条任务均包含 Verify 命令，便于执行 Agent 自证。

[ ] P0: 确认依赖安装优先使用 lock | Verify: `rg -n \"requirements.lock.txt\" scripts/init.sh services/ingestion/data-service/Makefile` | Gate: 输出包含 lock 优先逻辑

[ ] P0: 修复 WSCollector delayed flush | Verify: `rg -n \"while True\" services/ingestion/data-service/src/collectors/ws.py` | Gate: `_delayed_flush` 为循环 + idle 判断

[ ] P0: cryptofeed callback 支持 async | Verify: `rg -n \"inspect\\.isawaitable\" services/ingestion/data-service/src/adapters/cryptofeed.py` | Gate: 发现 awaitable 逻辑

[ ] P0: backfill/zip 写入不覆盖 WS | Verify: `rg -n \"update_on_conflict=False\" services/ingestion/data-service/src/collectors/backfill.py` | Gate: REST/ZIP 导入均为 insert-only

[ ] P0: TimescaleAdapter 支持 insert-only | Verify: `rg -n \"update_on_conflict\" services/ingestion/data-service/src/adapters/timescale.py` | Gate: `DO NOTHING` 分支存在

[ ] P0: 运行服务并观测 WS 按分钟写入 | Verify:
`services/ingestion/data-service/scripts/start.sh start && sleep 90 && rg -n \"WS写入\" services/ingestion/data-service/logs/ws.log | tail -n 5`
| Gate: 出现至少 2 条连续分钟 `WS写入`

[ ] P0: DB 新鲜度保持在阈值内 | Verify:
`cd services/ingestion/data-service && source .venv/bin/activate && PYTHONPATH=src python3 - <<'PY'\nfrom datetime import datetime, timezone\nimport psycopg\nfrom psycopg import sql\nfrom config import settings\nschema=settings.db_schema\nexchange=settings.db_exchange\nwith psycopg.connect(settings.database_url, connect_timeout=3) as conn:\n  with conn.cursor() as cur:\n    cur.execute(sql.SQL(\"SELECT bucket_ts FROM {} WHERE exchange=%s ORDER BY bucket_ts DESC LIMIT 1\").format(sql.Identifier(schema, 'candles_1m')), (exchange,))\n    ts=cur.fetchone()[0]\nnow=datetime.now(timezone.utc)\nage=int((now - (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))).total_seconds())\nprint('age_s=', age)\nPY`
| Gate: `age_s <= 120`

[ ] P1: 确认 daemon 不再触发 ws 自愈重启 | Verify:
`sleep 180 && rg -n \"执行自愈重启 ws\" services/ingestion/data-service/logs/daemon.log | tail -n 5`
| Gate: 最近 3 分钟无新增重启

