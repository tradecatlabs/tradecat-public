# TODO

- [ ] P0: 明确官方 CSV 字段与样本 | Verify: 从 `artifacts/analysis/binance_vision_compass/**` 抽样 `head` | Gate: 字段清单固定
- [ ] P0: 实现 3 个 download_and_ingest | Verify: backfill 命令可跑 | Gate: AC1
- [ ] P0: 落库字段逐列对齐 | Verify: `\\d+` 表结构 + 抽样行解析 | Gate: AC2
- [ ] P1: 写入 storage.files 审计 | Verify: SQL 查询 | Gate: AC3
