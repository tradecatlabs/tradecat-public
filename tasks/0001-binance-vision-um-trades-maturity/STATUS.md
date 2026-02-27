# STATUS - 进度真相源

## State

- Status: Done
- Updated: 2026-02-15

## Execution Evidence（已落地的变更与验证）

### Evidence 1: `.CHECKSUM` 格式确认 + 本地 SHA256 对齐

- Command: `curl -sSfL "https://data.binance.vision/data/futures/um/daily/trades/BTCUSDT/BTCUSDT-trades-2026-02-12.zip.CHECKSUM" | head`
- Observed (excerpt):
  - `26e7c804...  BTCUSDT-trades-2026-02-12.zip`

### Evidence 2: backfill（单日）写入 storage 审计（files/import_batches）并幂等入库

- Command: `python3 -m src backfill --dataset crypto.data_download.futures.um.trades --symbols BTCUSDT --start-date 2026-02-12 --end-date 2026-02-12 --no-files`
- Observed (excerpt):
  - `affected=0 file_rows=6480832`（运行库已存在该日数据，回填幂等不重复写）
- Command: `psql "$DATABASE_URL" -c "SELECT rel_path, checksum_sha256, row_count FROM storage.files ORDER BY file_id DESC LIMIT 3;"`
- Observed (excerpt):
  - `data/futures/um/daily/trades/BTCUSDT/BTCUSDT-trades-2026-02-12.zip` 已落 `storage.files`（含 checksum + row_count）
- Command: `psql "$DATABASE_URL" -c "SELECT status, COUNT(*) FROM storage.import_batches GROUP BY status;"`
- Observed (excerpt):
  - `success >= 1`

### Evidence 3: gap repair 闭环验证（open -> repairing -> closed）

- Command: `python3 -c "..."`（通过 IngestMetaWriter.insert_gap 插入 1 条 open gap）
- Command: `python3 -m src repair --dataset crypto.repair.futures.um.trades --symbols BTCUSDT --max-jobs 1 --no-files`
- Observed (excerpt):
  - `repair 完成: claimed=1 closed=1 reopened=0`
- Command: `psql "$DATABASE_URL" -c "SELECT status, COUNT(*) FROM crypto.ingest_gaps GROUP BY status;"`
- Observed (excerpt):
  - `closed = 1`

### Evidence 4: 单测通过（含 checksum + repair）

- Command: `cd services/ingestion/binance-vision-service && pytest -q`
- Observed (excerpt):
  - `14 passed`
