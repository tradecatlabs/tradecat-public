# TODO - 微步骤执行清单

> 任务编号：0001
> 每一项都必须跑 Verify；任何 Gate 未满足不得进入下一项。

## P0（可信与审计）

[ ] P0: 预检 `.CHECKSUM` 是否存在且可下载 | Verify: `curl -sSfL "<BINANCE_DATA_BASE>/data/futures/um/daily/trades/BTCUSDT/BTCUSDT-trades-2026-02-12.zip.CHECKSUM" | head` | Gate: 命令退出码=0 且输出非空  
[ ] P0: 探测 `.CHECKSUM` 格式并写入 CONTEXT 备注 | Verify: 同上，人工确认是否包含文件名 | Gate: 形成固定解析规则（单测可覆盖）  
[ ] P0: 设计并实现 sha256 校验工具（下载+解析+本地计算） | Verify: `pytest -q services/ingestion/binance-vision-service/tests -k checksum` | Gate: 通过  
[ ] P0: backfill 写入 `storage.import_batches/import_errors` | Verify: `psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM storage.import_batches;"` | Gate: `>0`  
[ ] P0: backfill 写入 `storage.files.checksum_sha256/size_bytes` | Verify: `psql "$DATABASE_URL" -c "SELECT rel_path, checksum_sha256, size_bytes FROM storage.files ORDER BY file_id DESC LIMIT 3;"` | Gate: checksum_sha256 非空  
[ ] P0: checksum mismatch 时必须阻止入库并写 import_errors | Verify: 构造坏文件/测试桩；查 `storage.import_errors` | Gate: error_type 命中且事实表未增加该文件窗口数据  

## P0（缺口修复闭环）

[ ] P0: 新增 `repair` 子命令入口（CLI） | Verify: `cd services/ingestion/binance-vision-service && python3 -m src --help | rg -n \"repair\"` | Gate: help 可见  
[ ] P0: repair 能消费 `crypto.ingest_gaps(status='open')` | Verify: `psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM crypto.ingest_gaps WHERE status='open';"` | Gate: >0 才执行下一步  
[ ] P0: repair 执行后 gap 被关闭 | Verify: `psql "$DATABASE_URL" -c "SELECT status, COUNT(*) FROM crypto.ingest_gaps GROUP BY status;"` | Gate: open 数下降、closed 数上升  

## P1（成熟成本结构）

[ ] P1: 初始化 `core.venue/core.instrument/core.symbol_map`（至少 BTCUSDT） | Verify: `psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM core.symbol_map;"` | Gate: >=1  
[ ] P1: 新建 `crypto.raw_futures_um_trades_v2`（整型键） | Verify: `psql "$DATABASE_URL" -c \"\\d crypto.raw_futures_um_trades_v2\"` | Gate: 表存在且主键为 (venue_id,instrument_id,time,id)  
[ ] P1: 提供兼容 view 输出 exchange/symbol | Verify: `psql "$DATABASE_URL" -c \"\\d+ crypto.raw_futures_um_trades_view\"` | Gate: 可查询且列齐全  
[ ] P1: 双写/切换开关验证（v1/v2 行数一致性抽样） | Verify: SQL 抽样比对同一窗口 COUNT | Gate: 误差=0（或有明确解释）  

## P2（可观测）

[ ] P2: 运行指标写入 `ingest_runs.meta`（吞吐/重连/lag） | Verify: `psql "$DATABASE_URL" -c "SELECT meta FROM crypto.ingest_runs ORDER BY run_id DESC LIMIT 1;"` | Gate: meta 包含关键字段  

---

## 可并行（Parallelizable）

- P0：checksum 工具与 storage.import_* writer 可并行开发，但合并前必须统一接口与测试口径。
- P0：repair CLI 与 backfill 审计落地可并行，但必须共享同一“窗口定义/对账口径”。
