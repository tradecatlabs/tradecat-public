# Binance Vision 字段字典（基于本仓库样本）

> 适用范围：本仓库样本目录  
> `artifacts/analysis/binance_vision_compass/BTCUSDT_20260211_010327/data/`  
>
> 目标：把 **目录层级 → 数据集类型 → CSV 字段** 固化为可执行的解析契约与数据库设计依据。

---

## 0. 重要约定（解析与落库必须统一）

### 0.1 时间戳单位

- **futures/um**：样本内 epoch 时间戳为 **毫秒（ms, 13 位）**
- **spot**：样本内 epoch 时间戳为 **微秒（us, 16 位）**
- 部分数据集（`metrics`、`bookDepth`）时间列为 **datetime 字符串**
- `EOHSummary` 的时间语义为 **date + hour（小时粒度）**

### 0.2 Header（首行字段名）

- **futures/um**：样本内 CSV **有 header**
- **spot**：样本内 CSV **无 header**（必须按固定列序解析，禁止猜测）

### 0.3 空值与数值格式

- 空字符串 `""`：按 NULL 处理（常见于 option `best_buy_iv` 等）
- 科学计数法（如 `0E-8`）：按 NUMERIC/Decimal 解析

### 0.4 文件追溯（强建议）

建议为每个导入文件建立 `storage.files`（或等价）索引表，并在事实表中保留 `file_id` 外键：
- 任何一行都能回溯到来源 `rel_path`（严格对齐官方目录结构与文件命名）
- 支持 `.CHECKSUM` 对账与“同一路径文件被替换”的版本链审计

---

## 1. Futures / UM / daily

目录前缀：`futures/um/daily/`

### 1.1 aggTrades（聚合成交）

路径模式：
- `futures/um/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-YYYY-MM-DD.csv`

行粒度：
- 1 行 = 1 条聚合成交（覆盖一段 trade id 区间）

字段字典：

```text
+----------------+----------------------+-----------+-------------------------------------------------------------+------------------------------+
| 字段           | 类型(建议)           | 单位      | 含义                                                        | 备注                         |
+----------------+----------------------+-----------+-------------------------------------------------------------+------------------------------+
| agg_trade_id   | BIGINT               | -         | 聚合成交 ID                                                 | 建议幂等键的一部分           |
| price          | NUMERIC(38, 12)      | quote     | 成交价格                                                    | BTCUSDT 的 quote=USDT        |
| quantity       | NUMERIC(38, 12)      | base      | 成交数量                                                    | base=BTC                     |
| first_trade_id | BIGINT               | -         | 该聚合成交覆盖的第一条 trade id                              |                              |
| last_trade_id  | BIGINT               | -         | 该聚合成交覆盖的最后一条 trade id                              |                              |
| transact_time  | BIGINT + timestamptz | ms / UTC  | 交易时间戳                                                  | 建议同时落 transact_time_ts  |
| is_buyer_maker | BOOLEAN              | -         | 买方是否为 maker                                            |                              |
+----------------+----------------------+-----------+-------------------------------------------------------------+------------------------------+
```

幂等键建议：
- `UNIQUE(symbol, agg_trade_id)`

---

### 1.2 trades（逐笔成交）

路径模式：
- `futures/um/daily/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM-DD.csv`

行粒度：
- 1 行 = 1 条 trade

字段字典：

```text
+----------------+----------------------+-----------+----------------------------------------------+---------------------------+
| 字段           | 类型(建议)           | 单位      | 含义                                         | 备注                      |
+----------------+----------------------+-----------+----------------------------------------------+---------------------------+
| id             | BIGINT               | -         | trade id                                     | 建议幂等键                |
| price          | NUMERIC(38, 12)      | quote     | 成交价格                                     |                           |
| qty            | NUMERIC(38, 12)      | base      | 成交数量                                     |                           |
| quote_qty      | NUMERIC(38, 12)      | quote     | 成交额                                       | ≈ price * qty             |
| time           | BIGINT + timestamptz | ms / UTC  | 成交时间戳                                   | 建议同时落 time_ts        |
| is_buyer_maker | BOOLEAN              | -         | 买方是否为 maker                             |                           |
+----------------+----------------------+-----------+----------------------------------------------+---------------------------+
```

幂等键建议：
- `UNIQUE(symbol, id)`

---

### 1.3 klines / markPriceKlines / indexPriceKlines / premiumIndexKlines（1m）

路径模式（示例以 klines 为例）：
- `futures/um/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv`
- `futures/um/daily/markPriceKlines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv`
- `futures/um/daily/indexPriceKlines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv`
- `futures/um/daily/premiumIndexKlines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv`

行粒度：
- 1 行 = 1 根 1m K 线（分钟对齐；样本中 1440 行/天）

字段字典（四者字段一致，仅“价格语义”不同）：

```text
+-----------------------+----------------------+-----------+----------------------------------------------------+-------------------------------+
| 字段                  | 类型(建议)           | 单位      | 含义                                               | 备注                          |
+-----------------------+----------------------+-----------+----------------------------------------------------+-------------------------------+
| open_time             | BIGINT + timestamptz | ms / UTC  | 开盘时间戳                                         | minute 对齐                   |
| open                  | NUMERIC(38, 12)      | quote     | 开盘价                                             |                               |
| high                  | NUMERIC(38, 12)      | quote     | 最高价                                             |                               |
| low                   | NUMERIC(38, 12)      | quote     | 最低价                                             |                               |
| close                 | NUMERIC(38, 12)      | quote     | 收盘价                                             |                               |
| volume                | NUMERIC(38, 12)      | base      | 成交量（基础币）                                   |                               |
| close_time            | BIGINT + timestamptz | ms / UTC  | 收盘时间戳                                         | 通常 = open_time + 59999      |
| quote_volume          | NUMERIC(38, 12)      | quote     | 成交额（报价币）                                   |                               |
| count                 | BIGINT               | -         | 成交笔数                                           |                               |
| taker_buy_volume      | NUMERIC(38, 12)      | base      | 主动买入成交量（基础币）                           |                               |
| taker_buy_quote_volume| NUMERIC(38, 12)      | quote     | 主动买入成交额（报价币）                           |                               |
| ignore                | BIGINT               | -         | 占位字段                                           | 通常为 0，可忽略              |
+-----------------------+----------------------+-----------+----------------------------------------------------+-------------------------------+
```

幂等键建议：
- `UNIQUE(symbol, open_time)`

---

### 1.4 bookTicker（最优买卖一）

路径模式：
- `futures/um/daily/bookTicker/{SYMBOL}/{SYMBOL}-bookTicker-YYYY-MM-DD.csv`

行粒度：
- 1 行 = 一次 top-of-book 更新

字段字典：

```text
+-------------------+----------------------+-----------+-----------------------------------------+----------------------------------+
| 字段              | 类型(建议)           | 单位      | 含义                                    | 备注                             |
+-------------------+----------------------+-----------+-----------------------------------------+----------------------------------+
| update_id         | BIGINT               | -         | 更新序号                                | 建议幂等键                       |
| best_bid_price    | NUMERIC(38, 12)      | quote     | 买一价                                  |                                  |
| best_bid_qty      | NUMERIC(38, 12)      | base      | 买一量                                  |                                  |
| best_ask_price    | NUMERIC(38, 12)      | quote     | 卖一价                                  |                                  |
| best_ask_qty      | NUMERIC(38, 12)      | base      | 卖一量                                  |                                  |
| transaction_time  | BIGINT + timestamptz | ms / UTC  | 交易时间戳                              |                                  |
| event_time        | BIGINT + timestamptz | ms / UTC  | 事件时间戳                              | 建议以 event_time_ts 做时序主键  |
+-------------------+----------------------+-----------+-----------------------------------------+----------------------------------+
```

幂等键建议：
- `UNIQUE(symbol, update_id)`

风险提示：
- 历史数据存在“文件内乱序”风险，导入建议做乱序检测，并在质量层记录（例如倒序段数/最大倒序跨度）。

---

### 1.5 bookDepth（深度曲线）

路径模式：
- `futures/um/daily/bookDepth/{SYMBOL}/{SYMBOL}-bookDepth-YYYY-MM-DD.csv`

行粒度：
- 1 行 = (timestamp, percentage) 的深度/名义额点

字段字典：

```text
+------------+-----------------+-----------+--------------------------------------+----------------------------------------------+
| 字段       | 类型(建议)      | 单位      | 含义                                 | 备注                                         |
+------------+-----------------+-----------+--------------------------------------+----------------------------------------------+
| timestamp  | TIMESTAMPTZ     | UTC       | 快照时间                             | CSV 为字符串 "YYYY-MM-DD HH:MM:SS"           |
| percentage | NUMERIC(12, 4)  | %         | 相对档位百分比                       | 常见为负(bid侧)/正(ask侧)，需以官方口径确认  |
| depth      | NUMERIC(38, 12) | base?     | 深度数量                             | 具体含义依赖 percentage 档位定义             |
| notional   | NUMERIC(38, 12) | quote     | 名义金额                             |                                              |
+------------+-----------------+-----------+--------------------------------------+----------------------------------------------+
```

幂等键建议：
- `UNIQUE(symbol, timestamp, percentage)`

---

### 1.6 metrics（期货指标 5m）

路径模式：
- `futures/um/daily/metrics/{SYMBOL}/{SYMBOL}-metrics-YYYY-MM-DD.csv`

行粒度：
- 1 行 = 5 分钟对齐的一组指标点

字段字典：

```text
+--------------------------------+-----------------+-----------+----------------------------------------------+---------------------------------------------+
| 字段                           | 类型(建议)      | 单位      | 含义                                         | 备注                                        |
+--------------------------------+-----------------+-----------+----------------------------------------------+---------------------------------------------+
| create_time                    | TIMESTAMPTZ     | UTC       | 指标时间（5m 对齐）                          | CSV 为字符串 "YYYY-MM-DD HH:MM:SS"          |
| symbol                         | TEXT            | -         | 交易对                                       | 与路径内 SYMBOL 一致                         |
| sum_open_interest              | NUMERIC         | contracts | 总持仓量                                     | 口径以 Binance 指标定义为准                  |
| sum_open_interest_value        | NUMERIC         | quote     | 总持仓价值                                   |                                             |
| count_toptrader_long_short_ratio| NUMERIC        | ratio     | Top Trader 多空比（账户数口径）              |                                             |
| sum_toptrader_long_short_ratio | NUMERIC         | ratio     | Top Trader 多空比（持仓量口径）              |                                             |
| count_long_short_ratio         | NUMERIC         | ratio     | 全市场多空比（账户数口径）                   |                                             |
| sum_taker_long_short_vol_ratio | NUMERIC         | ratio     | 主动买卖量比                                 |                                             |
+--------------------------------+-----------------+-----------+----------------------------------------------+---------------------------------------------+
```

幂等键建议：
- `UNIQUE(symbol, create_time)`

边界提示：
- 单日文件可能包含次日 `00:00:00` 的数据行，不要用“文件名日期”强切过滤。

---

## 2. Spot / daily

目录前缀：`spot/daily/`

> 注意：spot 样本内 CSV 无 header，且 epoch 时间戳为 us（16 位）。

### 2.1 trades（逐笔成交）

路径模式：
- `spot/daily/trades/{SYMBOL}/{SYMBOL}-trades-YYYY-MM-DD.csv`

列序字典（无 header）：

```text
+------+----------------------+----------------------+-----------+----------------------------------------------+-----------------------------+
| 列序 | 字段名(建议)          | 类型(建议)           | 单位      | 含义                                         | 备注                        |
+------+----------------------+----------------------+-----------+----------------------------------------------+-----------------------------+
| 0    | id                   | BIGINT               | -         | trade id                                     | 建议幂等键                  |
| 1    | price                | NUMERIC(38, 12)      | quote     | 成交价格                                     |                             |
| 2    | qty                  | NUMERIC(38, 12)      | base      | 成交数量                                     |                             |
| 3    | quote_qty            | NUMERIC(38, 12)      | quote     | 成交额                                       | ≈ price * qty               |
| 4    | time                 | BIGINT + timestamptz | us / UTC  | 成交时间戳                                   | 建议同时落 time_ts          |
| 5    | is_buyer_maker       | BOOLEAN              | -         | 买方是否为 maker                             |                             |
| 6    | is_best_match        | BOOLEAN              | -         | 是否最佳匹配（isBestMatch）                  |                             |
+------+----------------------+----------------------+-----------+----------------------------------------------+-----------------------------+
```

幂等键建议：
- `UNIQUE(symbol, id)`

---

### 2.2 aggTrades（聚合成交）

路径模式：
- `spot/daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-YYYY-MM-DD.csv`

列序字典（无 header）：

```text
+------+----------------------+----------------------+-----------+----------------------------------------------+-----------------------------+
| 列序 | 字段名(建议)          | 类型(建议)           | 单位      | 含义                                         | 备注                        |
+------+----------------------+----------------------+-----------+----------------------------------------------+-----------------------------+
| 0    | agg_trade_id         | BIGINT               | -         | 聚合成交 ID                                  | 建议幂等键                  |
| 1    | price                | NUMERIC(38, 12)      | quote     | 成交价格                                     |                             |
| 2    | quantity             | NUMERIC(38, 12)      | base      | 成交数量                                     |                             |
| 3    | first_trade_id       | BIGINT               | -         | 覆盖的第一条 trade id                        |                             |
| 4    | last_trade_id        | BIGINT               | -         | 覆盖的最后一条 trade id                      |                             |
| 5    | transact_time        | BIGINT + timestamptz | us / UTC  | 交易时间戳                                   | 建议同时落 transact_time_ts |
| 6    | is_buyer_maker       | BOOLEAN              | -         | 买方是否为 maker                             |                             |
| 7    | is_best_match        | BOOLEAN              | -         | 是否最佳匹配                                 |                             |
+------+----------------------+----------------------+-----------+----------------------------------------------+-----------------------------+
```

幂等键建议：
- `UNIQUE(symbol, agg_trade_id)`

---

### 2.3 klines（1m）

路径模式：
- `spot/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-YYYY-MM-DD.csv`

列序字典（无 header；字段语义与 futures klines 一致，时间戳为 us）：

```text
+------+-----------------------+----------------------+-----------+----------------------------------------------------+--------------------------+
| 列序 | 字段名(建议)           | 类型(建议)           | 单位      | 含义                                               | 备注                     |
+------+-----------------------+----------------------+-----------+----------------------------------------------------+--------------------------+
| 0    | open_time             | BIGINT + timestamptz | us / UTC  | 开盘时间戳                                         | minute 对齐（us）        |
| 1    | open                  | NUMERIC(38, 12)      | quote     | 开盘价                                             |                          |
| 2    | high                  | NUMERIC(38, 12)      | quote     | 最高价                                             |                          |
| 3    | low                   | NUMERIC(38, 12)      | quote     | 最低价                                             |                          |
| 4    | close                 | NUMERIC(38, 12)      | quote     | 收盘价                                             |                          |
| 5    | volume                | NUMERIC(38, 12)      | base      | 成交量（基础币）                                   |                          |
| 6    | close_time            | BIGINT + timestamptz | us / UTC  | 收盘时间戳                                         | 通常 = open_time + 59999999 |
| 7    | quote_volume          | NUMERIC(38, 12)      | quote     | 成交额（报价币）                                   |                          |
| 8    | count                 | BIGINT               | -         | 成交笔数                                           |                          |
| 9    | taker_buy_volume      | NUMERIC(38, 12)      | base      | 主动买入成交量（基础币）                           |                          |
| 10   | taker_buy_quote_volume| NUMERIC(38, 12)      | quote     | 主动买入成交额（报价币）                           |                          |
| 11   | ignore                | BIGINT               | -         | 占位字段                                           | 通常为 0                 |
+------+-----------------------+----------------------+-----------+----------------------------------------------------+--------------------------+
```

幂等键建议：
- `UNIQUE(symbol, open_time)`

---

## 3. Option / daily

目录前缀：`option/daily/`

### 3.1 BVOLIndex

路径模式：
- `option/daily/BVOLIndex/{SYMBOL}/{SYMBOL}-BVOLIndex-YYYY-MM-DD.csv`

行粒度：
- 1 行 = 一个 BVOL 指数计算点

字段字典：

```text
+------------+----------------------+-----------+----------------------------------+------------------------------+
| 字段       | 类型(建议)           | 单位      | 含义                             | 备注                         |
+------------+----------------------+-----------+----------------------------------+------------------------------+
| calc_time  | BIGINT + timestamptz | ms / UTC  | 计算时间戳                       | 建议同时落 calc_time_ts       |
| symbol     | TEXT                 | -         | 指数代码（如 BTCBVOLUSDT）       |                              |
| base_asset | TEXT                 | -         | 基础资产代码（如 BTCBVOL）       |                              |
| quote_asset| TEXT                 | -         | 报价资产代码（如 USDT）          |                              |
| index_value| NUMERIC              | -         | 指数值                           |                              |
+------------+----------------------+-----------+----------------------------------+------------------------------+
```

幂等键建议：
- `UNIQUE(symbol, calc_time)`

---

### 3.2 EOHSummary（End-of-Hour Summary）

路径模式：
- `option/daily/EOHSummary/{UNDERLYING}/{UNDERLYING}-EOHSummary-YYYY-MM-DD.csv`

行粒度：
- 1 行 = 某个期权合约（`symbol`）在某个小时（`date` + `hour`）的一组汇总快照

字段字典（有 header；此处逐字段解释，按样本 header 顺序）：

```text
+------------------------+-----------------+-----------+-------------------------------------------------------------+--------------------------------------+
| 字段                   | 类型(建议)      | 单位      | 含义                                                        | 备注                                 |
+------------------------+-----------------+-----------+-------------------------------------------------------------+--------------------------------------+
| date                   | DATE            | UTC date  | 日期                                                        | 与 hour 组合成 hour_ts               |
| hour                   | SMALLINT        | hour      | 小时（00~23）                                                | hour_ts = date + hour                |
| symbol                 | TEXT            | -         | 期权合约代码（如 BTC-231027-33000-C）                        | 合约维度主键的一部分                 |
| underlying             | TEXT            | -         | 标的（如 BTCUSDT）                                           | 目录层级也会体现 underlying          |
| type                   | TEXT            | -         | 期权类型：C=Call，P=Put                                      |                                      |
| strike                 | TEXT/NUMERIC    | -         | 行权价/行权信息                                               | 样本形如 "231027-33000"，建议后续拆分 |
| open                   | NUMERIC         | price     | 该小时开盘价                                                  |                                      |
| high                   | NUMERIC         | price     | 该小时最高价                                                  |                                      |
| low                    | NUMERIC         | price     | 该小时最低价                                                  |                                      |
| close                  | NUMERIC         | price     | 该小时收盘价                                                  |                                      |
| volume_contracts       | NUMERIC         | contracts | 成交量（合约口径）                                            |                                      |
| volume_usdt            | NUMERIC         | quote     | 成交额（USDT）                                               |                                      |
| best_bid_price         | NUMERIC         | price     | 买一价                                                       |                                      |
| best_ask_price         | NUMERIC         | price     | 卖一价                                                       |                                      |
| best_bid_qty           | NUMERIC         | contracts | 买一量                                                       |                                      |
| best_ask_qty           | NUMERIC         | contracts | 卖一量                                                       |                                      |
| best_buy_iv            | NUMERIC         | iv        | 买方最优 IV                                                   | 可能为空字符串 "" → NULL             |
| best_sell_iv           | NUMERIC         | iv        | 卖方最优 IV                                                   |                                      |
| mark_price             | NUMERIC         | price     | 标记价格                                                      |                                      |
| mark_iv                | NUMERIC         | iv        | 标记 IV                                                       |                                      |
| delta                  | NUMERIC         | greek     | Delta                                                        |                                      |
| gamma                  | NUMERIC         | greek     | Gamma                                                        |                                      |
| vega                   | NUMERIC         | greek     | Vega                                                         |                                      |
| theta                  | NUMERIC         | greek     | Theta                                                        |                                      |
| openinterest_contracts | NUMERIC         | contracts | 持仓量（合约口径）                                            | 可能出现 0E-8（科学计数法）          |
| openinterest_usdt      | NUMERIC         | quote     | 持仓价值（USDT）                                             | 同上                                 |
+------------------------+-----------------+-----------+-------------------------------------------------------------+--------------------------------------+
```

幂等键建议：
- `UNIQUE(underlying, symbol, date, hour)`

---

## 4. 对应到“目录结构严格对齐”的数据库落库建议（摘要）

如果你要“表结构对齐目录层级与文件命名”，建议采用：

1) `storage.files`：**严格镜像** `data/<market>/<product?>/<frequency>/<dataset>/<symbol>/<interval?>/<filename>`
2) 事实表按目录前缀建 schema：
   - `futures_um.*`、`futures_cm.*`、`spot.*`、`option.*`
3) 每张事实表都包含：
   - `file_id` 外键（逐行回溯到 `rel_path`）
   - `symbol`（或 `underlying+symbol`）
   - 原始 epoch 字段（BIGINT）+ 归一化 ts 字段（TIMESTAMPTZ）
4) daily/monthly 不进表名：属于 `storage.files.frequency`，通过 join 可精确恢复目录层级视角。

---

## 5. 包含/组成关系（逻辑目录结构图）

> 本节描述“数据之间的包含/组成/聚合关系”，用于帮助你在建模时区分：
> - **原子事实**（最小粒度）：例如逐笔成交 trades
> - **聚合事实**（由原子事实组成）：例如 aggTrades、1m K 线
> - **并列事实流**（不互相包含，但可对齐关联）：例如盘口 bookTicker/bookDepth 与成交聚合链路

```text
binance_vision/（逻辑数据域）
├── futures_um/（USDT-M 永续）
│   ├── trades/（逐笔：最小成交事实）
│   │   ├── trades（逐笔成交）
│   │   └── aggTrades（逐笔聚合成交）
│   │       └── 说明：aggTrades 由 trades 按时间/方向等规则聚合得到，属于 trades 的“聚合视图”
│   ├── klines/（时间桶聚合：由成交数据聚合而来）
│   │   └── klines_1m（成交K线）
│   │       └── 说明：1m K 线是对 trades/aggTrades 在 1 分钟桶内的 OHLCV 聚合，属于 trades 的“分钟聚合”
│   ├── orderbook/（盘口视角：独立于成交聚合链路）
│   │   ├── bookTicker（买一卖一更新，Top-of-book）
│   │   └── bookDepth_curve（深度曲线：timestamp + percentage 档位的 depth/notional）
│   │       └── 说明：bookTicker 与 bookDepth_curve 是盘口数据，二者互不包含；也不“由 trades 组成”
│   ├── reference_price_klines/（参考价格系：不由成交聚合生成）
│   │   ├── markPriceKlines_1m（标记价K线）
│   │   ├── indexPriceKlines_1m（指数价K线）
│   │   └── premiumIndexKlines_1m（溢价指数K线）
│   │       └── 说明：它们与 klines_1m 同时间桶对齐，但“价格口径不同”，不属于 trades 聚合链
│   └── metrics/（指标聚合：期货特有）
│       └── metrics_5m（5m 指标点：OI、多空比、主动买卖比等）
│           └── 说明：metrics 是另一条“指标事实流”，与 klines 可按时间桶关联，但不是由 trades 直接组成
│
├── spot/（现货）
│   ├── trades/
│   │   ├── trades（逐笔成交）
│   │   └── aggTrades（逐笔聚合成交）→ 由 trades 聚合，属于 trades
│   └── klines/
│       └── klines_1m（成交K线）→ 由 trades/aggTrades 聚合，属于 trades
│
└── option/（期权）
    ├── volatility_index/
    │   └── BVOLIndex（波动率指数时间序列：calc_time → index_value）
    └── contract_hourly_summary/
        └── EOHSummary（按 date+hour 的合约汇总：每合约每小时一行）
            └── 说明：EOHSummary 是“期权合约×小时”的汇总快照，不属于 spot/futures 的 trades 聚合链
```
