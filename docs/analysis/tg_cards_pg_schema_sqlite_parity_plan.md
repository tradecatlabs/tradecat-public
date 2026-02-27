# 方案：PG 指标库结构严格对齐 SQLite（telegram-service）

## 1) 你要的“严格对齐”是什么意思（我按这个实现）

对齐目标数据库：LF PG/Timescale（默认 `postgresql://postgres:postgres@localhost:5433/market_data`）

对齐目标源：`assets/database/services/telegram-service/market_data.db`（SQLite）

严格对齐范围（✅）：

- 表数量：**38 张表**
- 表名：与 SQLite 完全一致（包含中文与 `.py` 后缀）
- 列名：与 SQLite 完全一致（包含 `%`、括号等特殊字符）
- 列类型：按 SQLite 声明做最直接映射
  - `TEXT` → `text`
  - `REAL` → `double precision`
  - `INTEGER` → `integer`
- 允许 NULL：与 SQLite 一致（SQLite 未声明 NOT NULL）

不强制对齐范围（默认不做，✅保持“表结构一致”）（⚠️可选增强）：

- 主键/唯一约束（SQLite 原表没有）
- 索引（SQLite 原表没有）
- 分区/Hypertable（先不做，避免引入迁移复杂度）

## 2) PG 侧新增 schema 与表（树形示意）

```text
market_data (database)
└── tg_cards (schema)   # NEW：严格对齐 SQLite 的指标/卡片表
    ├── "基础数据同步器.py"
    ├── "ATR波幅扫描器.py"
    ├── "CVD信号排行榜.py"
    ├── "G，C点扫描器.py"
    ├── "K线形态扫描器.py"
    ├── "VPVR排行生成器.py"
    ├── "VWAP离线信号扫描.py"
    ├── "布林带扫描器.py"
    ├── "流动性扫描器.py"
    ├── "超级精准趋势扫描器.py"
    ├── "趋势线榜单.py"
    ├── "期货情绪元数据.py"
    ├── "期货情绪聚合表.py"
    ├── "期货情绪缺口监控.py"
    ├── "主动买卖比扫描器.py"
    ├── "成交量比率扫描器.py"
    ├── "MACD柱状扫描器.py"
    ├── "KDJ随机指标扫描器.py"
    ├── "OBV能量潮扫描器.py"
    ├── "MFI资金流量扫描器.py"
    ├── "智能RSI扫描器.py"
    ├── "趋势云反转扫描器.py"
    ├── "大资金操盘扫描器.py"
    ├── "量能斐波狙击扫描器.py"
    ├── "零延迟趋势扫描器.py"
    ├── "量能信号扫描器.py"
    ├── "多空信号扫描器.py"
    ├── "剥头皮信号扫描器.py"
    ├── "谐波信号扫描器.py"
    ├── "SuperTrend.py"
    ├── "ADX.py"
    ├── "CCI.py"
    ├── "WilliamsR.py"
    ├── "Donchian.py"
    ├── "Keltner.py"
    ├── "Ichimoku.py"
    └── "数据监控.py"
```

> 说明：PG 中这些表名必须用双引号引用，例如：`SELECT * FROM tg_cards."ATR波幅扫描器.py";`

## 3) DDL 落盘位置（你检查用）

我已把“严格对齐”的 PG DDL 固化成一个 schema 文件（不改业务逻辑，只是新增 DDL）：

- `assets/database/db/schema/021_tg_cards_sqlite_parity.sql`

并已把它纳入 LF stack：

- `assets/database/db/stacks/lf.sql`

## 4) 写入语义（严格对齐模式下的“最小改动”写法）

因为 SQLite 原表没有主键/唯一约束，严格对齐后 PG 侧同样没有。

因此 **幂等与“替换语义”必须由应用层实现**，不能指望 `ON CONFLICT`。

当前仓库已落地的写入语义（✅已实现，见 `services/compute/trading-service/src/db/reader.py` 的 `PgDataWriter`）：

1) **列对齐**

- 以 PG 表结构为准：缺列补 `NULL`，多列丢弃，避免“列漂移导致重建表/写入失败”。

2) **幂等写入（避免重复行）**

- 对于含 `("交易对","周期","数据时间")` 三列的表：
  - 先执行 `DELETE`（同一 `(交易对, 周期, 数据时间)` 作为幂等键）
  - 再批量 `INSERT` 新行
- 对于不含上述三列的表：仅执行 `INSERT`（严格对齐优先，避免误删）。

3) **保留窗口（避免历史无限膨胀）**

- 按 `(交易对, 周期)` 保留每周期最新 `N` 条：
  - `1m=120, 5m=120, 15m=96, 1h=144, 4h=120, 1d=180, 1w=104`
- 删除实现：`row_number() over (partition by 交易对 order by 数据时间 desc)` + `ctid` 精确删除超限行。

为什么当前实现 **不使用 `TRUNCATE`**（刻意不选）：

- `TRUNCATE` 会清空整张表（包含其他周期/其他币种/历史窗口），破坏“增量产出 + 保留窗口”的语义。
- `TRUNCATE` 更强锁粒度，读端/写端并发时更容易阻塞与抖动。

> 结论：**“delete-by-key + insert + retention”** 是在“严格对齐 + 允许历史窗口 + 并发读写”三者同时成立下的最稳方案。

## 5) 可选增强（不破坏“结构对齐”）

若你后续觉得 PG 查询慢/导出慢，我建议加“可选索引脚本”（另存一个 optional SQL，不改变表结构，只加 index）：

- 统一建议索引：`("交易对", "周期", "数据时间")`
- 对排行榜常用：`("周期", "成交额")` 或 `("周期", "指标")`（视你的排序字段而定）

我暂时不自动加索引，避免你说我“乱改结构”。你确认后再加。

## 6) 自检命令（你用来验收“严格对齐”）

### 6.1 SQLite 源表清单（只读）

```bash
sqlite3 'file:assets/database/services/telegram-service/market_data.db?mode=ro' \".tables\"
```

### 6.2 PG 目标表清单

```bash
PGPASSWORD=postgres psql 'postgresql://postgres:postgres@localhost:5433/market_data' \\
  -c \"\\dt tg_cards.*\"
```

### 6.3 对齐抽查：列名一致

```bash
PGPASSWORD=postgres psql 'postgresql://postgres:postgres@localhost:5433/market_data' \\
  -c \"\\d tg_cards.\\\"ATR波幅扫描器.py\\\"\"
```
