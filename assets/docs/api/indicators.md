# API：指标（Indicators）

指标数据来自 PostgreSQL 指标库（`DATABASE_URL` 指向的 `tg_cards.*`）。

对外查询建议通过 `api-service` 暴露只读接口：

- `services/consumption/api-service/`
