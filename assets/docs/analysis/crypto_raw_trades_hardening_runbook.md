# Crypto Raw Trades 加固 Runbook（约束硬化 / 历史一致性 / 权限隔离）

> 目标：把“靠文档/约定维持”的关键语义，落到 **DDL + 可执行 runbook + 最小 RBAC**，避免半年后系统被脏数据/误操作反噬。

## 0. 范围与不变量

### 0.1 涉及对象

- 表：
  - `crypto.raw_futures_um_trades`
  - `crypto.raw_futures_cm_trades`
  - `crypto.raw_spot_trades`
  - `core.symbol_map`
- 视图（只读可读层）：
  - `crypto.vw_futures_um_trades`
  - `crypto.vw_futures_cm_trades`
  - `crypto.vw_spot_trades`

### 0.2 本 runbook 承诺（安全边界）

- **不删除任何事实表数据**：本 runbook 只新增/重建约束、创建只读 view、收紧高危函数权限。
- 约束会让“未来脏写”直接失败（这是预期）；历史数据若存在脏行，需要先修复再加固。

## 1. DDL 真相源（必须先对齐）

> 这些脚本应作为“真相源”，不允许靠人工在运行库里手敲一套“类似的”。

- `assets/database/db/schema/013_core_symbol_map_hardening.sql`
  - `core.symbol_map`：active 唯一性、窗口自洽、窗口不重叠（as-of 语义底座）。
- `assets/database/db/schema/016_crypto_trades_readable_views.sql`
  - trades readable views：`time(epoch)` → `timestamptz` + as-of `symbol_map` join（不放大行数）。
- `assets/database/db/schema/019_crypto_raw_trades_sanity_checks.sql`
  - raw trades 最小 sanity CHECK：`venue_id/instrument_id/time/id/price/qty/quote_qty` 不为负且时间>0。
  - 以 `NOT VALID` 方式上线：避免上线时全表扫描，但会对**新写入**强制校验。

## 2. 一键应用（DDL）

```bash
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -f assets/database/db/schema/013_core_symbol_map_hardening.sql
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -f assets/database/db/schema/016_crypto_trades_readable_views.sql
PGPASSWORD=postgres psql -h localhost -p 15432 -U postgres -d market_data -f assets/database/db/schema/019_crypto_raw_trades_sanity_checks.sql
```

## 3. 让历史也“硬一致”（019：validated CHECK 的正确姿势）

### 3.1 为什么不能用 `VALIDATE CONSTRAINT`

在启用 Timescale 压缩（columnstore）后的 hypertable 上，`ALTER TABLE ... VALIDATE CONSTRAINT ...` 在部分版本/组合上会报错（常见形态包括）：

- `operation not supported on hypertables that have columnstore enabled`
- `operation not supported on chunk tables`

因此：如果你要让历史也强一致，推荐走“**重建为 validated CHECK**”的等价路径。

### 3.2 低峰期执行：重建 validated CHECK（不改语义、不删数据）

> 这一步会扫描数据并短暂阻塞写入，务必低峰执行。  
> 推荐先设置 `lock_timeout`，避免卡死在锁等待里。

以 `crypto.raw_futures_um_trades` 为例（另外两张表同理替换表名与约束名）：

```sql
BEGIN;
SET LOCAL lock_timeout = '5s';

-- 1) 先新增一个“已验证”的 v2 约束（无 NOT VALID）
ALTER TABLE crypto.raw_futures_um_trades
  ADD CONSTRAINT chk_raw_futures_um_trades_sanity_v2
  CHECK (
    venue_id > 0
    AND instrument_id > 0
    AND time > 0
    AND id >= 0
    AND price >= 0
    AND qty >= 0
    AND quote_qty >= 0
  );

-- 2) v2 成功后，再删除旧的 NOT VALID 约束
ALTER TABLE crypto.raw_futures_um_trades
  DROP CONSTRAINT chk_raw_futures_um_trades_sanity;

-- 3) 约束名回收（保持外部脚本/审计口径不变）
ALTER TABLE crypto.raw_futures_um_trades
  RENAME CONSTRAINT chk_raw_futures_um_trades_sanity_v2
  TO chk_raw_futures_um_trades_sanity;

COMMIT;
```

### 3.3 验收：约束是否已 validated

```sql
SELECT conname, convalidated
FROM pg_constraint
WHERE conrelid IN (
  'crypto.raw_futures_um_trades'::regclass,
  'crypto.raw_futures_cm_trades'::regclass,
  'crypto.raw_spot_trades'::regclass
)
ORDER BY conrelid::regclass::text, conname;
```

> 说明：Timescale 会把约束“扩散/继承”到 chunks；你也可以额外按 chunk 名称做抽样核对（非必需）。

## 4. `--force-update` 的权限模型（operator-only）

### 4.1 设计原则

- 日常采集（realtime/backfill 默认）只允许走“低成本路径”（压缩窗口外冲突降级 `DO NOTHING`）。
- **只有 operator** 才能显式启用 `--force-update`，触发 `decompress_chunk -> DO UPDATE -> compress_chunk` 离线异常流程。

### 4.2 推荐 RBAC（最小可用）

> 目标：让 `tradecat_ingest` **不能**执行 `decompress_chunk/compress_chunk`，而 `tradecat_operator` 才能执行。

```sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradecat_ingest') THEN
    CREATE ROLE tradecat_ingest NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tradecat_operator') THEN
    CREATE ROLE tradecat_operator NOLOGIN;
    GRANT tradecat_ingest TO tradecat_operator;
  END IF;
END $$;

GRANT USAGE ON SCHEMA core, crypto, storage TO tradecat_ingest;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core, crypto, storage TO tradecat_ingest;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA core, crypto, storage TO tradecat_ingest;

-- 读取 Timescale 元信息（用于回填压缩门禁）
GRANT USAGE ON SCHEMA timescaledb_information TO tradecat_ingest;
GRANT SELECT ON ALL TABLES IN SCHEMA timescaledb_information TO tradecat_ingest;

-- 高危函数：默认 PUBLIC 可执行，必须收紧到 operator
REVOKE EXECUTE ON FUNCTION public.decompress_chunk(regclass, boolean) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.compress_chunk(regclass, boolean, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.decompress_chunk(regclass, boolean) TO tradecat_operator;
GRANT EXECUTE ON FUNCTION public.compress_chunk(regclass, boolean, boolean) TO tradecat_operator;
```

### 4.3 验收：权限是否正确

```sql
SELECT
  has_function_privilege('tradecat_ingest', 'public.decompress_chunk(regclass,boolean)', 'EXECUTE') AS ingest_can_decompress,
  has_function_privilege('tradecat_ingest', 'public.compress_chunk(regclass,boolean,boolean)', 'EXECUTE') AS ingest_can_compress,
  has_function_privilege('tradecat_operator', 'public.decompress_chunk(regclass,boolean)', 'EXECUTE') AS operator_can_decompress,
  has_function_privilege('tradecat_operator', 'public.compress_chunk(regclass,boolean,boolean)', 'EXECUTE') AS operator_can_compress;
```

> 如果你希望“真实区分账号”，请基于以上角色再创建 `LOGIN` 用户（例如 `tradecat_ingest_user` / `tradecat_operator_user`），并让采集服务使用 ingest 用户的连接串（`BINANCE_VISION_DATABASE_URL`，或回退 `DATABASE_URL`）。

## 5. 最小验收清单（上线前/上线后都可跑）

```sql
-- 1) views 存在
SELECT to_regclass('crypto.vw_futures_um_trades'),
       to_regclass('crypto.vw_futures_cm_trades'),
       to_regclass('crypto.vw_spot_trades');

-- 2) symbol_map 关键索引/约束存在（active 唯一 + 窗口自洽）
SELECT indexname FROM pg_indexes WHERE schemaname='core' AND tablename='symbol_map' ORDER BY indexname;
SELECT conname FROM pg_constraint WHERE conrelid='core.symbol_map'::regclass ORDER BY conname;

-- 3) raw trades sanity 约束存在
SELECT conname, convalidated
FROM pg_constraint
WHERE conname LIKE 'chk_raw_%_trades_sanity'
ORDER BY conname;
```
