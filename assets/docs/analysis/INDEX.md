# assets/docs/analysis 索引（单点真相入口）

> 目标：让后来者在 30 秒内找到“设计真相源 / 落地手册 / 运维加固 / 验收口径”，避免文档互相打架。

## 1) Binance Vision / trades 主线

- `assets/docs/analysis/crypto_trades_fact_table_pro_design.md`：逐笔事实表（ids+DOUBLE+integer hypertable）全局设计，含冲突裁决与窗口合同。
- `assets/docs/analysis/binance_vision_um_trades_mature_playbook.md`：UM trades 从 0→1 落地手册（迁移/验收/运维）。
- `assets/docs/analysis/binance_vision_um_trades_local_only_import.md`：UM trades 离线本地导入（local-only，多 worker，并发 + 自动压缩）。
- `assets/docs/analysis/binance_vision_um_trades_maturity_audit.md`：UM trades 成熟化审计快照（现状 vs 目标）。
- `assets/docs/analysis/binance_vision_um_trades_dev_retrospective.md`：逐笔事实表落地复盘（踩坑清单 + 根因 + 解决方案）。
- `assets/docs/analysis/binance_vision_db_physical_design.md`：crypto/core/storage 物理层说明（表职责、主键、时间语义）。
- `assets/docs/analysis/binance_vision_field_dictionary.md`：字段字典（对齐 Vision CSV 的字段语义与类型）。

## 1.1) Binance Vision / futures.um book 数据（bookDepth / bookTicker）

- `assets/docs/analysis/binance_vision_futures_um_book_data_full_ingestion_plan.md`：bookDepth/bookTicker 全量回填规划（分段推进、对账、落盘策略）。
- `assets/docs/analysis/binance_vision_futures_um_book_depth_curve_explained.md`：bookDepth 曲线白话解释（是什么/为什么/怎么用/与官方差异）。

## 2) 加固与运维（强烈建议先读）

- `assets/docs/analysis/crypto_raw_trades_hardening_runbook.md`：trades sanity 约束“历史硬一致”、`--force-update` operator-only 权限隔离、验收 SQL。
- `assets/docs/analysis/layer_contract_one_pager.md`：采集→处理→消费的输入输出、幂等键、时间语义与观测指标（总合同）。
- `assets/docs/analysis/crypto_atomic_common_fields_contract.md`：原子事实表公共字段契约（`venue_id/instrument_id` 的构造与三种写入类型收敛口径）。

## 3) DDL 真相源（仓库内脚本）

> 以脚本为准，禁止在运行库手工“抄一份类似的”。

- `assets/database/db/schema/008_multi_market_core_and_storage.sql`：`core/*` 与 `storage/*`（维表 + 文件审计证据链）。
- `assets/database/db/schema/009_crypto_binance_vision_landing.sql`：`crypto.raw_*` 事实层（落库短主键、压缩/分片策略）。
- `assets/database/db/schema/012_crypto_ingest_governance.sql`：`crypto.ingest_*` 治理旁路（runs/watermark/gaps）。
- `assets/database/db/schema/013_core_symbol_map_hardening.sql`：`core.symbol_map` 语义硬约束（active 唯一/窗口自洽/窗口不重叠）。
- `assets/database/db/schema/016_crypto_trades_readable_views.sql`：UM/CM/Spot trades readable views（as-of join + 时间戳转换）。
- `assets/database/db/schema/019_crypto_raw_trades_sanity_checks.sql`：raw trades 最小 sanity CHECK（默认 NOT VALID，上线护栏）。
- `assets/database/db/schema/018_core_binance_venue_code_futures_um.sql`：兼容迁移脚本（历史把 `futures_um` 写在 `venue_code=binance` 的环境使用）。
- `assets/database/db/schema/020_crypto_futures_book_ids_swap.sql`：bookDepth/bookTicker ids 迁移脚本（旧结构运行库 rename-swap 保留 *_old）。

## 4) 执行任务索引

- `assets/tasks/INDEX.md`：任务总索引（按 ID/优先级/目标）。

## 5) Telegram → Google Sheets 看板（TG 卡片公共表格化）

- `assets/docs/analysis/tg_cards_google_sheets_dashboard_prd.md`：PRD（卡片块 x,y 渲染 + 全字段无遗漏审计 + Webhook/幂等/outbox）。
- `assets/docs/analysis/tg_cards_google_sheets_apps_script_webhook.md`：Apps Script Webhook 参考实现（doPost：鉴权/幂等/落事实/渲染）。
- `assets/docs/analysis/sheets_dashboard_source_info_compaction_plan.md`：展示面优化方案：源信息 5 行压缩为 1 单元格（固定顺序拼接）。
- `assets/docs/analysis/sheets_dashboard_optimization_options.md`：优化选项集（K1..K7）：配额/吞吐/事实面 cells 上限/性能/运维。
- `assets/docs/analysis/sheets_dashboard_flicker_free_refresh_design.md`：无感刷新最优方案：增量覆盖写 + 原子 batchUpdate + 样式模板化 + 夜间 defrag。
