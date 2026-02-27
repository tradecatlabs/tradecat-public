# Binance Vision UM Trades：逐笔事实表落地复盘（经验 / 教训 / 解决方案）

> 目标：把“从 0 到可长期跑”的全过程沉淀成**可复用工程记忆**：哪些坑必踩、为什么踩、怎么修、以后怎么避免。
>
> 范围：仅围绕 `futures/um/trades`（逐笔成交）这条主线；但其中不少教训对 CM/Spot/Book 系列同样适用。

---

## 0) 最终交付形态（我们现在真正拥有的）

### 0.1 单点真相源（SSOT）

- 文档索引入口：`docs/analysis/INDEX.md`
- DDL 真相源（禁止抄写运行库手工改）：
  - `assets/database/db/schema/008_multi_market_core_and_storage.sql`：`core/*` + `storage/*`
  - `assets/database/db/schema/009_crypto_binance_vision_landing.sql`：`crypto.raw_*`（含 UM trades 事实表）
  - `assets/database/db/schema/012_crypto_ingest_governance.sql`：`crypto.ingest_*`（run/watermark/gaps）
  - `assets/database/db/schema/013_core_symbol_map_hardening.sql`：`core.symbol_map` 语义硬约束
  - `assets/database/db/schema/016_crypto_trades_readable_views.sql`：trades 可读 view（时间戳 + as-of 映射）
  - `assets/database/db/schema/019_crypto_raw_trades_sanity_checks.sql`：raw trades sanity CHECK（上线护栏）

### 0.2 事实表（Atomic Fact）

- 表：`crypto.raw_futures_um_trades`
- 字段（8 列）：`venue_id,instrument_id,id,price,qty,quote_qty,time,is_buyer_maker`
- 主键（幂等键）：`PRIMARY KEY (venue_id, instrument_id, time, id)`
- Timescale：integer hypertable（`time=epoch(ms)`，chunk=1 day）
- 压缩：30d 后压缩；segmentby=`venue_id,instrument_id`，orderby=`time,id`
- 约束策略：只保留主键索引；默认 `*_time_idx` 必须禁用/删除（降低写入放大）

### 0.3 可追溯与治理（不污染事实表）

- 文件证据链：`storage.files / storage.file_revisions / storage.import_batches / storage.import_errors`
  - 用文件级 `sha256/.CHECKSUM` 阻断静默损坏与“同路径被替换”
- 运行元数据：`crypto.ingest_runs(meta jsonb)`（把吞吐/失败/跳过/压缩统计写入 meta）
- 治理闭环：`crypto.ingest_gaps` → repair worker → `open -> repairing -> closed`

### 0.4 采集/回填实现（仓库）

- 实时（WS 优先）：`services/ingestion/binance-vision-service/src/collectors/crypto/data/futures/um/trades.py`
- 官方回填（Vision ZIP）：`services/ingestion/binance-vision-service/src/collectors/crypto/data_download/futures/um/trades.py`
- 修复（gap repair）：`services/ingestion/binance-vision-service/src/collectors/crypto/repair/futures/um/trades.py`
- 维表自举/并发防重：`services/ingestion/binance-vision-service/src/writers/core_registry.py`
- 离线导入（本地 ZIP 并发）：`python3 -m src backfill --dataset crypto.data_download.futures.um.trades --local-only --workers N ...`

---

## 1) 这次最值钱的经验（按“会让系统咬人”的优先级排序）

### 1.1 事实表的“短主键 + 固定宽度”是生死线（不是优化项）

**问题**：用 `TEXT(exchange/symbol)` 做主键时，索引体积与写入放大随 symbol 数量线性上升，最终变成“越写越慢 / 越压越贵”。  
**解决**：把事实表主键收敛为 `(venue_id, instrument_id, time, id)`；维度解析放到 `core.*` 与 view 层完成。

### 1.2 schema drift（DDL 先改 / 写库还写旧列）会让采集当场崩

**问题**：仓库 DDL、运行库结构、写库代码三者只要不同步，表现就是：

- “列不存在 / 类型不匹配”
- 修复过程中出现二次漂移（越修越乱）

**解决**：迁移必须走“新表回迁 + rename-swap + 验收门禁”的标准套路（见 playbook），且以脚本为真相源。

### 1.3 integer hypertable 不是“建表就行”，now func / policy 必须补齐

**问题**：缺 `unix_now_ms()`/`set_integer_now_func(...)` 会导致 policy job 与压缩/保留行为不可控，后续运维会非常痛。  
**解决**：在 DDL 中写死 now func + integer hypertable + compression policy；并在验收 SQL 里强制检查（避免“看起来能插入”但 policy 不工作）。

### 1.4 压缩后的 UPDATE 是隐形炸弹：必须门禁 + 明确异常流程

**问题**：回填 `ON CONFLICT DO UPDATE` 如果打到已压缩 chunk，会触发透明解压/重压（成本爆炸，且容易把系统拖死）。  
**解决**：

- 正常路径：越过压缩线（或无法读取 compress_after）时 **fail-closed 降级为 DO NOTHING**
- 需要修复时：走 operator 离线流程（显式 `decompress_chunk -> UPDATE -> compress_chunk`），并把权限隔离出来（采集账号不能误触发）

### 1.5 as-of 映射必须由 DB 约束保障，不能靠 `LIMIT 1` 兜底

**问题**：`core.symbol_map` 如果允许出现两条 active（`effective_to IS NULL`），或者窗口重叠，view 就会“看起来还能跑”但语义已经被污染。  
**解决**：把语义写死到 DB：

- active 唯一（partial unique）
- 窗口自洽（`effective_to > effective_from`）
- 窗口不重叠（exclude constraint）
- 第一条映射 `effective_from=1970-01-01`，避免“映射创建晚于历史回填导致 view 取不到 symbol”

### 1.6 观测要进库：否则半年后你只剩日志地狱

**问题**：只靠日志，无法稳定回答“我导了多少、跳过多少、失败多少、压缩了多少 chunk、耗时在哪里”。  
**解决**：把关键指标写入 `crypto.ingest_runs.meta`，并保证多调用点兼容（jsonb 合并写入）。

---

## 2) 这次踩过的典型坑（现象 → 根因 → 修复方式）

```text
+-------------------------------+-------------------------------------------+----------------------------------------------+
| 现象                          | 根因                                      | 修复方式                                     |
+-------------------------------+-------------------------------------------+----------------------------------------------+
| 写库报“列不存在/类型不匹配”   | 运行库表结构落后于仓库 DDL                | 新表回迁 + rename-swap；禁止手工改列         |
| 压缩策略/保留策略不生效       | integer hypertable 缺 now func            | DDL 补 unix_now_ms + set_integer_now_func    |
| readable view 行数放大/爆炸    | symbol_map 窗口重叠或 join 不带窗口限制    | as-of join（effective_from/to）+ LATERAL+1   |
| 历史回填时 view 的 symbol 变 NULL | 映射 effective_from=now()，历史区间不覆盖 | 第一条映射 effective_from 固定为 epoch       |
| 回填越导越慢/系统抖动         | DO UPDATE 打到已压缩 chunk，触发解压重压   | 压缩窗口门禁 + operator-only 强制更新路径    |
| 全表 ORDER BY/去重查询报 OOM/锁 | hypertable chunk 太多，锁表数爆掉          | 只按时间窗查；用 storage.files 汇总；必要时调 max_locks |
+-------------------------------+-------------------------------------------+----------------------------------------------+
```

---

## 3) 强烈建议写死的“硬合同”（避免人肉记忆）

- **事实表只存原子字段**：不塞 `file_id/ingested_at/time_ts`（追溯走 `storage.*`，展示走 view）
- **回填冲突裁决**：
  - 实时：`DO NOTHING`
  - 官方回填：在压缩线前允许 `DO UPDATE`，越线降级 `DO NOTHING`
  - `DO UPDATE` 必须带 `IS DISTINCT FROM`（防无意义 UPDATE 写放大）
- **时间语义**：
  - `time` 为 epoch(ms) bigint，无时区；展示必须 `to_timestamp(time/1000.0) AT TIME ZONE ...`
- **目录契约**：代码目录镜像官方目录；`storage.files.rel_path` 必须使用官方相对路径（`data/...`）

---

## 4) 复核/验收的“最小证据集”（建议每次变更都跑）

- 结构：`\\d+ crypto.raw_futures_um_trades`（列/主键/类型）
- 行数：按 UTC 日窗对账（`storage.files.row_count` vs fact window count）
- Timescale：`timescaledb_information.hypertables` + `timescaledb_information.jobs`
- 压缩：统计未压缩 chunk 是否符合 compress_after 窗口
- 写库烟囱：最小 insert_rows/backfill 冒烟（输出 writer_ok / ingest_ok）

---

## 5) 下一步（只做高收益项，避免过早工程化）

- `bookTicker/bookDepth` 全量回填：优先把“可用数据范围 + 成本曲线”跑出来，再决定是否需要 double / ids 重构。
- 训练/回测数据集：用 continuous aggregate 或离线导出把 tick 压到可训练的 1s/5s bars（避免直接在 72 亿行上做研究）。
- ClickHouse：如果要做 L2/L3 或更严苛的微观结构研究，再上列式主仓；PG/Timescale 继续做治理与衍生聚合即可。
