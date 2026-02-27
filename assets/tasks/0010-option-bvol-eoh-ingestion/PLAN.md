# PLAN

- 仅做下载回填（Vision ZIP）：
  1) 下载 ZIP + checksum 校验
  2) 解压 CSV
  3) 写入 `storage.files`
  4) 解析 CSV → 批量入库（注意空字符串→NULL）
  5) 记录 `ingest_runs/meta`

## 交付物

- 实现：
  - `src/collectors/crypto/data_download/option/BVOLIndex.py`
  - `src/collectors/crypto/data_download/option/EOHSummary.py`
- CLI backfill choices 增加 option 数据集。

