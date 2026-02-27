# ACCEPTANCE

## AC1｜CLI repair 支持 CM/Spot

- 命令：`python3 -m src repair --help`
- 通过条件：`--dataset` 的 choices 包含：
  - `crypto.repair.futures.cm.trades`
  - `crypto.repair.spot.trades`

## AC2｜repair 能闭环关闭 open gaps（CM/Spot）

- 准备：向 `crypto.ingest_gaps` 插入 1 条 `status=open`（分别针对 dataset=`futures.cm.trades` 与 `spot.trades`，symbol 任意存在的交易对）。
- 命令：
  - `python3 -m src repair --dataset crypto.repair.futures.cm.trades --max-jobs 1 --no-files`
  - `python3 -m src repair --dataset crypto.repair.spot.trades --max-jobs 1 --no-files`
- 通过条件：
  - 输出包含 `claimed=1 closed=1`（或等价日志）
  - `crypto.ingest_gaps.status` 从 `open` 变为 `closed`，且 `run_id` 被写入

## AC3｜spot watermark 统一为 epoch(ms)

- 准备：跑一次 `crypto.data.spot.trades` 的最小写库冒烟（插 1 行后按 PK 删除）。
- 验证：查询 `crypto.ingest_watermark` 中 dataset=`spot.trades` 的 `last_time`
- 通过条件：`last_time` 为 **毫秒级**（数量级 ~ 1e12），且与 raw 行 `time(us)//1000` 一致。

## AC4｜安全门禁不退化

- 通过条件：
  - repair 内部复用 backfill 的“压缩线门禁（fail-closed）+ IS DISTINCT FROM”策略，不允许对压缩窗口外的 chunk 发生 UPDATE（越界时降级 DO NOTHING 并记入 meta）。

## AC5｜基础健康检查

- 命令：`python3 -m compileall -q services/ingestion/binance-vision-service/src`
- 通过条件：无语法错误退出码为 0。

