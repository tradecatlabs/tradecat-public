# Query Service（统一数据消费接口）TDD / 设计说明

> 目标：把 TradeCat 当前“多服务各自直连 PG、各自解析字段/时间”的消费方式，升级为**契约化、版本化、可治理**的“统一查询服务（Query Service / Data API）”。  
> 适用范围：消费端（Telegram / Sheets / 外部前端/脚本）读指标与看板数据；写入链路（ingestion/compute）仍以直连 PG 为主，不走 HTTP。

---

## 0. 需求梳理（来自本次会话）

你提出的核心诉求可以抽象为一句话：

**“我只维护一套固定接口 + 真实数据源；其它所有消费方都只依赖这套接口。”**

更细分的隐含需求：

1) **单一出口（Single Read Gateway）**  
   - Telegram、Sheets、外部 API、前端看板：统一通过一个稳定接口读数据  
   - 避免多处复制：字段映射、时间解析、去重规则、最新行选择规则

2) **契约稳定（Contract-first）**  
   - 输出结构固定、可版本化（`/v1/...`），向后兼容  
   - 表结构内部可变，对外不变（反腐层）

3) **可靠与可审计**  
   - 明确“有效行”定义：过滤占位行/无效行（例如期货情绪的占位污染问题）  
   - 时间统一：UTC / UTC+8 展示一致，不再出现“看起来超前/落后”

4) **迁移与治理**  
   - 其它服务逐步迁移到 Query Service  
   - 形成硬约束：**数据消费必须走 Query Service**（通过脚本/CI 门禁 enforce）

> 本文的 “Query Service” 特指：**统一的“只读”查询层**（Single Read Gateway）。  
> 写入链路（ingestion/compute）继续直连 PG，避免引入网络可用性耦合。

---

## 1. 当前系统“数据调用/消费”现状（仓库事实）

### 1.1 当前主数据链路（事实）

```text
ingestion  ->  market_data.* (Timescale/PG)
compute    ->  tg_cards.*    (PG schema)
consumption(TG/Sheets/API)  <- tg_cards.* / market_data.*
```

### 1.2 当前消费端存在的“漂移风险”

- Telegram / Sheets / API 都各自实现了一套：
  - `"数据时间"(text)` 解析
  - `latest-per-symbol` 选择（DISTINCT ON / MAX / 排序）
  - 字段映射（卡片名->表名、字段名->展示名）
  - 占位/无效行过滤策略（不同处实现不同）
- `api-service` 里存在“动态 import telegram-service 的 data_provider.py”的强耦合实现（部署与路径依赖更脆）。

结论：**已经具备“服务化”的动机**——不是因为没有 API，而是因为读逻辑分散、契约不统一、治理困难。

---

## 2. 业内成熟方案对齐（你问的“最服务化/专业”）

对你当前规模与目标的“成熟默认值”是：

### 推荐组合：**Query Service（只读） + Contract-first + 反腐层**

- **写路径**（ingestion/compute）：继续直连 PG（最短链路、最高可靠性）  
- **读路径**（Telegram/Sheets/外部）：统一走 Query Service（稳定契约 + 缓存 + 限流 + 可观测）

这在业内一般叫：
- Data API / Query Service / 统一查询层 / Single Read Gateway
- 方法论：Contract-first + Anti-Corruption Layer（ACL）
-（可选演进）CQRS Read Model（读模型/投影）与缓存（Redis/物化表）

### 为什么这套对你当前是“最合适”的

1) 你现在的主要痛点是“读逻辑漂移”（字段映射/时间解析/最新行选择/占位过滤分散），不是“写入吞吐不足”。因此先收敛**读侧契约**收益最大。  
2) 你有多个消费端（TG、Sheets、未来更多统计/看板）。越早建立统一读出口，越少重复劳动，也越容易治理。  
3) 内部表名/字段名强业务化（含中文与脚本名风格），必须有一层**反腐层**把内部细节隔离，避免未来重构时牵一发动全身。  

---

## 3. 方案选择：新建服务 vs 复用现有 api-service

### 方案 A（推荐）：**将现有 `services/consumption/api-service` 升级为 Query Service**

理由：
- 已经是 FastAPI，已有 PG pool 与一批路由；
- 只需要：收敛接口语义、补齐 `/v1/dashboard`、`/v1/symbol/.../snapshot`、统一时间与过滤规则；
- 避免重复建一个“第二套 API 服务”。

### 方案 B：新建 `services/consumption/query-service`

理由：
- 逻辑更干净，不受历史路径/路由影响；
- 但会带来重复（第二套 FastAPI / pool / 部署脚本）。

**本 TDD 默认采用方案 A（复用 api-service，明确其角色=Query Service）。**  
（如果你坚持新建服务，也仅是“目录与启动脚本”不同，接口契约与迁移策略不变。）

---

## 4. Query Service 的职责边界（硬约束）

### In Scope（必须做）

1) 对外输出稳定契约（`/v1`）
2) 统一时间域（UTC tz-aware）与展示域（UTC+8 可选字段）
3) 统一“有效行”过滤策略（避免占位行/空行污染消费端）
4) 为看板/币种查询提供“聚合视图”（一次请求返回面板数据）
5) 可选缓存（内存 TTL；Redis 后续演进）

### Out of Scope（不做/后续）

- compute 写入改为 HTTP（不建议；核心链路不增加网络依赖）
- 立即把所有 tg_cards 表从 text 时间迁到 timestamptz（结构性重构，后续专门迁移）
- 引入 Kafka/事件流（除非下游数量/延迟目标明确上升）

---

## 5. 对外契约（Contract-first）

### 5.1 基本约定

- 所有响应统一 envelope：

```json
{ "success": true, "code": 0, "msg": "ok", "data": {...} }
```

- 所有端点必须返回**可机器解析**的结构化字段；禁止返回“拼接的文本伪表格”。  

- 所有时间输出至少包含：
  - `ts_utc`: RFC3339（`Z` 结尾）
  - `ts_ms`: epoch ms
  - 可选 `ts_shanghai`: RFC3339 +08:00（仅展示用）

### 5.2 稳定字段命名（反腐层约定）

内部表/字段可能是中文 + “脚本名.py”，对外必须稳定。建议：

- `card_id`: `snake_case`（稳定 key，例如 `atr`, `cvd`, `ema`, `futures_sentiment`）
- `card_title`: 原卡片标题（用于展示，例如 `📊 ATR数据`）
- `table_name`: 内部表名（仅 debug/管理员模式返回；默认不暴露，避免锁死内部结构）

### 5.3 通用错误码（建议）

- `0`：成功  
- `40001`：参数错误（缺必填/格式不对）  
- `40401`：资源不存在（card/symbol/interval 不支持）  
- `50001`：内部错误  
- `50301`：DB 不可用或超时  

> 注意：错误码要在文档与实现中**唯一来源**，禁止各服务各写一套。

### 5.4 必备端点（MVP）

1) `GET /api/v1/health`
   - 返回版本、commit（可选）、DB 连通性（可选）

2) `GET /api/v1/dashboard`
   - 用途：给 Sheets 主表/看板一次性拉取所有卡片的“最新快照”
   - Query 参数（建议）：
     - `intervals=5m,15m,1h,4h,1d,1w`
     - `symbols=BTCUSDT,ETHUSDT,...`（可选；默认按配置/高优先级集合）
     - `cards=atr,cvd,ema,...`（可选；默认全量）
     - `mode=latest`（仅最新）/`mode=window`（最近 N 个时间点）
     - `shape=wide|long`：输出形态（Sheets 推荐 `wide`，API/调试推荐 `long`）

3) `GET /api/v1/symbol/{symbol}/snapshot`
   - 用途：币种查询页，一次返回多面板结构化数据（基础/期货/高级）
   - 参数：`intervals=5m,15m,1h,4h,1d,1w`、`panels=basic,futures,advanced`

4) `GET /api/v1/indicators/{table}`
   - 用途：通用指标表查询（便于调试与扩展）
   - 参数：`symbol`、`interval`、`limit`、`order=desc|asc`

> 说明：你当前已有部分路由（`/api/...`），建议新增 `v1` 并逐步迁移旧路径到新路径（保持兼容期）。

---

## 6. 统一“有效行”定义（关键：防脏数据）

### 6.1 三键规则（必须）
- `交易对`、`周期`、`数据时间` 必须存在且非空

### 6.2 占位/空行过滤（建议）

对外输出时默认过滤以下行：
- 除三键外 `num_nonnulls(cols_except_keys)=0` 的全空行
- 指标特例：例如期货情绪要求 `持仓金额 IS NOT NULL`

> 备注：过滤规则应在 Query Service 内“唯一实现”，消费端不再重复写。

---

## 7. 时间标准化（UTC 基准）

### 7.1 输入端差异（现状）
- `market_data.candles_*`: `timestamptz`
- `market_data.binance_futures_metrics_*`: `timestamp without time zone`（语义=UTC）
- `tg_cards.*."数据时间"`: `text`（当前统一为 `...T...+00:00`）

### 7.2 Query Service 的统一规则
- 内部所有比较都使用 **UTC tz-aware datetime**
- `timestamp without time zone` 一律按 UTC 解释
- `text` 时间严格解析：
  - 支持 `Z`、`+00:00`、`T/空格`、无时区（默认 UTC）

---

## 8. 性能与查询模式（必须可扩展）

### 8.1 “最新快照”的正确 SQL 形态

- 推荐 `DISTINCT ON (symbol)`（或 `row_number partition`）取每币最新一行；
- 避免 `MAX(text)` 作为时间比较（text 字典序有潜在风险，除非确保格式永远规范）。

### 8.2 缓存策略（先轻后重）
- MVP：进程内 TTL 缓存（按 endpoint+params key）
- 后续：Redis（`GET /dashboard` 这类大查询最适合缓存）

---

## 9. 影响面盘点与迁移计划（必须可执行）

### 9.1 影响面（“谁在读数据”）

以当前仓库事实看，消费侧直连 PG 的主要位置：

- `services/consumption/telegram-service/src/cards/data_provider.py`：`PgRankingDataProvider`（直连 `tg_cards.*`）
- `services/consumption/sheets-service`：当前复用 TG 的导出逻辑 + 自己维护幂等/状态（含 PG 读写）
- `services/consumption/api-service/src/routers/*`：对外 API 读 PG（含 `tg_cards` 与 `market_data`）

目标状态：

> **除 Query Service 之外，`services/consumption/**` 不再允许直连 `tg_cards.*`（也不应该出现 SQL 片段）。**

### 9.2 需要迁移的消费方

1) `services/consumption/sheets-service`
   - 现状：直接读 PG + 自己做字段/时间解析与布局写入
   - 迁移：改为调用 Query Service 的 `/v1/dashboard`、`/v1/symbol/.../snapshot`

2) `services/consumption/telegram-service`
   - 现状：`PgRankingDataProvider` 直连 PG
   - 迁移：改为调用 Query Service（HTTP）；保留“直连 PG”作为短期 fallback（可用 env 开关控制）

3) `services/consumption/api-service`
   - 若采用“方案 A”：它就是 Query Service，本身不迁移；只做接口整理与兼容期重定向
   - 若采用“方案 B 新建”：原 api-service 退化为“外部 API 聚合”或直接废弃

### 9.3 强制约束（如何 enforce “消费必须走 Query Service”）

建议在 `scripts/verify.sh` 增加门禁（对 consumption 层生效）：
- 禁止在 `services/consumption/**/src` 直接出现：
  - `psycopg.connect(` / `psycopg_pool.ConnectionPool(`（除 query-service 外）
  - SQL 片段 `FROM tg_cards` / `tg_cards.`（除 query-service 外）
- 允许白名单：`services/consumption/api-service`（或 query-service）

### 9.4 迁移节奏（“不爆炸”的做法）

1) Query Service 先补齐 `/v1/dashboard` 与 `/v1/symbol/.../snapshot`（只读，不动写链路）  
2) sheets-service 切换为 HTTP（优先）：它最怕读逻辑漂移，也最需要聚合输出  
3) telegram-service 切换为 HTTP：把 `data_provider` 退化为 HTTP client + 适配器  
4) 最后再加门禁：一旦切换完成，CI/verify 直接阻断直连  

---

## 10. 测试设计（TDD 核心）

> 目标：保证“契约稳定 + 时间正确 + 过滤正确”。  
> 这三件事只要错一次，你就会在看板上看到“空行、超前/滞后、字段错位”等问题复发。

### 10.1 单元测试（必须）
- 时间解析：
  - `Z` / `+00:00` / 无时区 / `T` / 空格
- 有效行过滤：
  - 期货情绪 `持仓金额 IS NOT NULL`
  - 全空行过滤（num_nonnulls=0）

建议补充：
- 输出形态 `shape=wide|long` 的稳定性（字段顺序、周期集合、缺失值填充规则）
- “最新行”选择策略的稳定性（同一个 symbol+interval 多条时必须可解释、可复现）

### 10.2 集成测试（建议）
- 启动 Query Service（本地）
- 用测试库/本机库跑：
  - `/v1/dashboard` 返回结构完整且时间字段齐全
  - `/v1/symbol/BTCUSDT/snapshot` 多周期齐全

### 10.3 契约测试（强烈建议）

- 以 OpenAPI schema 为“真理源”，对响应做 schema 校验（字段存在/类型正确/必填不缺）。  
- 这会显著降低“改了内部字段映射导致 TG/Sheets 静默坏掉”的风险。

---

## 11. 回滚策略

- 迁移期采用“双栈”：
  - 消费端新增 `USE_QUERY_SERVICE=1` 开关（默认关→逐步灰度）
  - 出问题一键回退到直连 PG（临时止血）
- Query Service 自身版本化：`/v1` 不破坏，新增走 `/v2`

---

## 12. 交付清单（Definition of Done）

1) Query Service 提供 `/v1/dashboard`、`/v1/symbol/.../snapshot` 并可在本机跑通
2) 统一时间字段输出（`ts_utc/ts_ms/ts_shanghai`）与有效行过滤
3) `sheets-service` 与 `telegram-service` 至少一个完成迁移并可回滚
4) `scripts/verify.sh` 添加门禁：消费端禁止直连 tg_cards（白名单除外）

---

## 13. 实现落点（建议的模块结构：复用 api-service）

如果采用“方案 A（升级 api-service）”，建议在 `services/consumption/api-service/src/` 新增一个清晰的 query 层：

```text
src/
├── app.py
├── config.py
├── query/
│   ├── __init__.py
│   ├── models.py              # Pydantic 响应模型（契约）
│   ├── time.py                # 时间解析/规范化（唯一实现）
│   ├── filters.py             # 有效行过滤（唯一实现）
│   ├── dao.py                 # SQL / 数据访问层（只读）
│   └── service.py             # 业务聚合：dashboard/snapshot
└── routers/
    ├── query_v1.py            # /api/v1/...
    └── ...                    # 现有 coinglass 风格路由（兼容期保留）
```

核心原则：

- `routers` 不写 SQL；只做入参校验/调用 service/返回响应  
- SQL 全部进 `dao.py`（可统一 timeout、统一 explain、统一注入 schema）  
- `filters.py/time.py` 作为“全仓唯一实现”，其它消费服务只调用 HTTP，不再复制粘贴  

---

## 14. 安全与访问控制（默认内网，只读）

你当前的使用形态更像“内部基础设施”。推荐最小安全默认值：

1) 网络层：Query Service 只监听内网/本机（或通过反代限制访问）  
2) 应用层：增加一个轻量内部 token（例如 `X-Internal-Token` header）  
3) 权限层：只读；禁止任何写接口进入 Query Service  

> 如果未来要公开给第三方，再单独做 OAuth/用户体系；现在不要过度工程。

---

## 15. 可观测性与运行时默认值（建议）

1) 每个请求打印结构化日志字段：
   - `request_id`、`path`、`status_code`、`duration_ms`、`db_time_ms`、`cache_hit`
2) 对慢查询设置红线：
   - `statement_timeout`（DB）+ `request_timeout`（HTTP client）
3) 统一超时与重试策略：
   - 消费端（sheets/telegram）只做**有限重试**，避免雪崩  
4) 版本与构建信息：
   - `/api/v1/health` 返回 `version`（以及可选 `git_sha`）
