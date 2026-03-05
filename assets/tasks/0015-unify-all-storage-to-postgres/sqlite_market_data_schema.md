# SQLite 真实表结构提取：market_data.db

- 生成时间(UTC): `2026-03-05T04:13:53Z`
- 源文件: `assets/database/services/telegram-service/market_data.db`
- 文件 SHA256(前16): `8d00e469011b5c99`
- 表数量: `38`

## 表清单（按名称排序）

- `ADX.py`
- `ATR波幅扫描器.py`
- `CCI.py`
- `CVD信号排行榜.py`
- `Donchian.py`
- `G，C点扫描器.py`
- `Ichimoku.py`
- `KDJ随机指标扫描器.py`
- `Keltner.py`
- `K线形态扫描器.py`
- `MACD柱状扫描器.py`
- `MFI资金流量扫描器.py`
- `OBV能量潮扫描器.py`
- `SuperTrend.py`
- `VPVR排行生成器.py`
- `VWAP离线信号扫描.py`
- `WilliamsR.py`
- `主动买卖比扫描器.py`
- `全量支撑阻力扫描器.py`
- `剥头皮信号扫描器.py`
- `基础数据同步器.py`
- `多空信号扫描器.py`
- `大资金操盘扫描器.py`
- `布林带扫描器.py`
- `成交量比率扫描器.py`
- `数据监控.py`
- `智能RSI扫描器.py`
- `期货情绪元数据.py`
- `期货情绪缺口监控.py`
- `期货情绪聚合表.py`
- `流动性扫描器.py`
- `谐波信号扫描器.py`
- `超级精准趋势扫描器.py`
- `趋势云反转扫描器.py`
- `趋势线榜单.py`
- `量能信号扫描器.py`
- `量能斐波狙击扫描器.py`
- `零延迟趋势扫描器.py`

## 字段清单（表名 → 字段 → 类型）

### `ADX.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `ADX` | `REAL` | 0 | `` | 0 |
| `正向DI` | `REAL` | 0 | `` | 0 |
| `负向DI` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "ADX.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "ADX" REAL,
  "正向DI" REAL,
  "负向DI" REAL,
  "指标" REAL
)
```
</details>

### `ATR波幅扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `波动分类` | `TEXT` | 0 | `` | 0 |
| `ATR百分比` | `REAL` | 0 | `` | 0 |
| `上轨` | `REAL` | 0 | `` | 0 |
| `中轨` | `REAL` | 0 | `` | 0 |
| `下轨` | `REAL` | 0 | `` | 0 |
| `成交额` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "ATR波幅扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "波动分类" TEXT,
  "ATR百分比" REAL,
  "上轨" REAL,
  "中轨" REAL,
  "下轨" REAL,
  "成交额" REAL,
  "当前价格" REAL,
  "指标" REAL
)
```
</details>

### `CCI.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `CCI` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "CCI.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "CCI" REAL,
  "指标" REAL
)
```
</details>

### `CVD信号排行榜.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `CVD值` | `REAL` | 0 | `` | 0 |
| `变化率` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "CVD信号排行榜.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "CVD值" REAL,
  "变化率" REAL,
  "指标" REAL
)
```
</details>

### `Donchian.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `上轨` | `REAL` | 0 | `` | 0 |
| `中轨` | `REAL` | 0 | `` | 0 |
| `下轨` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "Donchian.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "上轨" REAL,
  "中轨" REAL,
  "下轨" REAL,
  "指标" REAL
)
```
</details>

### `G，C点扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `EMA7` | `REAL` | 0 | `` | 0 |
| `EMA25` | `REAL` | 0 | `` | 0 |
| `EMA99` | `REAL` | 0 | `` | 0 |
| `价格` | `REAL` | 0 | `` | 0 |
| `趋势方向` | `TEXT` | 0 | `` | 0 |
| `带宽评分` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "G，C点扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "EMA7" REAL,
  "EMA25" REAL,
  "EMA99" REAL,
  "价格" REAL,
  "趋势方向" TEXT,
  "带宽评分" REAL,
  "指标" REAL
)
```
</details>

### `Ichimoku.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `转换线` | `REAL` | 0 | `` | 0 |
| `基准线` | `REAL` | 0 | `` | 0 |
| `先行带A` | `REAL` | 0 | `` | 0 |
| `先行带B` | `REAL` | 0 | `` | 0 |
| `迟行带` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `方向` | `TEXT` | 0 | `` | 0 |
| `强度` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "Ichimoku.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "转换线" REAL,
  "基准线" REAL,
  "先行带A" REAL,
  "先行带B" REAL,
  "迟行带" REAL,
  "当前价格" REAL,
  "信号" TEXT,
  "方向" TEXT,
  "强度" REAL,
  "指标" REAL
)
```
</details>

### `KDJ随机指标扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `J值` | `REAL` | 0 | `` | 0 |
| `K值` | `REAL` | 0 | `` | 0 |
| `D值` | `REAL` | 0 | `` | 0 |
| `信号概述` | `TEXT` | 0 | `` | 0 |
| `成交额` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "KDJ随机指标扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "J值" REAL,
  "K值" REAL,
  "D值" REAL,
  "信号概述" TEXT,
  "成交额" REAL,
  "当前价格" REAL,
  "指标" REAL
)
```
</details>

### `Keltner.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `上轨` | `REAL` | 0 | `` | 0 |
| `中轨` | `REAL` | 0 | `` | 0 |
| `下轨` | `REAL` | 0 | `` | 0 |
| `ATR` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "Keltner.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "上轨" REAL,
  "中轨" REAL,
  "下轨" REAL,
  "ATR" REAL,
  "指标" REAL
)
```
</details>

### `K线形态扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `形态类型` | `TEXT` | 0 | `` | 0 |
| `检测数量` | `INTEGER` | 0 | `` | 0 |
| `强度` | `REAL` | 0 | `` | 0 |
| `成交额（USDT）` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "K线形态扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "形态类型" TEXT,
  "检测数量" INTEGER,
  "强度" REAL,
  "成交额（USDT）" REAL,
  "当前价格" REAL
)
```
</details>

### `MACD柱状扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号概述` | `TEXT` | 0 | `` | 0 |
| `MACD` | `REAL` | 0 | `` | 0 |
| `MACD信号线` | `REAL` | 0 | `` | 0 |
| `MACD柱状图` | `REAL` | 0 | `` | 0 |
| `DIF` | `REAL` | 0 | `` | 0 |
| `DEA` | `REAL` | 0 | `` | 0 |
| `成交额` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "MACD柱状扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号概述" TEXT,
  "MACD" REAL,
  "MACD信号线" REAL,
  "MACD柱状图" REAL,
  "DIF" REAL,
  "DEA" REAL,
  "成交额" REAL,
  "当前价格" REAL,
  "指标" REAL
)
```
</details>

### `MFI资金流量扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `MFI值` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "MFI资金流量扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "MFI值" REAL
)
```
</details>

### `OBV能量潮扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `OBV值` | `REAL` | 0 | `` | 0 |
| `OBV变化率` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "OBV能量潮扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "OBV值" REAL,
  "OBV变化率" REAL,
  "指标" REAL
)
```
</details>

### `SuperTrend.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `SuperTrend` | `REAL` | 0 | `` | 0 |
| `方向` | `TEXT` | 0 | `` | 0 |
| `上轨` | `REAL` | 0 | `` | 0 |
| `下轨` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "SuperTrend.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "SuperTrend" REAL,
  "方向" TEXT,
  "上轨" REAL,
  "下轨" REAL,
  "指标" REAL
)
```
</details>

### `VPVR排行生成器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `VPVR价格` | `REAL` | 0 | `` | 0 |
| `成交量分布` | `REAL` | 0 | `` | 0 |
| `价值区下沿` | `REAL` | 0 | `` | 0 |
| `价值区上沿` | `REAL` | 0 | `` | 0 |
| `价值区宽度` | `REAL` | 0 | `` | 0 |
| `价值区宽度百分比` | `REAL` | 0 | `` | 0 |
| `价值区覆盖率` | `REAL` | 0 | `` | 0 |
| `高成交节点` | `TEXT` | 0 | `` | 0 |
| `低成交节点` | `TEXT` | 0 | `` | 0 |
| `价值区位置` | `TEXT` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "VPVR排行生成器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "VPVR价格" REAL,
  "成交量分布" REAL,
  "价值区下沿" REAL,
  "价值区上沿" REAL,
  "价值区宽度" REAL,
  "价值区宽度百分比" REAL,
  "价值区覆盖率" REAL,
  "高成交节点" TEXT,
  "低成交节点" TEXT,
  "价值区位置" TEXT,
  "指标" REAL
)
```
</details>

### `VWAP离线信号扫描.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `VWAP价格` | `REAL` | 0 | `` | 0 |
| `偏离度` | `REAL` | 0 | `` | 0 |
| `偏离百分比` | `REAL` | 0 | `` | 0 |
| `成交量加权` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |
| `成交额（USDT）` | `REAL` | 0 | `` | 0 |
| `VWAP上轨` | `REAL` | 0 | `` | 0 |
| `VWAP下轨` | `REAL` | 0 | `` | 0 |
| `VWAP带宽` | `REAL` | 0 | `` | 0 |
| `VWAP带宽百分比` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "VWAP离线信号扫描.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "VWAP价格" REAL,
  "偏离度" REAL,
  "偏离百分比" REAL,
  "成交量加权" REAL,
  "当前价格" REAL,
  "成交额（USDT）" REAL,
  "VWAP上轨" REAL,
  "VWAP下轨" REAL,
  "VWAP带宽" REAL,
  "VWAP带宽百分比" REAL,
  "指标" REAL
)
```
</details>

### `WilliamsR.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `WilliamsR` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "WilliamsR.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "WilliamsR" REAL
)
```
</details>

### `主动买卖比扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `主动买量` | `REAL` | 0 | `` | 0 |
| `主动卖量` | `REAL` | 0 | `` | 0 |
| `主动买卖比` | `REAL` | 0 | `` | 0 |
| `价格` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "主动买卖比扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "主动买量" REAL,
  "主动卖量" REAL,
  "主动买卖比" REAL,
  "价格" REAL
)
```
</details>

### `全量支撑阻力扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `支撑位` | `REAL` | 0 | `` | 0 |
| `阻力位` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |
| `ATR` | `REAL` | 0 | `` | 0 |
| `距支撑百分比` | `REAL` | 0 | `` | 0 |
| `距阻力百分比` | `REAL` | 0 | `` | 0 |
| `距关键位百分比` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "全量支撑阻力扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "支撑位" REAL,
  "阻力位" REAL,
  "当前价格" REAL,
  "ATR" REAL,
  "距支撑百分比" REAL,
  "距阻力百分比" REAL,
  "距关键位百分比" REAL,
  "指标" REAL
)
```
</details>

### `剥头皮信号扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `剥头皮信号` | `TEXT` | 0 | `` | 0 |
| `RSI` | `REAL` | 0 | `` | 0 |
| `EMA9` | `REAL` | 0 | `` | 0 |
| `EMA21` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "剥头皮信号扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "剥头皮信号" TEXT,
  "RSI" REAL,
  "EMA9" REAL,
  "EMA21" REAL,
  "当前价格" REAL
)
```
</details>

### `基础数据同步器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `开盘价` | `REAL` | 0 | `` | 0 |
| `最高价` | `REAL` | 0 | `` | 0 |
| `最低价` | `REAL` | 0 | `` | 0 |
| `收盘价` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |
| `成交量` | `REAL` | 0 | `` | 0 |
| `成交额` | `REAL` | 0 | `` | 0 |
| `振幅` | `REAL` | 0 | `` | 0 |
| `变化率` | `REAL` | 0 | `` | 0 |
| `交易次数` | `INTEGER` | 0 | `` | 0 |
| `成交笔数` | `INTEGER` | 0 | `` | 0 |
| `主动买入量` | `REAL` | 0 | `` | 0 |
| `主动买量` | `REAL` | 0 | `` | 0 |
| `主动买额` | `REAL` | 0 | `` | 0 |
| `主动卖出量` | `REAL` | 0 | `` | 0 |
| `主动买卖比` | `REAL` | 0 | `` | 0 |
| `主动卖出额` | `REAL` | 0 | `` | 0 |
| `资金流向` | `REAL` | 0 | `` | 0 |
| `平均每笔成交额` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "基础数据同步器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "开盘价" REAL,
  "最高价" REAL,
  "最低价" REAL,
  "收盘价" REAL,
  "当前价格" REAL,
  "成交量" REAL,
  "成交额" REAL,
  "振幅" REAL,
  "变化率" REAL,
  "交易次数" INTEGER,
  "成交笔数" INTEGER,
  "主动买入量" REAL,
  "主动买量" REAL,
  "主动买额" REAL,
  "主动卖出量" REAL,
  "主动买卖比" REAL,
  "主动卖出额" REAL,
  "资金流向" REAL,
  "平均每笔成交额" REAL
)
```
</details>

### `多空信号扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `方向` | `TEXT` | 0 | `` | 0 |
| `强度` | `REAL` | 0 | `` | 0 |
| `颜色` | `TEXT` | 0 | `` | 0 |
| `实体大小` | `REAL` | 0 | `` | 0 |
| `影线长度` | `REAL` | 0 | `` | 0 |
| `HA开盘` | `REAL` | 0 | `` | 0 |
| `HA收盘` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "多空信号扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号" TEXT,
  "方向" TEXT,
  "强度" REAL,
  "颜色" TEXT,
  "实体大小" REAL,
  "影线长度" REAL,
  "HA开盘" REAL,
  "HA收盘" REAL,
  "指标" REAL
)
```
</details>

### `大资金操盘扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `方向` | `TEXT` | 0 | `` | 0 |
| `评分` | `REAL` | 0 | `` | 0 |
| `结构事件` | `TEXT` | 0 | `` | 0 |
| `偏向` | `TEXT` | 0 | `` | 0 |
| `订单块` | `TEXT` | 0 | `` | 0 |
| `订单块上沿` | `REAL` | 0 | `` | 0 |
| `订单块下沿` | `REAL` | 0 | `` | 0 |
| `缺口类型` | `TEXT` | 0 | `` | 0 |
| `价格区域` | `TEXT` | 0 | `` | 0 |
| `摆动高点` | `REAL` | 0 | `` | 0 |
| `摆动低点` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "大资金操盘扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号" TEXT,
  "方向" TEXT,
  "评分" REAL,
  "结构事件" TEXT,
  "偏向" TEXT,
  "订单块" TEXT,
  "订单块上沿" REAL,
  "订单块下沿" REAL,
  "缺口类型" TEXT,
  "价格区域" TEXT,
  "摆动高点" REAL,
  "摆动低点" REAL,
  "指标" REAL
)
```
</details>

### `布林带扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `带宽` | `REAL` | 0 | `` | 0 |
| `中轨斜率` | `REAL` | 0 | `` | 0 |
| `中轨价格` | `REAL` | 0 | `` | 0 |
| `上轨价格` | `REAL` | 0 | `` | 0 |
| `下轨价格` | `REAL` | 0 | `` | 0 |
| `百分比b` | `REAL` | 0 | `` | 0 |
| `价格` | `REAL` | 0 | `` | 0 |
| `成交额` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "布林带扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "带宽" REAL,
  "中轨斜率" REAL,
  "中轨价格" REAL,
  "上轨价格" REAL,
  "下轨价格" REAL,
  "百分比b" REAL,
  "价格" REAL,
  "成交额" REAL
)
```
</details>

### `成交量比率扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `量比` | `REAL` | 0 | `` | 0 |
| `信号概述` | `TEXT` | 0 | `` | 0 |
| `成交额` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "成交量比率扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "量比" REAL,
  "信号概述" TEXT,
  "成交额" REAL,
  "当前价格" REAL
)
```
</details>

### `数据监控.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `已加载根数` | `INTEGER` | 0 | `` | 0 |
| `最新时间` | `TEXT` | 0 | `` | 0 |
| `本周应有根数` | `REAL` | 0 | `` | 0 |
| `缺口` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "数据监控.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "已加载根数" INTEGER,
  "最新时间" TEXT,
  "本周应有根数" REAL,
  "缺口" REAL
)
```
</details>

### `智能RSI扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `方向` | `TEXT` | 0 | `` | 0 |
| `强度` | `REAL` | 0 | `` | 0 |
| `RSI均值` | `REAL` | 0 | `` | 0 |
| `RSI7` | `REAL` | 0 | `` | 0 |
| `RSI14` | `REAL` | 0 | `` | 0 |
| `RSI21` | `REAL` | 0 | `` | 0 |
| `位置` | `TEXT` | 0 | `` | 0 |
| `背离` | `TEXT` | 0 | `` | 0 |
| `超买阈值` | `REAL` | 0 | `` | 0 |
| `超卖阈值` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "智能RSI扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号" TEXT,
  "方向" TEXT,
  "强度" REAL,
  "RSI均值" REAL,
  "RSI7" REAL,
  "RSI14" REAL,
  "RSI21" REAL,
  "位置" TEXT,
  "背离" TEXT,
  "超买阈值" REAL,
  "超卖阈值" REAL,
  "指标" REAL
)
```
</details>

### `期货情绪元数据.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |
| `持仓张数` | `REAL` | 0 | `` | 0 |
| `持仓金额` | `REAL` | 0 | `` | 0 |
| `大户多空比样本` | `REAL` | 0 | `` | 0 |
| `大户多空比总和` | `REAL` | 0 | `` | 0 |
| `全体多空比样本` | `REAL` | 0 | `` | 0 |
| `主动成交多空比总和` | `REAL` | 0 | `` | 0 |
| `大户多空比` | `REAL` | 0 | `` | 0 |
| `全体多空比` | `REAL` | 0 | `` | 0 |
| `主动成交多空比` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "期货情绪元数据.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "指标" REAL,
  "持仓张数" REAL,
  "持仓金额" REAL,
  "大户多空比样本" REAL,
  "大户多空比总和" REAL,
  "全体多空比样本" REAL,
  "主动成交多空比总和" REAL,
  "大户多空比" REAL,
  "全体多空比" REAL,
  "主动成交多空比" REAL
)
```
</details>

### `期货情绪缺口监控.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `已加载根数` | `REAL` | 0 | `` | 0 |
| `最新时间` | `TEXT` | 0 | `` | 0 |
| `缺失根数` | `REAL` | 0 | `` | 0 |
| `首缺口起` | `TEXT` | 0 | `` | 0 |
| `首缺口止` | `TEXT` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "期货情绪缺口监控.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号" TEXT,
  "已加载根数" REAL,
  "最新时间" TEXT,
  "缺失根数" REAL,
  "首缺口起" TEXT,
  "首缺口止" TEXT
)
```
</details>

### `期货情绪聚合表.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `是否闭合` | `REAL` | 0 | `` | 0 |
| `数据新鲜秒` | `REAL` | 0 | `` | 0 |
| `持仓金额` | `REAL` | 0 | `` | 0 |
| `持仓张数` | `REAL` | 0 | `` | 0 |
| `大户多空比` | `REAL` | 0 | `` | 0 |
| `全体多空比` | `REAL` | 0 | `` | 0 |
| `主动成交多空比` | `REAL` | 0 | `` | 0 |
| `大户样本` | `REAL` | 0 | `` | 0 |
| `持仓变动` | `REAL` | 0 | `` | 0 |
| `持仓变动%` | `REAL` | 0 | `` | 0 |
| `大户偏离` | `REAL` | 0 | `` | 0 |
| `全体偏离` | `REAL` | 0 | `` | 0 |
| `主动偏离` | `REAL` | 0 | `` | 0 |
| `情绪差值` | `REAL` | 0 | `` | 0 |
| `情绪差值绝对值` | `REAL` | 0 | `` | 0 |
| `波动率` | `REAL` | 0 | `` | 0 |
| `OI连续根数` | `REAL` | 0 | `` | 0 |
| `主动连续根数` | `REAL` | 0 | `` | 0 |
| `风险分` | `REAL` | 0 | `` | 0 |
| `市场占比` | `REAL` | 0 | `` | 0 |
| `大户波动` | `REAL` | 0 | `` | 0 |
| `全体波动` | `REAL` | 0 | `` | 0 |
| `持仓斜率` | `REAL` | 0 | `` | 0 |
| `持仓Z分数` | `REAL` | 0 | `` | 0 |
| `大户情绪动量` | `REAL` | 0 | `` | 0 |
| `主动情绪动量` | `REAL` | 0 | `` | 0 |
| `情绪翻转信号` | `REAL` | 0 | `` | 0 |
| `主动跳变幅度` | `REAL` | 0 | `` | 0 |
| `稳定度分位` | `REAL` | 0 | `` | 0 |
| `贡献度排名` | `REAL` | 0 | `` | 0 |
| `陈旧标记` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "期货情绪聚合表.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号" TEXT,
  "是否闭合" REAL,
  "数据新鲜秒" REAL,
  "持仓金额" REAL,
  "持仓张数" REAL,
  "大户多空比" REAL,
  "全体多空比" REAL,
  "主动成交多空比" REAL,
  "大户样本" REAL,
  "持仓变动" REAL,
  "持仓变动%" REAL,
  "大户偏离" REAL,
  "全体偏离" REAL,
  "主动偏离" REAL,
  "情绪差值" REAL,
  "情绪差值绝对值" REAL,
  "波动率" REAL,
  "OI连续根数" REAL,
  "主动连续根数" REAL,
  "风险分" REAL,
  "市场占比" REAL,
  "大户波动" REAL,
  "全体波动" REAL,
  "持仓斜率" REAL,
  "持仓Z分数" REAL,
  "大户情绪动量" REAL,
  "主动情绪动量" REAL,
  "情绪翻转信号" REAL,
  "主动跳变幅度" REAL,
  "稳定度分位" REAL,
  "贡献度排名" REAL,
  "陈旧标记" REAL
)
```
</details>

### `流动性扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `流动性得分` | `REAL` | 0 | `` | 0 |
| `流动性等级` | `TEXT` | 0 | `` | 0 |
| `Amihud得分` | `REAL` | 0 | `` | 0 |
| `Kyle得分` | `REAL` | 0 | `` | 0 |
| `波动率得分` | `REAL` | 0 | `` | 0 |
| `成交量得分` | `REAL` | 0 | `` | 0 |
| `Amihud原值` | `REAL` | 0 | `` | 0 |
| `Kyle原值` | `REAL` | 0 | `` | 0 |
| `成交额（USDT）` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "流动性扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "流动性得分" REAL,
  "流动性等级" TEXT,
  "Amihud得分" REAL,
  "Kyle得分" REAL,
  "波动率得分" REAL,
  "成交量得分" REAL,
  "Amihud原值" REAL,
  "Kyle原值" REAL,
  "成交额（USDT）" REAL,
  "当前价格" REAL,
  "指标" REAL
)
```
</details>

### `谐波信号扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `谐波值` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "谐波信号扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "谐波值" REAL
)
```
</details>

### `超级精准趋势扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `趋势方向` | `TEXT` | 0 | `` | 0 |
| `趋势持续根数` | `REAL` | 0 | `` | 0 |
| `趋势强度` | `REAL` | 0 | `` | 0 |
| `趋势带` | `REAL` | 0 | `` | 0 |
| `最近翻转时间` | `TEXT` | 0 | `` | 0 |
| `量能偏向` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "超级精准趋势扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "趋势方向" TEXT,
  "趋势持续根数" REAL,
  "趋势强度" REAL,
  "趋势带" REAL,
  "最近翻转时间" TEXT,
  "量能偏向" REAL,
  "指标" REAL,
  "信号" TEXT
)
```
</details>

### `趋势云反转扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `方向` | `TEXT` | 0 | `` | 0 |
| `强度` | `REAL` | 0 | `` | 0 |
| `形态` | `TEXT` | 0 | `` | 0 |
| `SMMA200` | `REAL` | 0 | `` | 0 |
| `EMA2` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "趋势云反转扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号" TEXT,
  "方向" TEXT,
  "强度" REAL,
  "形态" TEXT,
  "SMMA200" REAL,
  "EMA2" REAL,
  "指标" REAL
)
```
</details>

### `趋势线榜单.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `趋势方向` | `TEXT` | 0 | `` | 0 |
| `距离趋势线%` | `REAL` | 0 | `` | 0 |
| `当前价格` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "趋势线榜单.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "趋势方向" TEXT,
  "距离趋势线%" REAL,
  "当前价格" REAL,
  "指标" REAL
)
```
</details>

### `量能信号扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `方向` | `TEXT` | 0 | `` | 0 |
| `强度` | `REAL` | 0 | `` | 0 |
| `多头比例` | `REAL` | 0 | `` | 0 |
| `空头比例` | `REAL` | 0 | `` | 0 |
| `MA100` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "量能信号扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号" TEXT,
  "方向" TEXT,
  "强度" REAL,
  "多头比例" REAL,
  "空头比例" REAL,
  "MA100" REAL,
  "指标" REAL
)
```
</details>

### `量能斐波狙击扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `方向` | `TEXT` | 0 | `` | 0 |
| `强度` | `REAL` | 0 | `` | 0 |
| `价格区域` | `TEXT` | 0 | `` | 0 |
| `VWMA基准` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "量能斐波狙击扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号" TEXT,
  "方向" TEXT,
  "强度" REAL,
  "价格区域" TEXT,
  "VWMA基准" REAL,
  "指标" REAL
)
```
</details>

### `零延迟趋势扫描器.py`

| 字段 | 类型 | NOT NULL | 默认值 | PK |
|:---|:---|:---:|:---|:---:|
| `交易对` | `TEXT` | 0 | `` | 0 |
| `周期` | `TEXT` | 0 | `` | 0 |
| `数据时间` | `TEXT` | 0 | `` | 0 |
| `信号` | `TEXT` | 0 | `` | 0 |
| `方向` | `TEXT` | 0 | `` | 0 |
| `强度` | `REAL` | 0 | `` | 0 |
| `ZLEMA` | `REAL` | 0 | `` | 0 |
| `波动带宽` | `REAL` | 0 | `` | 0 |
| `上轨` | `REAL` | 0 | `` | 0 |
| `下轨` | `REAL` | 0 | `` | 0 |
| `趋势值` | `REAL` | 0 | `` | 0 |
| `指标` | `REAL` | 0 | `` | 0 |

<details>
<summary>CREATE TABLE</summary>

```sql
CREATE TABLE "零延迟趋势扫描器.py" (
"交易对" TEXT,
  "周期" TEXT,
  "数据时间" TEXT,
  "信号" TEXT,
  "方向" TEXT,
  "强度" REAL,
  "ZLEMA" REAL,
  "波动带宽" REAL,
  "上轨" REAL,
  "下轨" REAL,
  "趋势值" REAL,
  "指标" REAL
)
```
</details>
