# 0005 - add-cm-spot-trades-repair

## 价值（Why）

目前 `binance-vision-service` 的 **repair 闭环只覆盖 UM trades**：能检测/记录缺口（`crypto.ingest_gaps`），但 CM/Spot 仍缺少“自动消费缺口并修复”的执行卡片；同时 spot 的 `ingest_watermark.last_time` 与治理表注释口径（ms）存在漂移，长期会导致修复/巡检/运维脚本踩坑。

本任务的目标是把 **CM/Spot trades 也补齐到 UM 同级**：可观测、可修复、可审计、可重跑。

## 范围（Scope）

### In Scope

- 新增 repair 数据集卡片：
  - `crypto.repair.futures.cm.trades`
  - `crypto.repair.spot.trades`
- `python3 -m src repair ...` CLI 增加上述 dataset 选择并可运行。
- 统一 **spot 的 watermark 时间单位**：`crypto.ingest_watermark.last_time` 对 `spot.trades` 以 **epoch(ms)** 写入（表注释口径保持 ms）。
- repair 运行写入 `crypto.ingest_runs/meta`：至少包含 claimed/closed/reopened + 关键耗时/条数。

### Out of Scope

- 不新增 agg/派生表（聚合/物化视图仍由后续任务处理）。
- 不修改事实表 schema（`crypto.raw_*_trades` 列不变）。
- 不修改 `config/.env`。

## 执行顺序（必须）

1. 阅读 `CONTEXT.md`（现状与证据）
2. 对照 `PLAN.md`（实现路径）
3. 按 `TODO.md` 执行并逐条验收 `ACCEPTANCE.md`
4. 更新 `STATUS.md`（写入证据）

