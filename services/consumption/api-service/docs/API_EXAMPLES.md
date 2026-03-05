# API 调用示例（以 Query Service v1 为主）

> Base URL: `http://localhost:8088`

---

## 0) 鉴权（可选）

Query Service v1 端点支持通过 `X-Internal-Token` 做内网鉴权：

- 默认（推荐）：`QUERY_SERVICE_AUTH_MODE=required`（默认值）  
  - 必须设置服务端 `QUERY_SERVICE_TOKEN`，客户端也必须携带 `X-Internal-Token`，否则返回 `unauthorized`。
- 本地调试（可选）：`QUERY_SERVICE_AUTH_MODE=disabled`  
  - 显式关闭鉴权（不校验 token），仅建议在本机开发环境使用。

```bash
export BASE_URL="http://localhost:8088"
export TOKEN="replace_me_if_enabled"
```

带 token 调用示例：

```bash
curl -s "$BASE_URL/api/v1/capabilities" -H "X-Internal-Token: $TOKEN" | head
```

---

## 1) 健康检查

### 1.1 服务存活（不含数据源探测）

```bash
curl -s "$BASE_URL/api/health" | head
```

### 1.2 Query Service v1 健康（含 sources 探测）

```bash
curl -s "$BASE_URL/api/v1/health" -H "X-Internal-Token: $TOKEN" | head
```

---

## 2) capabilities（卡片/周期/数据源）

```bash
curl -s "$BASE_URL/api/v1/capabilities" -H "X-Internal-Token: $TOKEN" | head
```

响应结构（节选）：

```json
{
  "code": "0",
  "msg": "success",
  "data": {
    "version": "x.y.z",
    "cards": [{"card_id": "atr_ranking", "title": "📊 ATR数据", "intervals": ["5m","15m","1h"]}],
    "intervals": ["5m","15m","1h","4h","1d","1w"],
    "sources": [{"id": "indicators", "ok": true, "dsn": "postgresql://user@host:5433/market_data"}]
  },
  "success": true
}
```

---

## 3) 卡片数据（单卡片）

```bash
curl -s "$BASE_URL/api/v1/cards/atr_ranking?interval=15m&limit=5" -H "X-Internal-Token: $TOKEN" | head
```

响应结构（节选）：

```json
{
  "code": "0",
  "msg": "success",
  "data": {
    "card_id": "atr_ranking",
    "title": "📊 ATR数据",
    "interval": "15m",
    "rows": [
      {
        "symbol": "BTCUSDT",
        "base_symbol": "BTC",
        "rank": 1,
        "fields": {
          "price": 67118.3,
          "quote_volume": 47350000.0,
          "updated_at": "2026-02-19T01:15:00Z"
        }
      }
    ]
  },
  "success": true
}
```

说明：

- `rows[].fields.*` 中的数值字段会被标准化为 JSON number（float/int），避免 Decimal 直接外泄导致编码差异。

---

## 4) 看板聚合（多卡片 × 多周期）

### 4.1 wide（推荐：按 symbol → interval）

```bash
curl -s "$BASE_URL/api/v1/dashboard?cards=atr_ranking&intervals=5m,15m,1h&shape=wide&limit=50" -H "X-Internal-Token: $TOKEN" | head
```

返回结构说明（外层 `data` 为统一响应；内层 `data.data` 为 dashboard payload）：

```json
{
  "code": "0",
  "msg": "success",
  "success": true,
  "data": {
    "cards": ["atr_ranking"],
    "intervals": ["5m","15m","1h"],
    "shape": "wide",
    "data": {
      "atr_ranking": {
        "rows": {
          "BTCUSDT": {
            "15m": {"symbol": "BTCUSDT", "rank": 1, "fields": {"price": 67118.3}}
          }
        }
      }
    }
  }
}
```

---

## 5) 单币种快照（币种查询：结构化表格数据源）

```bash
curl -s "$BASE_URL/api/v1/symbol/BTC/snapshot?panels=basic,futures,advanced&intervals=5m,15m,1h,4h,1d,1w" \
  -H "X-Internal-Token: $TOKEN" | head
```

---

## 6) K线历史（v1 推荐）

```bash
curl -s "$BASE_URL/api/v1/ohlc/history?symbol=BTC&exchange=Binance&interval=2h&limit=5" -H "X-Internal-Token: $TOKEN" | head
```

响应（节选）：

```json
{
  "code": "0",
  "msg": "success",
  "success": true,
  "data": [
    {"time": 1768501320000, "open": "96059.1", "high": "96066.8", "low": "96006.0", "close": "96013.0", "volume": "122.24", "volume_usd": "0"}
  ]
}
```

> 注意：OHLC 为 CoinGlass 兼容格式，数值字段为字符串（保精度）。

---

## 7) 期货兼容端点（/api/futures/*，仅兼容，不建议新消费方依赖）

```bash
curl -s "$BASE_URL/api/futures/open-interest/history?symbol=BTC&interval=1h&limit=5" | head
curl -s "$BASE_URL/api/futures/funding-rate/history?symbol=BTC&interval=1h&limit=5" | head
curl -s "$BASE_URL/api/futures/metrics?symbol=BTC&interval=1h&limit=5" | head
```

---

## 8) 调试端点（默认必须鉴权）

### 8.1 指标表列表（旧端点：token-only）

```bash
curl -s "$BASE_URL/api/indicator/list" -H "X-Internal-Token: $TOKEN" | head
```

### 8.2 原始指标数据（旧端点：token-only）

```bash
curl -s "$BASE_URL/api/indicator/data?table=ATR波幅扫描器.py&symbol=BTC&interval=15m&limit=2" \
  -H "X-Internal-Token: $TOKEN" | head
```

### 8.3 表名直通（/api/v1/indicators/*，deprecated，token-only）

```bash
curl -s "$BASE_URL/api/v1/indicators/ATR波幅扫描器.py?mode=latest_per_symbol&interval=15m&limit=5" \
  -H "X-Internal-Token: $TOKEN" | head
```

---

## 9) 错误响应示例

### 9.1 参数错误（interval 非法）

```bash
curl -s "$BASE_URL/api/v1/ohlc/history?symbol=BTC&exchange=Binance&interval=invalid&limit=1" \
  -H "X-Internal-Token: $TOKEN" | head
```

### 9.2 表不存在（缺表诊断）

```bash
curl -s "$BASE_URL/api/futures/open-interest/history?symbol=BTC&interval=1h&limit=1" | head
```

典型响应（节选）：

```json
{
  "code": "40004",
  "msg": "表不存在: market_data.binance_futures_metrics_1h_last",
  "missing_table": {"schema": "market_data", "table": "binance_futures_metrics_1h_last"},
  "success": false
}
```

---

## 10) 错误码参考

| code | 说明 |
|:---|:---|
| `"0"` | 成功 |
| `"40001"` | 参数错误 |
| `"40002"` | symbol 无效 |
| `"40003"` | interval 无效 |
| `"40004"` | 表不存在 |
| `"50001"` | 服务不可用 |
| `"50002"` | 内部错误 |

---

*文档版本: 1.1*  
*最后更新: 2026-03-04*
