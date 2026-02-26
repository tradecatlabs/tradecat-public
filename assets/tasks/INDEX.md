# Tasks Index

| ID | Slug | Status | Priority | Objective | Link |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 0001 | binance-vision-um-trades-maturity | Done | P0 | 将 Binance Vision UM trades 采集链路补齐到“业内成熟”级别：CHECKSUM 审计、缺口修复闭环、维度字典化（v2） | ./0001-binance-vision-um-trades-maturity/ |
| 0002 | migrate-um-trades-ids-swap | Done | P0 | 将现有 `crypto.raw_futures_um_trades` 从旧结构（exchange/symbol + NUMERIC）安全迁移到新结构（venue_id/instrument_id + DOUBLE），并通过 rename-swap 与采集写库对齐 | ./0002-migrate-um-trades-ids-swap/ |
| 0003 | migrate-cm-trades-ids-swap | Done | P0 | 将运行库中仍为旧结构的 `crypto.raw_futures_cm_trades` 迁移到 ids+DOUBLE 事实表形态，并补齐 CM trades（实时+回填）采集卡片与写库链路 | ./0003-migrate-cm-trades-ids-swap/ |
| 0004 | refactor-spot-trades-fact-table | Done | P0 | 将 `crypto.raw_spot_trades` 从 legacy(file_id+time_ts+NUMERIC) 重构为极简事实表（ids+DOUBLE+time=epoch_us），并补齐 spot trades（实时+回填）采集卡片与审计闭环 | ./0004-refactor-spot-trades-fact-table/ |
| 0005 | add-cm-spot-trades-repair | Done | P0 | 补齐 CM/Spot trades 的 repair 闭环（消费 `crypto.ingest_gaps`），并统一 spot watermark 的时间单位口径（ms）以避免治理漂移 | ./0005-add-cm-spot-trades-repair/ |
| 0006 | trades-readable-views | Done | P1 | 为 UM/CM/Spot trades 提供只读视图：时间戳转换、维表 join、人类可读字段（不污染事实表） | ./0006-trades-readable-views/ |
| 0007 | trades-derived-klines-cagg | Done | P0 | 基于 trades 事实表构建 1m/5m/... K 线等派生序列（Timescale continuous aggregates / 物化视图），支撑训练与回测 | ./0007-trades-derived-klines-cagg/ |
| 0008 | futures-um-book-metrics-ingestion | Done | P1 | 补齐 futures/um 的 bookTicker/bookDepth/metrics（下载回填为主，必要时 WS），并完成审计/治理闭环 | ./0008-futures-um-book-metrics-ingestion/ |
| 0009 | futures-cm-book-metrics-ingestion | Not Started | P2 | 在 UM 成熟实现基础上对称补齐 futures/cm 的 bookTicker/bookDepth/metrics（下载回填为主） | ./0009-futures-cm-book-metrics-ingestion/ |
| 0010 | option-bvol-eoh-ingestion | Not Started | P2 | 补齐 option 的 BVOLIndex/EOHSummary（下载回填），并完成字段解析与审计闭环 | ./0010-option-bvol-eoh-ingestion/ |
| 0011 | tg-cards-sheets-dashboard | Done | P0 | 将 telegram-service 现有 TG 卡片同步到 Google Sheets 公共看板：卡片块 x,y 渲染 + 全字段无遗漏审计 + 幂等/outbox/可重建 | ./0011-tg-cards-sheets-dashboard/ |
| 0012 | sheets-service-hardening | Not Started | P1 | 对 sheets-service 做可靠性/可观测/配额与运维体验加固：减少无意义写入、抖动重试、prune 调度化、列宽快照固化 | ./0012-sheets-service-hardening/ |
| 0013 | rename-libs-to-assets | Done | P1 | 将仓库内“共享库/资源”目录从 `libs/` 逐步迁移为 `assets/`：先 `libs/external` → `assets/repo`，再通过兼容层完成 `libs/` → `assets/`（最少破坏、可回滚） | ./0013-rename-libs-to-assets/ |

## 相关索引（单点入口）

- `assets/docs/analysis/INDEX.md`：设计真相源 / 落地手册 / 运维加固 / 验收口径索引（强烈建议从这里开始读）。
- `assets/docs/analysis/binance_vision_um_trades_dev_retrospective.md`：UM trades 从 0 到可长期跑的复盘（坑 → 根因 → 解决方案）。
- `assets/docs/analysis/binance_vision_futures_um_book_data_full_ingestion_plan.md`：bookDepth/bookTicker 全量采集整理入库规划（分段推进 + 对账 + 成本控制）。
