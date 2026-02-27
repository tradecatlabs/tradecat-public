# TODO - 微步骤执行清单

> 任务编号：0002  
> 每一项都必须跑 Verify；任何 Gate 未满足不得进入下一项。

## P0（必须完成：解阻塞采集写库）

[ ] P0: 确认目标端点可连 | Verify: `pg_isready -h localhost -p 15432 && PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT 1;"` | Gate: 退出码=0  
[ ] P0: 快照旧表结构 | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "\\d+ crypto.raw_futures_um_trades"` | Gate: 观察到旧列 `exchange/symbol`  
[ ] P0: 确认 Timescale 扩展存在 | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT extname FROM pg_extension WHERE extname='timescaledb';"` | Gate: 返回 1 行  
[ ] P0: 进入维护窗口（冻结写入） | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT pid, usename, state, query FROM pg_stat_activity WHERE datname='market_data' AND query ILIKE '%raw_futures_um_trades%' ORDER BY state;"` | Gate: 无持续写入会话  

[ ] P0: 统计旧表规模（用于评估 copy 批次） | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT COUNT(*) AS rows, MIN(time) AS min_time, MAX(time) AS max_time FROM crypto.raw_futures_um_trades;"` | Gate: rows>0  
[ ] P0: 统计 distinct (exchange,symbol) | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT exchange, COUNT(DISTINCT symbol) AS symbols FROM crypto.raw_futures_um_trades GROUP BY 1 ORDER BY 2 DESC;"` | Gate: 列表非空  

[ ] P0: 为旧表里出现的 exchange 补齐 core.venue | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "INSERT INTO core.venue (venue_code, venue_name) SELECT DISTINCT exchange, exchange FROM crypto.raw_futures_um_trades ON CONFLICT (venue_code) DO NOTHING; SELECT COUNT(*) FROM core.venue;"` | Gate: core.venue 行数>=distinct exchange  

[ ] P0: 为旧表里出现的 symbol 建 core.instrument + core.symbol_map（幂等） | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data <<'SQL'\nWITH v AS (\n  SELECT venue_id, venue_code FROM core.venue\n), pairs AS (\n  SELECT DISTINCT t.exchange AS venue_code, t.symbol\n  FROM crypto.raw_futures_um_trades t\n), need AS (\n  SELECT p.venue_code, p.symbol\n  FROM pairs p\n  JOIN v ON v.venue_code = p.venue_code\n  LEFT JOIN core.symbol_map sm\n    ON sm.venue_id = v.venue_id AND sm.symbol = p.symbol AND sm.effective_to IS NULL\n  WHERE sm.instrument_id IS NULL\n), ins_inst AS (\n  INSERT INTO core.instrument (asset_class, instrument_type, meta)\n  SELECT 'crypto', 'perp', jsonb_build_object('source','migration','venue_code',venue_code,'symbol',symbol,'product','futures_um')\n  FROM need\n  RETURNING instrument_id, meta->>'venue_code' AS venue_code, meta->>'symbol' AS symbol\n)\nINSERT INTO core.symbol_map (venue_id, symbol, instrument_id, effective_from, effective_to, meta)\nSELECT v.venue_id, ii.symbol, ii.instrument_id, '1970-01-01'::timestamptz, NULL, jsonb_build_object('source','migration')\nFROM ins_inst ii\nJOIN v ON v.venue_code = ii.venue_code\nON CONFLICT DO NOTHING;\nSQL` | Gate: 再跑一遍 Verify 不应新增大量记录  

[ ] P0: 创建新表 `crypto.raw_futures_um_trades_new`（ids+DOUBLE+hypertable） | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data <<'SQL'\nCREATE TABLE IF NOT EXISTS crypto.raw_futures_um_trades_new (\n  venue_id        BIGINT NOT NULL,\n  instrument_id   BIGINT NOT NULL,\n  id              BIGINT NOT NULL,\n  price           DOUBLE PRECISION NOT NULL,\n  qty             DOUBLE PRECISION NOT NULL,\n  quote_qty       DOUBLE PRECISION NOT NULL,\n  time            BIGINT NOT NULL,\n  is_buyer_maker  BOOLEAN NOT NULL,\n  PRIMARY KEY (venue_id, instrument_id, time, id)\n);\nCREATE OR REPLACE FUNCTION crypto.unix_now_ms() RETURNS BIGINT\nLANGUAGE SQL STABLE AS $$ SELECT (EXTRACT(EPOCH FROM NOW()) * 1000)::BIGINT $$;\nSELECT create_hypertable('crypto.raw_futures_um_trades_new','time',chunk_time_interval=>86400000,create_default_indexes=>FALSE,if_not_exists=>TRUE);\nDROP INDEX IF EXISTS crypto.raw_futures_um_trades_new_time_idx;\nSELECT set_integer_now_func('crypto.raw_futures_um_trades_new','crypto.unix_now_ms',replace_if_exists=>TRUE);\nALTER TABLE crypto.raw_futures_um_trades_new SET (\n  timescaledb.compress = TRUE,\n  timescaledb.compress_segmentby = 'venue_id,instrument_id',\n  timescaledb.compress_orderby = 'time,id'\n);\nSQL\nPGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c \"SELECT * FROM timescaledb_information.hypertables WHERE hypertable_schema='crypto' AND hypertable_name='raw_futures_um_trades_new';\"` | Gate: hypertable 存在  

[ ] P0: 分批回迁（建议按日/按 chunk，避免单事务过大） | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "INSERT INTO crypto.raw_futures_um_trades_new (venue_id,instrument_id,id,price,qty,quote_qty,time,is_buyer_maker)\nSELECT v.venue_id, sm.instrument_id, t.id, t.price::DOUBLE PRECISION, t.qty::DOUBLE PRECISION, t.quote_qty::DOUBLE PRECISION, t.time, t.is_buyer_maker\nFROM crypto.raw_futures_um_trades t\nJOIN core.venue v ON v.venue_code = t.exchange\nJOIN core.symbol_map sm ON sm.venue_id = v.venue_id AND sm.symbol = t.symbol AND sm.effective_to IS NULL\nON CONFLICT (venue_id,instrument_id,time,id) DO NOTHING;"` | Gate: 受影响行数>0 或“已迁移完成”可解释  

[ ] P0: 检查是否存在 unmapped rows（必须为 0） | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT COUNT(*) AS unmapped FROM crypto.raw_futures_um_trades t LEFT JOIN core.venue v ON v.venue_code=t.exchange LEFT JOIN core.symbol_map sm ON sm.venue_id=v.venue_id AND sm.symbol=t.symbol AND sm.effective_to IS NULL WHERE v.venue_id IS NULL OR sm.instrument_id IS NULL;"` | Gate: unmapped=0  
[ ] P0: 核对行数（新表 >= 旧表；若等于最好） | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c "SELECT (SELECT COUNT(*) FROM crypto.raw_futures_um_trades) AS old_rows, (SELECT COUNT(*) FROM crypto.raw_futures_um_trades_new) AS new_rows;"` | Gate: new_rows >= old_rows  

[ ] P0: rename-swap（只在对账通过后做） | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data <<'SQL'\nBEGIN;\nSET LOCAL lock_timeout = '5s';\nALTER TABLE crypto.raw_futures_um_trades RENAME TO raw_futures_um_trades_old;\nALTER TABLE crypto.raw_futures_um_trades_new RENAME TO raw_futures_um_trades;\nCOMMIT;\nSQL` | Gate: 退出码=0  

[ ] P0: swap 后复核结构与 hypertable | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c \"\\d+ crypto.raw_futures_um_trades\" && PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c \"SELECT * FROM timescaledb_information.hypertables WHERE hypertable_schema='crypto' AND hypertable_name='raw_futures_um_trades';\"` | Gate: 列=ids+DOUBLE 且 hypertable 存在  

[ ] P0: 加回压缩 policy（若迁移期选择暂缓） | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c \"DO $$ BEGIN PERFORM add_compression_policy('crypto.raw_futures_um_trades', 2592000000); EXCEPTION WHEN duplicate_object THEN NULL; END $$;\"` | Gate: 命令成功（重复执行不报错）  

## P1（建议）

[ ] P1: 保留旧表并记录保留期限 | Verify: `PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -c \"SELECT to_regclass('crypto.raw_futures_um_trades_old');\"` | Gate: 返回非空  
[ ] P1: 写库烟囱测试（回填单日） | Verify: `cd services/ingestion/binance-vision-service && python3 -m src backfill --dataset crypto.data_download.futures.um.trades --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12` | Gate: 不出现“列不存在/类型不匹配”  

## 可并行（Parallelizable）

- 迁移前的 core 映射构建 与 新表 DDL 创建可并行准备，但正式回迁前必须冻结写入。

