# assets/database/db

这里的 DDL 现在被明确分成两套“数据库栈”（避免同名表在不同库里结构漂移导致写库崩溃）。

## 两套库的定位

### LF（低频/分时/K线与指标库）

- 目标对象：`market_data.*`（candles/metrics/continuous aggregates）
- 入口脚本：`assets/database/db/stacks/lf.sql`
- 典型实例：`localhost:5433/market_data`

初始化命令示例：

```bash
PGPASSWORD=postgres psql -h localhost -p 5433 -U postgres -d market_data \
  -f assets/database/db/stacks/lf.sql
```

### HF（高频/原子事实库）

- 目标对象：`core.*` + `storage.*` + `crypto.raw_*`（逐笔/订单簿/治理旁路）
- 入口脚本：`assets/database/db/stacks/hf.sql`
- 典型实例：`localhost:15432/market_data`

初始化命令示例：

```bash
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data \
  -f assets/database/db/stacks/hf.sql
```

## 重要约束（必须理解，否则必踩坑）

- `CREATE TABLE IF NOT EXISTS` 不会“升级”已存在的旧表结构：同名旧表仍会保留旧列/旧类型。
- 如果你看到“仓库 DDL 是 ids+DOUBLE，但运行库还是 exchange/symbol+NUMERIC”，这是 **schema drift**：
  - **不要**指望重复跑 DDL 入口脚本能修好；
  - 必须用 **rename-swap** 迁移脚本（或手工迁移）把旧表换成新表。

## 旧版 DDL 快照（仅用于对照）

- `assets/database/db/legacy_projects_tradecat/`：从旧项目路径拷贝的 LF DDL 快照（不要作为当前真相源）。

## 与服务配置的对应关系（避免混库）

- `DATABASE_URL`：建议固定指向 LF（给默认脚本/老服务兜底用）
- `DATA_SERVICE_DATABASE_URL`：data-service 专用（LF）
- `BINANCE_VISION_DATABASE_URL`：binance-vision-service 专用（HF）
