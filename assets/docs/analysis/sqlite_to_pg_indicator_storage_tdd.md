# TDD：指标/看板数据从 SQLite 迁移到 PostgreSQL/TimescaleDB

## 1. 背景与现状

### 1.1 现状（Single Writer / Multi Reader）

- 写入端：`services/compute/trading-service`
  - 产出：指标结果、排行榜/卡片所需字段、运行元信息等
  - 当前落地：`assets/database/services/telegram-service/market_data.db`（SQLite）
- 读取端（消费端）：
  - `services/consumption/telegram-service`：生成 TG 卡片
  - `services/consumption/sheets-service`：渲染 Google Sheets 看板（方案5）
  - `services/consumption/api-service`：提供查询接口（如有）

### 1.2 迁移动机

- 统一存储：派生指标从“本地文件库”升级为“中心化 PG/Timescale”
- 可扩展：多消费者/多机器共享一份真相源
- 可运维：更好的幂等、索引、权限、备份与审计

## 2. 目标与非目标

### 2.1 目标（Goals）

1. PG 成为指标/看板派生数据的单一真相源（SSOT）
2. 支持双写与可回滚切换（先 dual-write，后 cutover）
3. 在不删减内容前提下，保持现有卡片/看板输出的字段完整性与语义一致
4. 写入具备幂等与可重复回放能力（重复运行不产生重复/错乱）

### 2.2 非目标（Non-Goals）

- 不把逐笔/订单簿明细灌入 Sheets
- 不在本次迁移中重构全部指标计算逻辑（只改存储层 + 读取路径）
- 不强制删除 SQLite（可保留为本地缓存/离线快照，作为降级路径）

## 3. 术语与数据语义

- `bucket_ts`：指标对应的“时间桶”时间戳，必须统一为 UTC（展示再转 UTC+8）
- `export_ts`：导出/渲染时刻（UTC/UTC+8 由消费端决定）
- `card_id`：卡片/榜单的稳定标识（例：`atr`, `supertrend`, `cvd` 等）
- `interval`：周期（例：`5m`,`15m`,`1h`,`4h`,`1d`,`1w` 等；**是否保留 `1m` 由 UI 层决定**）
- `payload`：卡片需要的全字段结构化数据（JSONB）

## 4. 总体设计（High-Level Design）

### 4.1 设计原则

1. **写入是 append/upsert 的快照流**：写入端只写“快照”，禁止跨行复杂更新
2. **读优化用视图/物化视图**：尽量让消费端只做轻薄拼装
3. **结构变化快 → JSONB + 少量抽取列**：避免“每个卡片一张宽表”的 DDL 维护噩梦
4. **双写可控**：开关化、可观测、可回滚

### 4.2 推荐 PG 结构（两层）

#### A) 事实层（SSOT）：`dashboard.card_snapshots`

用途：保存每次计算/导出的“卡片快照”，可追溯、可回放、可复算。

推荐字段：

- `card_id` (text, not null)
- `card_title` (text, not null)
- `exchange` (text, not null) — 例：`binance_futures_um`
- `symbol` (text, not null) — 例：`BTCUSDT`
- `interval` (text, not null) — 例：`15m`
- `bucket_ts` (timestamptz, not null) — 指标桶时间（UTC）
- `export_ts` (timestamptz, not null) — 写入时刻（UTC）
- `updated_at` (timestamptz, not null) — upsert 更新时刻（UTC）
- `payload` (jsonb, not null) — 卡片所需全字段

幂等唯一键（必须）：

- `UNIQUE(card_id, exchange, symbol, interval, bucket_ts)`

抽取列（可选，但推荐，用于排序/过滤/上色）：

- `direction` (smallint) — -1/0/+1
- `score` (double precision)
- `volume_quote` (numeric)
- `rank` (integer)
- `severity` (text)

索引（最低要求）：

- `(card_id, symbol, interval, bucket_ts DESC)`
- `(card_id, interval, bucket_ts DESC)`
- `(bucket_ts DESC)`
- 如存在按成交额排序：`(card_id, interval, volume_quote DESC NULLS LAST)`

#### B) 读优化层：`dashboard.card_latest`（view / materialized view）

用途：快速取“每个 (card_id, exchange, symbol, interval) 最新一条”。

实现方式：

- view：`DISTINCT ON (...) ORDER BY bucket_ts DESC`
- 或物化视图：按刷新频率（例如 10s/30s）定时刷新

> 注：Timescale continuous aggregate 更适合“可聚合的数值指标”，对 JSONB 快照不一定划算；先用 view，后续再按压测演进。

## 5. 写入端改造（trading-service）

### 5.1 引入存储抽象

定义 `IndicatorStore`（接口层，不绑定实现）：

- `upsert_snapshots(card_id, interval, rows[])`（批量 upsert）
- `healthcheck()`（写库探测）

实现：

- `SQLiteIndicatorStore`（旧实现）
- `PostgresIndicatorStore`（新实现）
- `DualWriteStore`（双写：PG + SQLite，带容错策略）

### 5.2 写入语义

- 每轮计算输出一批 snapshots（同一轮可覆盖同 `bucket_ts` 的值 → upsert）
- upsert 冲突策略：
  - 以 `bucket_ts` 为幂等键，`payload` 全量覆盖
  - `updated_at` 更新为当前时间
  - `export_ts` 记录本次写入时间（可等于 `updated_at`）

### 5.3 性能策略

- 只允许批量写：`INSERT ... VALUES (...) ON CONFLICT DO UPDATE`
- 禁止逐行写入（会把 PG 写爆）
- 写入限流：对齐当前 `trading-service` 轮询节奏，必要时在 store 内做队列/合并写

### 5.4 配置开关（建议）

新增环境变量（写入端）：

- `INDICATOR_STORE_MODE=sqlite|pg|dual`
- `INDICATOR_STORE_PG_URL=postgresql://...`（可复用 `DATABASE_URL` 或独立）
- `INDICATOR_STORE_PG_SCHEMA=dashboard`
- `INDICATOR_STORE_FAILOVER=on|off`（dual 模式下允许 SQLite 兜底）

> TODO：以仓库现有 `config/.env.example` 为准落地命名，避免引入重复配置键。

## 6. 读取端改造（telegram/sheets/api）

### 6.1 切换顺序（推荐）

1. `sheets-service` 先切 PG（可容忍短暂不一致，易验证）
2. `telegram-service` 再切 PG（面向产出内容，需要更严格一致）
3. `api-service` 最后切 PG（对外接口可能有兼容风险）

### 6.2 读取方式

消费端读“latest 视图”：

- 维度：`card_id + interval`（排行榜） 或 `card_id + symbol + interval`（币种查询）
- 输出：直接对齐当前卡片字段 contract（保持结构不变）

### 6.3 兼容与回滚

消费端引入读开关：

- `INDICATOR_READ_SOURCE=sqlite|pg`

回滚策略：

- 任何异常可即时回切到 `sqlite`（前提：仍在 dual-write 或 SQLite 未被停写）

## 7. 历史回填（SQLite → PG）

### 7.1 回填目标

- 把 SQLite 中用于看板/币种查询的历史指标灌入 `dashboard.card_snapshots`
- 回填必须幂等（可重复跑）

### 7.2 回填方式

- 从 SQLite 逐表导出 → 映射成统一 snapshot 结构 → 批量 upsert 到 PG
- 回填粒度：按 `card_id` 分批（便于失败重跑与验收）

> TODO：需要先完成“SQLite 表清单 → card_id 映射表”（见第 9 节测试用例与盘点项）。

## 8. 验收标准（Definition of Done）

### 8.1 数据正确性

- 同一时刻（相同 `bucket_ts`），PG 与 SQLite 在核心字段上值一致：
  - 价格、成交量、成交额、方向、评分、排名等（以卡片 contract 为准）

### 8.2 稳定性

- `trading-service` + `data-service` 连续运行 24h
  - PG 写入无持续冲突/爆炸性增长
  - 看板渲染无断流

### 8.3 可回滚

- 关闭 PG 写入（或切回 sqlite）后，系统可在 1 分钟内恢复“旧路径可用”

## 9. TDD：测试计划（按先写测试再实现）

> 原则：每个阶段都要有“可自动化验证”的证据；否则迁移一定会在 cutover 时爆雷。

### 9.1 单元测试（Unit）

1. **快照键规范化**
   - 输入：`card_id,symbol,interval,bucket_ts`
   - 断言：生成的幂等键一致（大小写/空白/UTC 规范化）
2. **payload contract 校验**
   - 对每个 card：必填字段存在（缺字段直接失败）
3. **抽取列一致性**
   - `direction/score/volume_quote/rank` 从 payload 抽取的规则固定，测试覆盖正负/空值

### 9.2 集成测试（Integration）

1. **PG upsert 幂等**
   - 同一批数据写两次，行数不变，`updated_at` 递增
2. **dual-write 一致性**
   - dual 模式写入后，从 PG 与 SQLite 读出的同一 `(card_id,symbol,interval,bucket_ts)` 一致
3. **读取 latest 正确**
   - 构造多条 bucket_ts，latest 视图返回最大 bucket_ts

### 9.3 回填测试（Migration/Backfill）

1. SQLite → PG 回填后：
   - 对抽样的 `card_id`、`symbol`、`interval`：PG 行数 >= SQLite 行数
   - 幂等重复跑：PG 行数不增加（只允许更新）

### 9.4 端到端对齐（E2E）

1. 同一时刻导出 Sheets：
   - PG 读与 SQLite 读输出差异仅允许“格式差异”（例如小数显示），不允许“值差/缺行”
2. 同一时刻生成 TG 卡片：
   - 文案/排序/字段不变（只改变数据源）

## 10. 风险与缓解

### P0（会导致服务不可用）

- 写入爆炸（逐行写/无索引）→ 强制批量 upsert + 指标索引 + 写入限流
- 幂等键错误导致重复/覆盖错位 → 统一 key 生成 + 单测覆盖

### P1（运行时才暴露）

- JSONB payload 演进导致读端解析崩溃 → contract 校验 + 版本号字段（可选：`payload_version`）
- 时区混乱导致“最新值”错 → bucket_ts 强制 UTC + 读端展示转换

### P2（运维/成本问题）

- 历史保留导致表膨胀 → 后续加 TTL（按 card/interval 分级保留）+ Timescale 压缩策略

## 11. 执行路线图（建议拆分成可回滚小 PR）

1. PR#1：引入 `PostgresIndicatorStore`（仅写入端，默认关闭）
2. PR#2：dual-write 模式上线（PG+SQLite），加一致性对账脚本
3. PR#3：SQLite→PG 回填工具与映射表
4. PR#4：切 `sheets-service` 读 PG（带开关）
5. PR#5：切 `telegram-service` 读 PG（带开关）
6. PR#6：切 `api-service` 读 PG（带开关）
7. PR#7：停 SQLite 主写入（保留缓存/或废弃）

## 12. TODO（必须补齐的“事实清单”）

1. SQLite 现有指标表清单与用途：
   - 命令：`sqlite3 assets/database/services/telegram-service/market_data.db ".tables"`
2. 消费端查询路径：
   - `telegram-service` 的读取入口函数/SQL（文件路径+函数名）
   - `sheets-service` 的读取入口函数/SQL（文件路径+函数名）
3. 每个 card 的字段 contract（最小必填/可选字段）
4. 保留周期策略（哪些 card 需要保留多久）

