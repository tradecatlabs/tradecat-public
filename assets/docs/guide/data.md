# 数据（Data）

本项目的数据流（高层）：

1. 采集层：`services/ingestion/*` 写入 TimescaleDB（raw/landing）
2. 计算层：`services/compute/trading-service` 计算指标并写入 SQLite（用于消费层展示）
3. 消费层：`services/consumption/*`（Telegram/API/Sheets）只读展示与导出

设计入口：

- `assets/docs/analysis/INDEX.md`
