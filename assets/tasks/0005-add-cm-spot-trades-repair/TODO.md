# TODO

- [ ] P0: 新增 `crypto.repair.futures.cm.trades` 卡片 | Verify: `python3 -m src repair --help` | Gate: choices 出现
- [ ] P0: 新增 `crypto.repair.spot.trades` 卡片 | Verify: 同上 | Gate: choices 出现
- [ ] P0: CLI 路由新增 dataset 分支 | Verify: `python3 -m src repair --dataset ... --max-jobs 0 --no-files` | Gate: 无 import 错误
- [ ] P0: spot watermark 写入改为 ms | Verify: 查询 `crypto.ingest_watermark` 数量级 | Gate: ~1e12
- [ ] P0: repair 复用 backfill 的压缩门禁 + DISTINCT 更新 | Verify: 人为构造越界 gap，观察降级日志/meta | Gate: 无 UPDATE
- [ ] P1: 完整性巡检 SQL（ids 维表闭环） | Verify: SQL 返回 0 行异常 | Gate: 可写入 STATUS 证据
- [ ] P2: 文档补齐（对外口径） | Verify: 更新相关 docs/analysis 引用 | Gate: 无冲突
