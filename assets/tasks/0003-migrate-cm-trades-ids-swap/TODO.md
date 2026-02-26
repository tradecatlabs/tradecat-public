# TODO - 微步骤执行清单

> 任务编号：0003
> 规则：每一项都必须跑 Verify；任何 Gate 未满足不得进入下一项。

## P0（结构对齐）

[ ] P0: 复核当前 CM 表结构与行数 | Verify: `psql "$DATABASE_URL" -c "\\d+ crypto.raw_futures_cm_trades" && psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM crypto.raw_futures_cm_trades;"` | Gate: 确认仍为 `exchange/symbol` 旧列  
[ ] P0: 迁移脚本准备（rename-swap） | Verify: `ls -la libs/database/db/schema | rg -n "014_.*cm.*trades"` | Gate: 脚本存在且内容只影响 `crypto.raw_futures_cm_trades*`  
[ ] P0: 执行迁移脚本 | Verify: `psql "$DATABASE_URL" -f libs/database/db/schema/014_crypto_futures_cm_trades_ids_swap.sql` | Gate: exit code=0  
[ ] P0: AC1/AC2/AC3 结构验收 | Verify: 见 `ACCEPTANCE.md` | Gate: 全通过  

## P0（链路补齐）

[ ] P0: 新增 CM trades writer | Verify: `rg -n "class RawFuturesCmTradesWriter" -S services/ingestion/binance-vision-service/src/writers` | Gate: writer 可被 import  
[ ] P0: 实现 CM realtime 采集卡片 | Verify: `python3 -m compileall services/ingestion/binance-vision-service/src/collectors/crypto/data/futures/cm/trades.py` | Gate: 无语法错误  
[ ] P0: 实现 CM backfill 采集卡片 | Verify: `python3 -m compileall services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/cm/trades.py` | Gate: 无语法错误  

## P1（最小落地验证）

[ ] P1: writer 冒烟（插入 1 行→删除） | Verify: 手动 SQL / 小脚本 | Gate: 无报错且不留脏数据  
[ ] P1: Vision 回填 1 天（symbol TBD） | Verify: `python3 -m src backfill --dataset crypto.data_download.futures.cm.trades --symbols <TBD> --start-date <TBD> --end-date <TBD>` | Gate: 行数>0 且 storage.files 有记录  

