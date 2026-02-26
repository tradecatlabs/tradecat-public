# TODO - 微步骤执行清单

> 任务编号：0004

## P0（合同与结构）

[ ] P0: 复核当前 spot 表结构与行数 | Verify: `psql "$DATABASE_URL" -c "\\d+ crypto.raw_spot_trades" && psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM crypto.raw_spot_trades;"` | Gate: 确认仍为 legacy 列  
[ ] P0: 确认 Vision spot trades CSV 合同（无 header + time(us) + 列序） | Verify: 下载并 `head` 抽样 | Gate: 合同写死到文档/测试  
[ ] P0: 迁移脚本准备（rename-swap + integer hypertable(us)） | Verify: `ls -la libs/database/db/schema | rg -n "015_.*spot.*trades"` | Gate: 脚本存在且影响范围可控  
[ ] P0: 执行迁移脚本 | Verify: `psql "$DATABASE_URL" -f libs/database/db/schema/015_crypto_spot_trades_fact_table.sql` | Gate: exit code=0  
[ ] P0: AC1/AC2 表结构验收 | Verify: 见 `ACCEPTANCE.md` | Gate: 全通过  

## P0（链路补齐）

[ ] P0: 新增 spot trades writer | Verify: `rg -n "class RawSpotTradesWriter" -S services/ingestion/binance-vision-service/src/writers` | Gate: writer 可 import  
[ ] P0: 实现 spot realtime 采集卡片 | Verify: `python3 -m compileall services/ingestion/binance-vision-service/src/collectors/crypto/data/spot/trades.py` | Gate: 无语法错误  
[ ] P0: 实现 spot backfill 采集卡片 | Verify: `python3 -m compileall services/ingestion/binance-vision-service/src/collectors/crypto/data_download/spot/trades.py` | Gate: 无语法错误  

## P1（最小落地验证）

[ ] P1: writer 冒烟（插入 1 行→删除） | Verify: 手动 SQL / 小脚本 | Gate: 无报错且不留脏数据  
[ ] P1: Vision 回填 1 天（BTCUSDT） | Verify: `python3 -m src backfill --dataset crypto.data_download.spot.trades --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12` | Gate: 行数>0 且 storage.files 有记录  

