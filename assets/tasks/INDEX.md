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
| 0014 | fix-ci-and-pypi-build | Done | P0 | 资产迁移后收敛“可运行/可测试/可打包”：修复 CI ruff 失绿、pytest 误扫外部仓库、PyPI 包缺失 `src/tradecat` 的结构性断裂 | ./0014-fix-ci-and-pypi-build/ |
| 0015 | unify-all-storage-to-postgres | In Progress | P0 | 数据库归一完全转型：彻底废弃 SQLite（指标库/状态库/幂等库），统一迁移到 `DATABASE_URL` 指向的 PostgreSQL（`tg_cards` + `signal_state` + `sheets_state`），并提供灰度切换与可回滚策略 | ./0015-unify-all-storage-to-postgres/ |
| 0016 | remove-sqlite-from-services | Done | P0 | SQLite 彻底出清（服务侧）：清理核心服务的 SQLite 残留（测试/默认值/文档/遗留 .db 文件），确保运行时只依赖 PostgreSQL；迁移脚本保留为工具 | ./0016-remove-sqlite-from-services/ |
| 0017 | migrate-consumption-to-query-service | Not Started | P0 | 统一数据消费为 Query Service（/api/v1）：消费层禁止直连 DB，仅通过稳定契约读取（并支持多数据源扩展） | ./0017-migrate-consumption-to-query-service/ |
| 0018 | stabilize-data-service-ban-backoff | Not Started | P0 | 修复 data-service 因 418 ban 触发的写库停滞与 ws 自愈重启风暴：统一识别 ban 并全局退避、收敛 backfill 并发、让守护逻辑对 ban 友好 | ./0018-stabilize-data-service-ban-backoff/ |
| 0019 | stabilize-data-service-ws-write | Done | P0 | 修复 data-service WS 1m K线不持续落库问题：修复 flush 窗口逻辑、回调桥接与写入覆盖策略，并收敛依赖漂移风险 | ./0019-stabilize-data-service-ws-write/ |
| 0020 | data-api-contract-hardening | In Progress | P0 | 将 api-service 升级为“稳定数据契约层”：新增 capabilities/cards/dashboard 稳定端点，迁移 TG/Sheets/Vis 消费，逐步清退表名直通接口以彻底遮蔽底层实现变动 | ./0020-data-api-contract-hardening/ |
| 0021 | harden-futures-datasources-fallback | Done | P0 | 对 futures 路由做 QueryService 化收口：统一改用 datasources(MARKET) 连接池、对 *_last 缺表做降级不 500、并将 /api/v1/indicators 表名直通端点标记 deprecated + 强制内网 token | ./0021-harden-futures-datasources-fallback/ |
| 0022 | api-service-contract-cleanup | Not Started | P0 | 完成契约层收口与一致性：补齐缺表结构化诊断字段、清理 api-service 路由的 get_pg_pool 直连散落（统一 datasources）、并对齐 tasks/文档状态避免运维漂移 | ./0022-api-service-contract-cleanup/ |

## 相关索引（单点入口）

- `docs/analysis/INDEX.md`：设计真相源 / 落地手册 / 运维加固 / 验收口径索引（强烈建议从这里开始读）。
- `docs/analysis/binance_vision_um_trades_dev_retrospective.md`：UM trades 从 0 到可长期跑的复盘（坑 → 根因 → 解决方案）。
- `docs/analysis/binance_vision_futures_um_book_data_full_ingestion_plan.md`：bookDepth/bookTicker 全量采集整理入库规划（分段推进 + 对账 + 成本控制）。
