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

### 4.2 两种落库形态（必须先选定）

本仓库目前存在两种可行的“指标库落库形态”，二者互斥但可渐进迁移：

#### 方案 A：统一快照事实表（JSONB + 抽取列）

- 优点：可扩展、字段演进成本低、易做 latest/view/pivot
- 缺点：对齐旧 SQLite 的表结构需要额外做映射层（读写端要适配）

#### 方案 B：SQLite 表结构严格对齐（38 张表 1:1 迁入 PG）

- 优点：对现有读写端改动最小（表名/列名一致），更容易“先迁存储再慢慢重构”
- 缺点：表数量多、列名特殊（中文/标点/`.py`），SQL 引用必须全量双引号；后续要做统一分析与聚合会更难

> 本次你提出“严格对齐原 SQLite 表结构”，默认走 **方案 B**，并保留未来向方案 A 迁移的空间。

### 4.3 当前落地（✅方案 B：SQLite 表结构严格对齐）

本仓库当前已落地的“最小可用”实现：**把 `market_data.db` 的 38 张指标表 1:1 迁入 PG 的 `tg_cards` schema**，在写端提供 `sqlite|pg|dual` 开关，先完成“存储迁移”，再逐步推进读端 cutover。

- PG 目标库：LF Timescale（默认复用 `DATABASE_URL`）
- schema：`tg_cards`（可用 `INDICATOR_PG_SCHEMA` 覆盖）
- DDL 真相源：`assets/database/db/schema/021_tg_cards_sqlite_parity.sql`（已纳入 `assets/database/db/stacks/lf.sql`）

写入端（`services/compute/trading-service`）已落地：

- 开关：`INDICATOR_STORE_MODE=sqlite|pg|dual`
- 写入实现：`services/compute/trading-service/src/db/reader.py:PgDataWriter`
- 写入语义：
  - 列对齐：以 PG 表结构为准，缺列补 `NULL`，多列丢弃
  - 幂等：对含 `交易对/周期/数据时间` 的表，先删同 key 再插入
  - 保留窗口：按 `(交易对, 周期)` 保留每周期最新 N 条（window + `ctid` 精确删除）

读取端（telegram/sheets/api）目标：

- 引入 `INDICATOR_READ_SOURCE=auto|sqlite|pg`（`auto` 跟随 `INDICATOR_STORE_MODE`）
- 读取语义：优先用 SQL `DISTINCT ON` 拿 latest-per-symbol，避免“拉全历史再 Python 过滤”造成网络与 CPU 浪费

### 4.4 未来演进（方案 A：统一快照事实表 JSONB）

当你后续希望把“38 张表”的杂乱形态收敛成 BI 友好的 SSOT，可再演进到“统一快照事实表（JSONB + 抽取列）”的结构；但这不影响当前的方案 B 灰度切换与回滚路径。

## 5. 写入端改造（trading-service）

> 状态：**写端已落地**（SQLite/PG 可切换 + 支持双写）。

### 5.1 开关与配置（以仓库现状为准）

- `INDICATOR_SQLITE_PATH`：SQLite 指标库路径（默认 `assets/database/services/telegram-service/market_data.db`）
- `INDICATOR_STORE_MODE=sqlite|pg|dual`
- `INDICATOR_PG_SCHEMA=tg_cards`（当 `mode=pg|dual` 生效）
- PG 连接串：复用 `DATABASE_URL`（LF Timescale；与 K 线/期货指标同库）

### 5.2 写入实现（方案 B：表结构严格对齐）

- SQLite 写入：`services/compute/trading-service/src/db/reader.py:DataWriter`
- PG 写入：`services/compute/trading-service/src/db/reader.py:PgDataWriter`
- 开关分支：`services/compute/trading-service/src/core/storage.py`（按 `INDICATOR_STORE_MODE` 选择 `writer/pg_writer`）

写入语义（两端一致）：

- 列对齐：缺列补 `NULL`，多列丢弃
- 幂等：对含 `交易对/周期/数据时间` 的表，先删同 key 再插入
- 保留窗口：按 `(交易对, 周期)` 保留每周期最新 N 条（与 SQLite 口径一致）

### 5.3 性能策略（现实现）

- 批量写入：`executemany`（SQLite/PG）
- 单轮事务：批量写入多表在同一事务内提交（降低提交次数）
- 连接复用：PG 侧复用共享连接池（同 `DATABASE_URL`）

### 5.4 观测与回滚

- 灰度：先用 `INDICATOR_STORE_MODE=dual` 双写一段时间，对齐后再切 `pg`
- 回滚：任意异常可将 `INDICATOR_STORE_MODE` 回切 `sqlite`（前提：SQLite 仍可用）

## 6. 读取端改造（telegram/sheets/api）

### 6.1 切换顺序（推荐）

1. `sheets-service` 先切 PG（可容忍短暂不一致，易验证）
2. `telegram-service` 再切 PG（面向产出内容，需要更严格一致）
3. `api-service` 最后切 PG（对外接口可能有兼容风险）

### 6.2 读取方式

消费端直接读 `tg_cards.*`（方案 B：表结构 1:1 对齐），推荐按“取最新值”语义做轻薄查询：

- 排行榜（latest-per-symbol）：
  - `SELECT DISTINCT ON ("交易对") * FROM tg_cards."<表>" WHERE "周期"=$period ORDER BY "交易对","数据时间" DESC`
  - 目标：每个交易对只取最新一条（供排序/TopN）
- 基础数据（latest-batch）：
  - 先取该周期 `MAX("数据时间")`，再 `WHERE "数据时间"=max_ts` 拉出同批次全量币种
  - 目标：保证“价格/成交额/振幅”等公共字段来自同一批次
- 币种查询（单币 latest）：
  - `WHERE 交易对/币种 匹配 AND 周期=$period ORDER BY 数据时间 DESC LIMIT 1`

### 6.3 兼容与回滚

消费端引入读开关：

- `INDICATOR_READ_SOURCE=auto|sqlite|pg`

回滚策略：

- 任何异常可即时回切到 `sqlite`（前提：仍在 dual-write 或 SQLite 未被停写）

## 7. 历史回填（SQLite → PG）

### 7.1 回填目标

- 把 SQLite 中的指标历史（`market_data.db` 的 38 张表）回填到 PG 的 `tg_cards.*`（同表名/同列名）
- 回填必须幂等（可重复跑，重复跑不产生重复行）

### 7.2 回填方式

- 从 SQLite 逐表导出 → 逐表写入同名 PG 表（严格对齐，不做字段映射）
- 回填粒度：按“表 + 周期”分批（便于失败重跑与验收）

> TODO：回填脚本建议优先做“抽样对齐校验”（行数/最新时间戳/关键字段），再放开全量回填。

## 8. 验收标准（Definition of Done）

### 8.1 数据正确性

- 同一批次（相同 `数据时间`），PG 与 SQLite 在核心字段上值一致（同一 `(交易对, 周期, 数据时间)`）：
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

1. **幂等键规范化（方案 B）**
   - 输入：`交易对, 周期, 数据时间`
   - 断言：写端在 SQLite/PG 两侧均使用相同三元组作为幂等键（重复写入不产生重复行）
2. **列对齐（严格对齐）**
   - 断言：缺列补 `NULL`、多列丢弃，不因列漂移导致写入失败/重建表
3. **保留窗口（retention）**
   - 断言：同一 `(交易对, 周期)` 写入超过 `N` 条后，仅保留最新 `N` 条

### 9.2 集成测试（Integration）

1. **PG delete-by-key 幂等**
   - 同一批数据写两次，行数不变（同一 `(交易对, 周期, 数据时间)` 不出现重复）
2. **dual-write 一致性**
   - dual 模式写入后，抽样对比 SQLite 与 PG 的同表同 key 三元组：核心字段值一致
3. **读取 latest-per-symbol 正确**
   - 构造同一交易对的多条 `数据时间`，`DISTINCT ON` 查询返回最大 `数据时间`

### 9.3 回填测试（Migration/Backfill）

1. SQLite → PG 回填后：
   - 对抽样的 `表名 + 周期`：PG 行数 >= SQLite 行数
   - 幂等重复跑：PG 行数不增加（只允许同 key 覆盖/跳过）

### 9.4 端到端对齐（E2E）

1. 同一时刻导出 Sheets：
   - PG 读与 SQLite 读输出差异仅允许“格式差异”（例如小数显示），不允许“值差/缺行”
2. 同一时刻生成 TG 卡片：
   - 文案/排序/字段不变（只改变数据源）

## 10. 风险与缓解

### P0（会导致服务不可用）

- 写入爆炸（逐行写/无窗口清理）→ 强制批量写 + retention 清理 + 写入限流
- 幂等键错误导致重复/覆盖错位 → 统一 key 生成 + 单测覆盖

### P1（运行时才暴露）

- 特殊列名/表名导致 SQL 报错 → 全量双引号引用 + SQL builder（`psycopg.sql.Identifier`）
- `数据时间` 为 TEXT 导致“最新值”错 → 统一写入 ISO8601（UTC），并在读端约束排序字段

### P2（运维/成本问题）

- 历史保留导致表膨胀 → 现阶段 retention 已控量；后续再引入“按表/周期分级保留”与压缩策略

## 11. 执行路线图（建议拆分成可回滚小 PR）

1. PR#1：初始化 DDL + trading-service 支持 `INDICATOR_STORE_MODE=sqlite|pg|dual`（✅已完成）
2. PR#2：补齐 `.env.example` + 文档真相源对齐（✅进行中）
3. PR#3：切 `telegram-service` 读 PG（带 `INDICATOR_READ_SOURCE` 开关，可回滚）
4. PR#4：切 `sheets-service` / `api-service` 读 PG（同开关）
5. PR#5：对账脚本 + 可选索引脚本（仅加 index，不破坏结构对齐）
6. PR#6：停 SQLite 主写（如需；保留为离线快照/降级缓存）

## 12. TODO（必须补齐的“事实清单”）

1. SQLite 现有指标表清单与用途：
   - 命令：`sqlite3 assets/database/services/telegram-service/market_data.db ".tables"`
2. 消费端查询路径：
   - `telegram-service` 的读取入口函数/SQL（文件路径+函数名）
   - `sheets-service` 的读取入口函数/SQL（文件路径+函数名）
3. 每个 card 的字段 contract（最小必填/可选字段）
4. 保留周期策略（哪些 card 需要保留多久）
