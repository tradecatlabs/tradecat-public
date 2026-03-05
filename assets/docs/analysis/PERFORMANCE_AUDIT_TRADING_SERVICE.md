# Trading-Service Python 性能优化审计报告（静态审计版）

日期：2026-01-22  
范围：`services/compute/trading-service`（指标计算服务：K线 + 期货情绪 → PostgreSQL(tg_cards.*)；SQLite 分析为历史路径）  
审计方法：代码静态扫描 + 结构/复杂度分析 + 可复现实证（profiling 计划）  

> 更新（2026-03）：trading-service 的指标落盘已切换为 PostgreSQL（`tg_cards.*`），不再依赖 `market_data.db`。  
> 本报告中关于 SQLite 写入路径（delete/cleanup/commit 放大）的结论属于**历史优化记录**：用于解释“旧版为什么会慢”，不应直接当作当前线上瓶颈结论。

> 说明：本报告未直接在你的生产数据与数据库上运行 profiling，因此“热点”结论默认标记为【推断】；每个【推断】都附带可执行的验证方法，用于把推断转成证据并量化收益。

---

## 【0. 执行摘要】

### 0.1 当前最可能瓶颈 Top 3（结论一句话版）

1) 【推断】期货类指标在 `compute()` 内部直接 `psycopg.connect()` + 查询，形成典型 N+1 查询与连接风暴（IO/延迟主导，扩展性最差）。  
2) 【推断】SQLite 写入路径存在“逐行 delete + 逐组清理 + 每表 commit”的组合，导致 SQL 语句数量与事务次数随 `symbols * intervals * indicators` 线性爆炸（IO/锁竞争/日志写放大）。  
3) 【推断】部分指标存在 Pandas 反模式（`apply(axis=1)` / `iterrows()`）与 Python 循环，造成 CPU 常数项巨大；在默认 `thread` 后端下容易被 GIL/线程调度吞噬（CPU/可扩展性受限）。

### 0.2 最快可落地的 3 个优化动作（1~2 小时）

1) 把 `services/compute/trading-service/src/indicators/batch/tv_trend_cloud.py:62` 的 `df.apply(axis=1)` 改为矢量化表达（常数项显著下降，几乎零风险）。  
2) 把 `services/compute/trading-service/src/db/reader.py:283-285` 与 `:314-332` 的 `iterrows()` 发 SQL 改为 `executemany`，并把多表写入合并为单事务（写入阶段通常立刻变快）。  
3) 先“禁止期货指标在 compute 内做 IO”：把 PG 查询移到读阶段批量拉取并缓存，再把数据注入指标（先把 N+1 砍掉，收益通常最大）。

### 0.3 预期整体收益区间 & 不确定性来源

- 预期整体收益：2x~10x（甚至更高）。  
- 不确定性来源：
  - 你的实际 `symbols` 数量、周期数、指标数；
  - TimescaleDB/SQLite 的磁盘与网络延迟；
  - 当前运行时 `读取/计算/写入` 三段占比（`Engine.run` 已打印该信息，见验证清单）。

---

## 【1. 入口与数据流（你现在的系统“到底在干什么”）】

### 1.1 运行入口（以代码为准）

- 推荐入口：`cd services/compute/trading-service && python -m src --once --mode all`  
  - 入口文件：`services/compute/trading-service/src/__main__.py`  
  - 注意：`__main__.py` 的 docstring 仍写 `python -m indicator_service`，这与实际包名 `src` 不一致（可维护性坏味道：文档偏离真实入口，容易导致错误 profiling）。

### 1.2 核心数据流（按执行顺序）

1) 选币：若未指定 `--symbols`，会从 PG 计算高优先级币种（`services/compute/trading-service/src/core/engine.py` 调用 `get_high_priority_symbols_fast`）。  
2) 读数据：通过 `services/compute/trading-service/src/db/cache.py` 的 `DataCache` 从 TimescaleDB 拉取各 `interval` 的 candles（看起来是“缓存初始化 + 增量更新”模式）。  
3) 算指标：`services/compute/trading-service/src/core/engine.py` 的 `_compute_batch` 对每个 `(symbol, interval)` 运行所有指标 `Indicator.compute()`。  
4) 写结果：把所有指标结果写入 PostgreSQL `tg_cards.*`（写入代码：`services/compute/trading-service/src/db/reader.py:DataWriter`；旧版为 SQLite `market_data.db`）。  
5) 后处理：根据需要更新市场占比与做保留/清理（旧版包含 “PG → SQLite” 与 SQLite DELETE；现行以 PG 侧策略为准）。

### 1.3 规模敏感性（决定你为什么“会突然慢”）

用最重要的三维度描述工作量：

- S = symbols 数（默认从优先级里取，常见 15~30；极端可到几百）  
- I = intervals 数（默认 7：1m,5m,15m,1h,4h,1d,1w）  
- K = indicators 数（目前 `services/compute/trading-service/src/indicators` 约 30+）

大多数阶段都至少是 O(S*I*K) 的“任务数”放大器；如果在任务内部再出现 IO（N+1）或 Python 循环（row-by-row），性能会以“线性放大 + 巨大常数项”的方式崩掉，表现为：加几个币种或加一个周期就变得不可控。

---

## 【2. 热点与证据（静态推断 + 你该如何把它变成证据）】

> 表格中的“证据/依据”严格引用具体文件/行号与结构性原因；如无法直接断言，则标记【推断】并给出验证路径。

| 热点位置 | 现象 | 证据/依据（代码引用） | 资源类型 | 复杂度敏感性（前→后） |
|---|---|---|---|---|
| `services/compute/trading-service/src/indicators/batch/futures_aggregate.py:140-178` + `:187-193` | 期货情绪聚合：每次 compute 直接连 PG 查 history | `get_metrics_history()` 内部 `psycopg.connect(...)`；`FuturesAggregate.compute()` 每次调用都 `history = get_metrics_history(symbol, 240, interval)` | IO/网络/DB | O(S*I) 次查询/连接 → 目标 O(I) 次批量查询 |
| `services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py:8-33` + `:67-73` | 缺口监控：每次 compute 直接连 PG 查 times | `get_metrics_times()` 内部 `psycopg.connect(...)`；`FuturesGapMonitor.compute()` 每次调用都查询 | IO/网络/DB | O(S) → 目标 O(1)（5m 一次批量） |
| `services/compute/trading-service/src/core/engine.py:261-275` + `services/compute/trading-service/src/db/reader.py:253-297` | SQLite 写：每指标表一次写入且每表 commit | `_write_simple_db()` 对每个 indicator 调 `sqlite_writer.write()`；`DataWriter.write()` 最后 `conn.commit()` | IO/锁/FSync | 事务数 O(K) → 目标 O(1) |
| `services/compute/trading-service/src/db/reader.py:281-285` | 写入前逐行 delete | `for _, row in ...drop_duplicates().iterrows(): conn.execute(DELETE...)` | IO + Python 循环 | 语句数 O(rows)（慢常数）→ O(rows)（但 executemany 降常数） |
| `services/compute/trading-service/src/db/reader.py:314-332` | 清理旧数据逐组循环 delete | 对每个 (交易对,周期) 执行一次 DELETE ... NOT IN(...) | IO + Python 循环 | 语句数 O(unique(S,I)) → 可合并/异步/延后 |
| `services/compute/trading-service/src/indicators/batch/tv_trend_cloud.py:62` | `df.apply(axis=1)` | 明确 Pandas 反模式：row-wise apply | CPU | O(n)→O(n)，常数项通常 10x 级下降 |
| `services/compute/trading-service/src/indicators/batch/vpvr.py:72-85` | `iterrows()` 扫行 | 明确 Pandas 反模式：iterrows | CPU | O(n)→O(n)，向量化/np.add.at 降常数 |
| `services/compute/trading-service/src/db/cache.py:112-150` | K线增量更新按 symbol 循环查询 | `for symbol in symbols: conn.execute(...)` | IO/网络/DB | O(S) queries/interval → 目标 O(1) query/interval |
| `services/compute/trading-service/src/db/cache.py:156-165` | 从缓存取数据强制 `.copy()` | `return {s: df.copy() ...}` | 内存 + CPU | O(S) copy/interval；S 大时内存翻倍 |
| `services/compute/trading-service/src/core/engine.py:198-203` | process 后端需 pickle 每个 df | `pickle.dumps(df, protocol=5)` | CPU + 内存 | O(S*I*size(df)) 序列化；应只对“慢指标”使用 |

---

## 【3. Profiling 计划（你该怎么跑，跑完你会得到什么证据）】

> 目标：把“读/算/写”三段耗时拆清楚；确认是否存在 N+1 IO；找出 CPU 热点指标；量化峰值内存与对象分配。

### 3.1 最小复现集（先把变量固定住）

建议先固定参数，否则 profiling 结果不可比：

- symbols：建议 10~30 个（例如 `BTCUSDT,ETHUSDT,...`）  
- intervals：先 2 个（`5m,1h`），再逐步扩到 7 个  
- mode：`--mode all`（你要审计的是全链路）  

示例命令：

```bash
cd services/compute/trading-service
python -m src --once --mode all --symbols BTCUSDT,ETHUSDT --intervals 5m,1h --workers 4
```

### 3.2 cProfile（回答：时间主要花在 Python 哪些函数？）

```bash
cd services/compute/trading-service
python -m cProfile -o /tmp/trading.pstats -m src --once --mode all --symbols BTCUSDT,ETHUSDT --intervals 5m,1h
python - <<'PY'
import pstats
p = pstats.Stats("/tmp/trading.pstats")
p.sort_stats("cumtime").print_stats(80)
PY
```

期望看到的证据：

- 若 `psycopg.connect` / `cursor.execute` 占比极高：说明期货 N+1/连接风暴是主因。  
- 若 `sqlite3.Connection.execute` / `executemany` / `commit` 占比高：说明写入路径是主因。  
- 若某指标 `compute()` 占比异常：锁定 CPU 热点指标，后续用 line_profiler 细化。

### 3.3 py-spy（回答：CPU 火焰图长在 pandas/numpy 还是 python loop？）

```bash
py-spy record -o /tmp/trading.svg -- python -m src --once --mode all --symbols BTCUSDT,ETHUSDT --intervals 5m,1h
```

期望看到的证据：

- `DataWriter.write`/`sqlite3` 一条粗柱：写入是主瓶颈。  
- `futures_aggregate.get_metrics_history` 一条粗柱：期货 IO 是主瓶颈。  
- `tv_trend_cloud` / `vpvr` 的 Python loop 占比明显：指标实现需要向量化。

### 3.4 line_profiler（回答：某个函数内部到底哪一行最慢？）

适用对象：

- `services/compute/trading-service/src/db/reader.py:DataWriter.write`  
- `services/compute/trading-service/src/indicators/batch/futures_aggregate.py:get_metrics_history`  
- 任何 CPU 热点指标 `compute()`

建议只对 1~3 个函数做 line_profiler，否则噪声过大。

### 3.5 tracemalloc / memory_profiler（回答：峰值内存是谁导致的？）

重点怀疑点：

- `_write_simple_db` 聚合 `all_records` 与 DataFrame 构建（`services/compute/trading-service/src/core/engine.py:261-275`）  
- `DataCache.get_klines` 的 `.copy()`（`services/compute/trading-service/src/db/cache.py:156-165`）  
- `process` 后端 pickle 序列化（`services/compute/trading-service/src/core/engine.py:198-203`）

---

## 【4. 快速收益优化（低风险，最小改动）】

> 每条建议必须包含：原因 → 改法 → 预期收益 → 风险/副作用 → 如何验证；并给出复杂度变化。

### 4.1 消灭 `df.apply(axis=1)`（TvTrendCloud）

- 问题（原因）：`services/compute/trading-service/src/indicators/batch/tv_trend_cloud.py:62` 使用 `df.apply(lambda row..., axis=1)`，这是典型 Pandas 反模式：每行回调一次 Python，常数项巨大。  
- 修改方案（最小改动）：
  - 现有：
    - `avg_body = df.apply(lambda row: abs(row["close"] - row["open"]), axis=1).iloc[-15:].mean()`
  - 建议：
    - `avg_body = (df["close"] - df["open"]).abs().iloc[-15:].mean()`
- 复杂度变化：O(n) → O(n)（不变），但“逐行 Python 回调”→“矢量化”，常数项显著下降。  
- 预期收益：【推断】该指标 compute 5x~50x；全链路收益取决于该指标占比。  
- 风险/副作用：几乎无；唯一风险是列缺失时抛错（原本也会）。  
- 验证方法：
  - 固定一份 df（>=200 行），分别跑旧/新 compute，对比输出字段与数值（强度允许极小浮点误差）。

### 4.2 SQLite 写入：delete/cleanup 循环改 `executemany`

- 问题（原因）：
  - `services/compute/trading-service/src/db/reader.py:283-285`：逐行 delete（Python 循环 + 多次 SQL execute）。  
  - `services/compute/trading-service/src/db/reader.py:314-332`：逐(交易对,周期)清理 delete（同样循环发 SQL）。  
- 修改方案（最小改动方向）：
  - 把 keys 组装为 tuples，改 `conn.executemany(...)`；必要时分块（例如每 500 条一块）。  
- 复杂度变化：O(m) → O(m)（不变），但 Python 循环开销显著下降，SQLite statement 复用更好。  
- 预期收益：【推断】写入阶段 1.3x~3x（视磁盘/锁争用而定）。  
- 风险/副作用：一次 executemany 太大可能占内存；可分块。  
- 验证方法：
  - 对比 `Engine.run` 日志中的 `写入=...s`（`services/compute/trading-service/src/core/engine.py:251`）。  
  - 对比 SQLite 结果：每表按 `(交易对,周期,数据时间)` 去重后行数一致；随机抽样对比字段值。

### 4.3 SQLite 写入：多表写入合并为单事务（减少 commit/fsync）

- 问题（原因）：`Engine._write_simple_db` 对每个指标表调用 `DataWriter.write`，而 `DataWriter.write` 每次 `conn.commit()`（`services/compute/trading-service/src/db/reader.py:296`）。事务数≈指标数 K。  
- 修改方案（最小改动方向）：
  - 给 `DataWriter.write()` 增加 `commit: bool = True`；外层 `Engine._write_simple_db` 包一层 `BEGIN IMMEDIATE` 与最终 `commit()`。  
  - 或实现 `DataWriter.transaction()` 上下文管理器，统一控制事务边界。
- 复杂度变化：事务次数 O(K) → O(1)。  
- 预期收益：【推断】写入阶段 2x~10x（SSD/机械盘差异很大）。  
- 风险/副作用：单事务更大，异常时回滚更多；但对批处理语义更一致。  
- 验证方法：同上；并加一次故障注入（运行中 SIGINT）检查 SQLite 是否出现“部分表更新/部分表旧数据”的不一致（理想情况下整体一致）。

### 4.4 指标对象实例化：从 O(S*I*K) 降到 O(K)

- 问题（原因）：`services/compute/trading-service/src/core/engine.py:_compute_batch` 的内层循环对每个 `(symbol,interval)`、每个指标都 `ind = cls()`（见 `engine.py:81-83`）。  
  - 若某些指标构造函数做了隐式初始化（导入大模块、构建缓存），开销会被放大。  
- 修改方案：
  - 在 batch 内先构造一次实例列表：`instances = [(name, cls()) ...]`，再重复调用 `compute`。  
- 复杂度变化：实例化次数 O(S*I*K) → O(K)（每个 batch 一次；若多 batch 则 O(K*batches)）。  
- 预期收益：【推断】通常是小到中等（取决于指标 init 的重量），但几乎零风险/零侵入。  
- 风险/副作用：要求指标实例是无状态/可重入；若某指标在实例里缓存上次结果，可能改变语义。  
- 验证方法：对同一输入多次运行，输出稳定一致；并对比单指标结果。

---

## 【5. 中等改造（1~2 天，结构调整：砍掉 N+1 IO）】

### 5.1 核心原则：指标 compute() 内禁止做外部 IO

当前坏味道：`FuturesAggregate` / `FuturesGapMonitor` 在 compute 内直接连 PG。  

为什么这是结构性问题：

- 这使得“计算阶段”不再是纯 CPU，而是夹杂 IO，导致：
  - 并发模型失效（线程/进程都被 IO 等待拖慢）；  
  - DB 负载指数增加（连接与查询次数随任务数增长）；  
  - 难以测试（compute 无法离线测试，需要真实 DB）。  

目标形态：

- 所有 DB 查询前移到“读阶段”，按 interval 批量拉取，并以 dict/list 的形式注入指标。

### 5.2 期货 metrics 批量读取与缓存（把 O(S*I) 查询改成 O(I)）

#### 5.2.1 现状（为何慢）

- `FuturesAggregate.compute()`：每个 symbol、每个 interval 都调用一次 `get_metrics_history(symbol, 240, interval)`（`futures_aggregate.py:187-193`）。  
- `get_metrics_history` 内部 `psycopg.connect(...)`（`futures_aggregate.py:156`）。  

当 S=30、I=6 时，单轮计算潜在连接/查询次数约 180 次；一旦把 S 扩到 200，直接上千次连接/查询，DB 与网络会先死。

#### 5.2.2 改造方案（建议数据结构与 cache key）

- 新增 `FuturesMetricsBatchReader`（位置建议：`services/compute/trading-service/src/datasource/futures_metrics.py`）：
  - API（示例）：
    - `load_history(symbols: list[str], interval: str, limit: int) -> dict[str, list[dict]]`
  - 查询方式：
    - 使用窗口函数：`ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY time_col DESC)`，一次 SQL 拿齐所有 symbols 的最近 N 条，再按 symbol 分组。  
  - cache：
    - key：`(interval, tuple(sorted(symbols)), limit)`  
    - ttl：`min(60, interval_seconds)` 或 30s（与你的数据更新节奏匹配）

#### 5.2.3 复杂度与收益

- 查询次数：O(S*I) → O(I)  
- 预期收益：【推断】当你当前慢点在期货指标时，整体收益往往是“数量级”的（3x~20x 常见）。  

#### 5.2.4 风险与验证

- 风险：一次 SQL 返回的数据量更大；但 limit=240 且 symbols 数可控，通常比 N+1 更稳定。  
- 验证：
  - 统计 `psycopg.connect`/`execute` 次数（加计数器或在 `psycopg` 层打 debug log）；应从几百次降到个位数。  
  - 期货指标输出与旧版逐 symbol 查询结果一致（golden test）。

### 5.3 K线缓存增量更新：按 interval 批量拉取（砍掉 per-symbol 查询）

现状：

- `services/compute/trading-service/src/db/cache.py:update_interval()` 在一个连接内对每个 symbol 执行一次 SQL（`cache.py:114-135`），查询次数是 O(S) / interval。  

可落地的折中改法（避免“每 symbol 不同 last_ts”带来的复杂度）：

1) 计算该 interval 下所有 symbols 的 `min_last_ts`（最老的最后时间）。  
2) 一次 SQL 拉取所有 symbols 在 `bucket_ts > min_last_ts` 的数据（可能多取少量行）。  
3) 在 Python 侧按 symbol 分组，再按各自 last_ts 过滤并合并到缓存。

复杂度：

- 查询次数：O(S) → O(1) / interval  
- 数据量：略增（但上限可控，且通常远小于连接/查询开销）

风险：

- 多取的数据增加 CPU/内存；需要限制最大回填窗口（例如最多取最近 2~3 个周期的跨度）。  

验证：

- 统计每轮更新实际 SQL 次数；应与 interval 数接近。  
- 对比更新后的缓存尾部数据时间戳与旧版一致。

---

## 【6. 深度重构（长期：可维护性 + 性能的共同根因）】

### 6.1 结构性根因：阶段边界不清 + IO/计算/写入混杂

当前系统存在三类“职责混杂”：

1) 指标层夹杂 IO（期货指标）。  
2) 写入层夹杂大量“数据维护策略”（去重/保留）并且通过 Python 循环触发大量 SQL。  
3) 引擎层为了兜底引入“占位符写入 + 后清理”的模式（如期货 1m 清理），造成额外 IO 与隐性语义风险。

### 6.2 建议的模块分层（最小但清晰）

- `src/datasource/`：只做 IO（PG/TimescaleDB）与缓存，输出纯数据结构。  
- `src/indicators/`：只做计算（纯/准纯函数），不做外部 IO。  
- `src/storage/`：只做写入（SQLite），并集中实现去重/保留/索引策略。  
- `src/pipeline/`：编排 read → compute → write，负责 metrics 埋点与错误边界。

### 6.3 数据契约（让“关掉 copy”成为可能）

性能与可扩展性的关键：避免无意义 DataFrame copy。

建议明确契约：

- 输入 df 是只读：指标不得原地修改 df（不得新增/覆盖列）。  
- 若某指标需要临时列，必须基于 `df.assign(...)` 或在局部 `np.ndarray` 上计算。  

配套测试：

- 对每个指标，运行前后对比 `df.columns` 与 `df.index` 不变；必要时对关键列做 hash 校验。

### 6.4 性能回归防护（把“快”变成可持续的工程能力）

- 基准脚本（建议放在 `scripts/bench_trading_service.py` 或文档附录，不进产线依赖）：
  - 固定 symbols/intervals/lookback，跑 5 次取中位数，输出：
    - 总耗时、读/算/写耗时、峰值 RSS
    - SQL 次数（PG/SQLite）
- 引入门槛：
  - 如果不想新增依赖，不用 `pytest-benchmark`，直接 `time.perf_counter()` + `resource.getrusage()` 即可。

---

## 【7. 验证清单（快了且没错）】

### 7.1 你需要记录的指标

- 时间：
  - 总耗时
  - 读取耗时 `t_read`
  - 计算耗时 `t_compute`
  - 写入耗时 `t_write`
- 资源：
  - 峰值 RSS（进程常驻内存）
  - SQLite 写入事务数（commit 次数）
  - PG 查询次数（尤其期货相关）

### 7.2 对比方法（输出一致性）

- 选一个固定参数集（symbols/intervals/lookback），分别跑“优化前/优化后”。  
- SQLite 对比：
  - 每个指标表：按 `(交易对, 周期, 数据时间)` 去重后行数相同
  - 抽样 5% 行对比字段值（浮点允许 1e-6 或按业务容忍度）
- 失败策略：
  - 若差异出现在期货指标：先确认批量查询排序/时区/闭合字段是否一致。  

---

## 【8. 附录：额外的“性能坏味道”扫描结果（命中点列表）】

### 8.1 Pandas 反模式命中

- `apply(axis=1)`：`services/compute/trading-service/src/indicators/batch/tv_trend_cloud.py:62`  
- `iterrows()`：`services/compute/trading-service/src/indicators/batch/vpvr.py:72`、`vpvr.py:159`  

### 8.2 IO/N+1 命中

- PG：  
  - `services/compute/trading-service/src/indicators/batch/futures_aggregate.py:get_metrics_history`（每 symbol/interval）  
  - `services/compute/trading-service/src/indicators/batch/futures_gap_monitor.py:get_metrics_times`（每 symbol）  
  - `services/compute/trading-service/src/db/cache.py:update_interval`（每 symbol/interval）  
- SQLite：  
  - `services/compute/trading-service/src/db/reader.py:DataWriter.write`（逐行 delete + 每表 commit）  
  - `services/compute/trading-service/src/db/reader.py:DataWriter._cleanup_old_data`（逐组 delete）  

### 8.3 并行/可扩展性风险点

- 默认 `compute_backend=thread`（`services/compute/trading-service/src/config.py`）：若热点指标是 Python loop，线程无法加速且可能更慢。  
- `process` 后端：pickle 每个 df 可能成为新瓶颈（`engine.py:198-203`）。建议只对“慢指标集合”走 process，其他走 thread（类似 `async_full_engine.py` 的 SLOW_INDICATORS 思路）。  

---

## 【9. 最小可落地路线图（按 ROI 排序）】

1) 立刻修：`tv_trend_cloud` 向量化 + SQLite delete/cleanup executemany + 单事务写入（当天见效）。  
2) 砍最大扩展性炸弹：期货指标 IO 外移并批量拉取（把 N+1 干掉）。  
3) 优化 K线缓存增量更新为批量（减少 DB 往返）。  
4) 确立“输入 df 只读”契约，逐步关闭 `.copy()`（在 S 大时把内存翻倍问题直接解决）。  
