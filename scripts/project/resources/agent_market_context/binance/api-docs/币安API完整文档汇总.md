> 标签：历史/迁移文档
> 当前运行真相以 `README.md`、`README_EN.md`、`AGENTS.md` 与 `assets/docs/architecture/current-database-truth.md` 为准。

# 币安API完整文档汇总

## 概述

本文档整理了币安（Binance）API的所有主要接口类型和访问方式。币安提供了全面的API服务，涵盖现货交易、衍生品交易、行情数据、投资服务等多个方面。

## 🔗 官方文档地址

**主要文档入口：** [https://developers.binance.com/](https://developers.binance.com/)

**中文API文档：** [https://www.binance.com/zh-CN/binance-api](https://www.binance.com/zh-CN/binance-api)

## 📋 API类型分类

### 1. 现货交易 API

#### 现货交易（Spot Trading）
- **文档地址：** [https://developers.binance.com/docs/binance-spot-api-docs](https://developers.binance.com/docs/binance-spot-api-docs)
- **基础URL：** `https://api.binance.com`
- **替代URLs：** `https://api1.binance.com` - `https://api4.binance.com`（性能更高但稳定性较低）

##### 基础端点
- **连接测试：** `GET /api/v3/ping` （权重: 1）
- **服务器时间：** `GET /api/v3/time` （权重: 1）
- **交易规则信息：** `GET /api/v3/exchangeInfo` （权重: 20）

##### 市场数据端点

###### 深度信息 `GET /api/v3/depth`
- **权重：** 根据limit调整
  - 限制1-100: 权重5
  - 限制101-500: 权重25
  - 限制501-1000: 权重50
  - 限制1001-5000: 权重250
- **数据源：** 内存

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| limit | INT | NO | 默认100，最大5000。如果limit > 5000，只返回5000条数据 |

###### 最近成交 `GET /api/v3/trades`
- **权重：** 25
- **数据源：** 内存

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| limit | INT | NO | 默认500，最大1000 |

###### 历史成交 `GET /api/v3/historicalTrades`
- **权重：** 25
- **数据源：** 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| limit | INT | NO | 默认500，最大1000 |
| fromId | LONG | NO | 从此成交ID开始获取，默认获取最新成交 |

###### 聚合成交 `GET /api/v3/aggTrades`
- **权重：** 4
- **数据源：** 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| fromId | LONG | NO | 从此聚合成交ID开始获取（包含） |
| startTime | LONG | NO | 从此时间戳开始获取（包含） |
| endTime | LONG | NO | 获取到此时间戳为止（包含） |
| limit | INT | NO | 默认500，最大1000 |

**注意：** 如果未提供fromId、startTime和endTime，将返回最新的聚合成交

###### K线数据 `GET /api/v3/klines`
- **权重：** 2
- **数据源：** 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| interval | ENUM | YES | K线间隔 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| timeZone | STRING | NO | 时区，默认0 (UTC) |
| limit | INT | NO | 默认500，最大1000 |

**支持的K线间隔：**
- **秒：** 1s
- **分钟：** 1m, 3m, 5m, 15m, 30m
- **小时：** 1h, 2h, 4h, 6h, 8h, 12h
- **天：** 1d, 3d
- **周：** 1w
- **月：** 1M

**时区支持：**
- 小时和分钟格式：-1:00, 05:45
- 仅小时格式：0, 8, 4
- 接受范围：[-12:00 到 +14:00]

###### UI K线 `GET /api/v3/uiKlines`
- **权重：** 2
- **数据源：** 数据库
- **功能：** 返回针对蜡烛图显示优化的修改K线数据

**参数：** 与klines相同

###### 平均价格 `GET /api/v3/avgPrice`
- **权重：** 2
- **数据源：** 内存

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |

**响应示例：**
```json
{
  "mins": 5,
  "price": "9.35751834",
  "closeTime": 1694061154503
}
```

###### 24hr价格变动统计 `GET /api/v3/ticker/24hr`
- **权重：**
  - 单个交易对: 权重2
  - 无参数: 权重80
  - 1-20个交易对: 权重2
  - 21-100个交易对: 权重40
  - 101+个交易对: 权重80
- **数据源：** 内存

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 交易对，与symbols不能同时使用 |
| symbols | STRING | NO | 交易对数组，如["BTCUSDT","BNBUSDT"] |
| type | ENUM | NO | 支持值: FULL或MINI，默认FULL |

**注意：** 如果symbol和symbols都不提供，将返回所有交易对的行情

###### 交易日行情 `GET /api/v3/ticker/tradingDay`
- **权重：** 每个请求的交易对4个权重，超过50个交易对时权重上限为200
- **数据源：** 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 单个交易对，与symbols二选一 |
| symbols | STRING | NO | 交易对数组，最多100个 |
| timeZone | STRING | NO | 时区，默认0 (UTC) |
| type | ENUM | NO | 支持值: FULL或MINI，默认FULL |

###### 价格行情 `GET /api/v3/ticker/price`
- **权重：**
  - 单个交易对: 权重2
  - 无参数: 权重4
  - symbols参数: 权重4
- **数据源：** 内存

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 交易对，与symbols不能同时使用 |
| symbols | STRING | NO | 交易对数组 |

###### 最优挂单价格 `GET /api/v3/ticker/bookTicker`
- **权重：**
  - 单个交易对: 权重2
  - 无参数: 权重4
  - symbols参数: 权重4
- **数据源：** 内存

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 交易对，与symbols不能同时使用 |
| symbols | STRING | NO | 交易对数组 |

###### 滚动窗口价格变动统计 `GET /api/v3/ticker`
- **权重：** 每个交易对4个权重，超过50个交易对时权重上限为200
- **数据源：** 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 单个交易对，与symbols二选一 |
| symbols | STRING | NO | 交易对数组，最多100个 |
| windowSize | ENUM | NO | 默认1d，支持1m-59m（分钟）、1h-23h（小时）、1d-7d（天） |
| type | ENUM | NO | 支持值: FULL或MINI，默认FULL |

**注意：**
- 计算窗口最多比请求的windowSize宽59999ms
- openTime总是从分钟开始，closeTime是请求的当前时间
- 单位不能组合（如1d2h不被允许）

##### 交易端点（需要签名）

###### 下单接口 `POST /api/v3/order`
- **权重：** 1
- **数据源：** 撮合引擎

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| side | ENUM | YES | 订单方向 (BUY, SELL) |
| type | ENUM | YES | 订单类型 (LIMIT, MARKET, STOP_LOSS, STOP_LOSS_LIMIT, TAKE_PROFIT, TAKE_PROFIT_LIMIT, LIMIT_MAKER) |
| timeInForce | ENUM | NO | 生效时间 (GTC, IOC, FOK) |
| quantity | DECIMAL | NO | 下单数量 |
| quoteOrderQty | DECIMAL | NO | 报价资产数量 |
| price | DECIMAL | NO | 委托价格 |
| newClientOrderId | STRING | NO | 用户自定义订单ID，如空缺系统会自动赋值 |
| strategyId | LONG | NO | 策略ID |
| strategyType | INT | NO | 策略类型，不能低于1000000 |
| stopPrice | DECIMAL | NO | 触发价格，仅STOP_LOSS等订单需要 |
| trailingDelta | LONG | NO | 追踪止盈止损参数 |
| icebergQty | DECIMAL | NO | 冰山订单数量 |
| newOrderRespType | ENUM | NO | 响应类型 (ACK, RESULT, FULL) |
| selfTradePreventionMode | ENUM | NO | STP模式 |
| recvWindow | LONG | NO | 时间窗口，不能大于60000 |
| timestamp | LONG | YES | 时间戳 |

###### 测试下单 `POST /api/v3/order/test`
- **权重：** 1
- **功能：** 测试下单接口，参数与正式下单相同，但不会实际执行

###### 查询订单 `GET /api/v3/order`
- **权重：** 4
- **数据源：** 内存 => 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| orderId | LONG | NO | 订单ID |
| origClientOrderId | STRING | NO | 客户端订单ID |
| recvWindow | LONG | NO | 时间窗口，不能大于60000 |
| timestamp | LONG | YES | 时间戳 |

**注意：** orderId或origClientOrderId必须提供其一

###### 撤销订单 `DELETE /api/v3/order`
- **权重：** 1

###### 撤销所有订单 `DELETE /api/v3/openOrders`
- **权重：** 1

###### 当前挂单 `GET /api/v3/openOrders`
- **权重：**
  - 带symbol: 权重6
  - 不带symbol: 权重80
- **数据源：** 内存 => 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 交易对 |
| recvWindow | LONG | NO | 时间窗口，不能大于60000 |
| timestamp | LONG | YES | 时间戳 |

###### 历史订单 `GET /api/v3/allOrders`
- **权重：** 20
- **数据源：** 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| orderId | LONG | NO | 起始订单ID |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| limit | INT | NO | 默认500，最大1000 |
| recvWindow | LONG | NO | 时间窗口，不能大于60000 |
| timestamp | LONG | YES | 时间戳 |

##### OCO订单
- **下OCO单：** `POST /api/v3/order/oco`
- **查询OCO：** `GET /api/v3/orderList` （权重: 4）
- **查询所有OCO：** `GET /api/v3/allOrderList` （权重: 20）
- **查询开放OCO：** `GET /api/v3/openOrderList` （权重: 6）
- **撤销OCO：** `DELETE /api/v3/orderList`

##### 账户信息

###### 账户信息 `GET /api/v3/account`
- **权重：** 20
- **数据源：** 内存 => 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| omitZeroBalances | BOOLEAN | NO | 设置为true时，仅返回非零余额，默认值: false |
| recvWindow | LONG | NO | 时间窗口，不能大于60000 |
| timestamp | LONG | YES | 时间戳 |

**响应示例：**
```json
{
  "makerCommission": 15,
  "takerCommission": 15,
  "buyerCommission": 0,
  "sellerCommission": 0,
  "commissionRates": {
    "maker": "0.00150000",
    "taker": "0.00150000",
    "buyer": "0.00000000",
    "seller": "0.00000000"
  },
  "canTrade": true,
  "canWithdraw": true,
  "canDeposit": true,
  "balances": [
    {
      "asset": "BTC",
      "free": "4723846.89208129",
      "locked": "0.00000000"
    }
  ]
}
```

###### 账户成交历史 `GET /api/v3/myTrades`
- **权重：**
  - 不带orderId: 权重20
  - 带orderId: 权重5
- **数据源：** 内存 => 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| orderId | LONG | NO | 订单ID，只能与symbol同时使用 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| fromId | LONG | NO | 起始成交ID，默认获取最新成交 |
| limit | INT | NO | 默认500，最大1000 |
| recvWindow | LONG | NO | 时间窗口，不能大于60000 |
| timestamp | LONG | YES | 时间戳 |

**支持的参数组合：**
- symbol
- symbol + orderId
- symbol + startTime
- symbol + endTime
- symbol + fromId
- symbol + startTime + endTime
- symbol + orderId + fromId

###### 当前订单计数使用量 `GET /api/v3/rateLimit/order`
- **权重：** 40
- **数据源：** 内存
- **功能：** 显示用户所有时间间隔的未完成订单计数

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| recvWindow | LONG | NO | 时间窗口，不能大于60000 |
| timestamp | LONG | YES | 时间戳 |

**响应示例：**
```json
[
  {
    "rateLimitType": "ORDERS",
    "interval": "SECOND",
    "intervalNum": 10,
    "limit": 50,
    "count": 0
  },
  {
    "rateLimitType": "ORDERS",
    "interval": "DAY",
    "intervalNum": 1,
    "limit": 160000,
    "count": 0
  }
]
```

###### 查询预防匹配 `GET /api/v3/myPreventedMatches`
- **权重：**
  - 按preventedMatchId查询: 权重2
  - 按orderId查询: 权重20
  - symbol无效: 权重2
- **数据源：** 数据库
- **功能：** 显示因STP（自成交防护）过期的订单列表

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| preventedMatchId | LONG | NO | 预防匹配ID |
| orderId | LONG | NO | 订单ID |
| fromPreventedMatchId | LONG | NO | 起始预防匹配ID |
| limit | INT | NO | 默认500，最大1000 |
| recvWindow | LONG | NO | 时间窗口，不能大于60000 |
| timestamp | LONG | YES | 时间戳 |

**支持的参数组合：**
- symbol + preventedMatchId
- symbol + orderId
- symbol + orderId + fromPreventedMatchId (limit默认500)
- symbol + orderId + fromPreventedMatchId + limit

###### 查询分配 `GET /api/v3/myAllocations`
- **权重：** 20
- **数据源：** 数据库
- **功能：** 获取SOR订单分配的结果

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| fromAllocationId | INT | NO | 起始分配ID |
| limit | INT | NO | 默认500，最大1000 |
| orderId | LONG | NO | 订单ID |
| recvWindow | LONG | NO | 时间窗口，不能大于60000 |
| timestamp | LONG | NO | 时间戳 |

**注意：** startTime和endTime之间不能超过24小时

###### 查询佣金费率 `GET /api/v3/account/commission`
- **权重：** 20
- **数据源：** 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |

**响应示例：**
```json
{
  "symbol": "BTCUSDT",
  "standardCommission": {
    "maker": "0.00000010",
    "taker": "0.00000020",
    "buyer": "0.00000030",
    "seller": "0.00000040"
  },
  "taxCommission": {
    "maker": "0.00000112",
    "taker": "0.00000114",
    "buyer": "0.00000118",
    "seller": "0.00000116"
  },
  "discount": {
    "enabledForAccount": true,
    "enabledForSymbol": true,
    "discountAsset": "BNB",
    "discount": "0.75000000"
  }
}
```

#### 杠杆交易（Margin Trading）
- **文档地址：** [https://developers.binance.com/docs/margin_trading/Introduction](https://developers.binance.com/docs/margin_trading/Introduction)
- **功能：** 杠杆买卖、借贷管理、风险控制等
- **支持倍数：** 通常支持3x-10x杠杆

##### 主要端点
- **杠杆资产：** `GET /sapi/v1/margin/asset`
- **杠杆交易对：** `GET /sapi/v1/margin/pair`
- **获取所有杠杆资产：** `GET /sapi/v1/margin/allAssets`
- **杠杆账户信息：** `GET /sapi/v1/margin/account`
- **杠杆下单：** `POST /sapi/v1/margin/order`
- **借贷记录：** `GET /sapi/v1/margin/loan`
- **还款记录：** `GET /sapi/v1/margin/repay`

#### 闪兑（Convert）
- **文档地址：** [https://developers.binance.com/docs/convert/Introduction](https://developers.binance.com/docs/convert/Introduction)
- **功能：** 快速币种兑换、汇率查询等

##### 主要端点
- **获取汇率：** `GET /sapi/v1/convert/exchangeInfo`
- **获取报价：** `POST /sapi/v1/convert/getQuote`
- **确认兑换：** `POST /sapi/v1/convert/acceptQuote`
- **查询兑换历史：** `GET /sapi/v1/convert/tradeFlow`

#### 现货算法交易（Spot Algo Trading）
- **文档地址：** [https://developers.binance.com/docs/algo/spot-algo](https://developers.binance.com/docs/algo/spot-algo)
- **功能：** 算法订单、智能交易策略等

##### 算法订单类型
- **TWAP：** 时间加权平均价格
- **VP：** 成交量参与
- **实施快捷方式：** 立即执行

### 2. 衍生品交易 API

#### U本位合约（USDT-M Futures）
- **文档地址：** [https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info](https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info)
- **基础URL：** `https://fapi.binance.com`
- **测试网URL：** `https://testnet.binancefuture.com`
- **WebSocket URL：** `wss://fstream.binance.com/ws/`
- **测试网WebSocket：** `wss://fstream.binancefuture.com/ws/`

##### 认证与安全

###### 支持的签名算法
- **HMAC SHA256：** 传统的密钥签名方式
- **RSA-PKCS#8：** 更安全的公私钥模式（推荐）
- **Ed25519：** 最新的椭圆曲线签名（性能最佳）

###### 安全级别详解
| 安全类型 | 描述 |
|----------|------|
| NONE | 端点可自由访问 |
| MARKET_DATA | 需要发送有效的API密钥 |
| USER_STREAM | 需要发送有效的API密钥 |
| USER_DATA | 需要发送有效的API密钥和签名 |
| TRADE | 需要发送有效的API密钥和签名 |

###### 时间安全
- **timestamp参数：** 必须是请求创建和发送时的毫秒时间戳
- **recvWindow参数：** 指定请求在timestamp后的有效毫秒数，默认5000ms
- **时间同步：** 建议使用小于5000ms的recvWindow

**验证逻辑：**
```
if (timestamp < serverTime + 1000 && serverTime - timestamp <= recvWindow) {
  // 处理请求
} else {
  // 拒绝请求
}
```

##### 主要端点

###### 市场数据端点

**深度信息** `GET /fapi/v1/depth`
- **权重：** 根据limit调整
  - 限制1-100: 权重5
  - 限制101-500: 权重25
  - 限制501-1000: 权重50
  - 限制1001-5000: 权重250
- **数据源：** 内存

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| limit | INT | NO | 默认500，最大5000 |

**K线数据** `GET /fapi/v1/klines`
- **权重：** 1
- **数据源：** 数据库

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| interval | ENUM | YES | K线间隔 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| limit | INT | NO | 默认500，最大1500 |

**标记价格** `GET /fapi/v1/premiumIndex`
- **权重：** 1（单个交易对），40（所有交易对）

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 交易对 |

**资金费率** `GET /fapi/v1/fundingRate`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 交易对 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| limit | INT | NO | 默认100，最大1000 |

**24hr价格变动** `GET /fapi/v1/ticker/24hr`
- **权重：** 1（单个），40（所有）

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 交易对 |

###### 交易端点（需要签名）

**下单** `POST /fapi/v1/order`
- **权重：** 1
- **数据源：** 撮合引擎

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| side | ENUM | YES | 买卖方向 (BUY, SELL) |
| positionSide | ENUM | NO | 持仓方向 (BOTH, LONG, SHORT) |
| type | ENUM | YES | 订单类型 |
| timeInForce | ENUM | NO | 生效时间 (GTC, IOC, FOK, GTX) |
| quantity | DECIMAL | NO | 下单数量 |
| reduceOnly | BOOLEAN | NO | 只减仓，默认false |
| price | DECIMAL | NO | 委托价格 |
| newClientOrderId | STRING | NO | 用户自定义订单ID |
| stopPrice | DECIMAL | NO | 触发价格 |
| closePosition | BOOLEAN | NO | 全平标志 |
| activationPrice | DECIMAL | NO | 追踪止损激活价格 |
| callbackRate | DECIMAL | NO | 追踪止损回调比例 |
| workingType | ENUM | NO | 条件价格触发类型 |
| priceProtect | BOOLEAN | NO | 条件订单触发保护 |
| newOrderRespType | ENUM | NO | 响应类型 |
| priceMatch | ENUM | NO | 价格匹配模式 |
| selfTradePreventionMode | ENUM | NO | STP模式 |
| goodTillDate | LONG | NO | GTD订单有效期 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**订单类型说明：**
- LIMIT: 限价单
- MARKET: 市价单
- STOP: 止损单
- TAKE_PROFIT: 止盈单
- STOP_MARKET: 止损市价单
- TAKE_PROFIT_MARKET: 止盈市价单
- TRAILING_STOP_MARKET: 追踪止损市价单

**批量下单** `POST /fapi/v1/batchOrders`
- **权重：** 5
- **功能：** 单次请求最多包含5个订单

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| batchOrders | LIST | YES | 订单列表，最多5个 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**查询订单** `GET /fapi/v1/order`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| orderId | LONG | NO | 订单ID |
| origClientOrderId | STRING | NO | 客户端订单ID |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**注意：** orderId 或 origClientOrderId 必须提供其一

**撤销订单** `DELETE /fapi/v1/order`
- **权重：** 1

**撤销所有挂单** `DELETE /fapi/v1/allOpenOrders`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

###### 账户和持仓信息（需要签名）

**账户信息** `GET /fapi/v2/account`
- **权重：** 5

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**响应字段：**
- feeTier: 手续费等级
- canTrade: 可否交易
- canDeposit: 可否入金
- canWithdraw: 可否出金
- updateTime: 更新时间
- totalInitialMargin: 总初始保证金
- totalMaintMargin: 总维持保证金
- totalWalletBalance: 账户余额
- totalUnrealizedProfit: 全部未实现盈亏
- totalMarginBalance: 总保证金余额
- totalPositionInitialMargin: 持仓所需起始保证金
- totalOpenOrderInitialMargin: 当前挂单所需起始保证金
- totalCrossWalletBalance: 全仓账户余额
- totalCrossUnPnl: 全仓持仓未实现盈亏
- availableBalance: 可用余额

**持仓信息** `GET /fapi/v2/positionRisk`
- **权重：** 5

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 交易对 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**账户成交历史** `GET /fapi/v1/userTrades`
- **权重：** 5

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| fromId | LONG | NO | 起始成交ID |
| limit | INT | NO | 默认500，最大1000 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**调整杠杆** `POST /fapi/v1/leverage`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| leverage | INT | YES | 目标杠杆倍数 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**调整保证金** `POST /fapi/v1/positionMargin`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| positionSide | ENUM | NO | 持仓方向 |
| amount | DECIMAL | YES | 保证金资金 |
| type | INT | YES | 调整方向 (1:增加，2:减少) |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

###### 限制与配额

**IP限制：**
- 基于IP地址的频率限制
- 每个端点有不同的权重值
- 响应头包含 `X-MBX-USED-WEIGHT-(intervalNum)(intervalLetter)`
- 违反限制收到429错误码时必须退避
- IP封禁：2分钟到3天递增

**订单限制：**
- 基于账户的订单频率限制
- 响应头包含 `X-MBX-ORDER-COUNT-(intervalNum)(intervalLetter)`
- 计数针对每个账户
- 失败订单可能不包含计数头

**HTTP返回码：**
- **403：** WAF限制被违反
- **408：** 等待后端服务器响应超时
- **418：** IP自动封禁（继续发送429后）
- **429：** 超过请求频率限制
- **503：** 服务不可用

###### 下单示例（HMAC签名）

**参数表：**
| 参数 | 值 |
|------|-----|
| symbol | BTCUSDT |
| side | BUY |
| type | LIMIT |
| timeInForce | GTC |
| quantity | 1 |
| price | 9000 |
| recvWindow | 5000 |
| timestamp | 1591702613943 |

**查询字符串：**
```
symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=1&price=9000&timeInForce=GTC&recvWindow=5000&timestamp=1591702613943
```

**HMAC SHA256签名：**
```bash
echo -n "symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=1&price=9000&timeInForce=GTC&recvWindow=5000&timestamp=1591702613943" | openssl dgst -sha256 -hmac "your_secret_key"
```

**curl命令：**
```bash
curl -H "X-MBX-APIKEY: your_api_key" -X POST 'https://fapi.binance.com/fapi/v1/order?symbol=BTCUSDT&side=BUY&type=LIMIT&quantity=1&price=9000&timeInForce=GTC&recvWindow=5000&timestamp=1591702613943&signature=calculated_signature'
```

#### 币本位合约（COIN-M Futures）
- **文档地址：** [https://developers.binance.com/docs/derivatives/coin-margined-futures/general-info](https://developers.binance.com/docs/derivatives/coin-margined-futures/general-info)
- **基础URL：** `https://dapi.binance.com`
- **测试网URL：** `https://testnet.binancefuture.com`
- **WebSocket URL：** `wss://dstream.binance.com/ws/`
- **功能：** 币本位期货合约交易，以BTC、ETH等作为保证金

##### 主要特点
- **结算货币：** 合约标的物本身（如BTC合约用BTC结算）
- **杠杆倍数：** 最高125倍
- **合约类型：** 永续合约、交割合约

##### 主要端点

###### 市场数据端点

**深度信息** `GET /dapi/v1/depth`
- **权重：** 根据limit调整（同U本位）

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| limit | INT | NO | 默认500，最大5000 |

**K线数据** `GET /dapi/v1/klines`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| interval | ENUM | YES | K线间隔 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| limit | INT | NO | 默认500，最大1500 |

**聚合成交** `GET /dapi/v1/aggTrades`
- **权重：** 20

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| fromId | LONG | NO | 起始聚合成交ID |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| limit | INT | NO | 默认500，最大1000 |

**24hr价格变动** `GET /dapi/v1/ticker/24hr`
- **权重：** 1（单个），40（所有）

###### 交易端点（需要签名）

**下单** `POST /dapi/v1/order`
- **权重：** 1
- **数据源：** 撮合引擎

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| side | ENUM | YES | 买卖方向 (BUY, SELL) |
| positionSide | ENUM | NO | 持仓方向 (BOTH, LONG, SHORT) |
| type | ENUM | YES | 订单类型 |
| timeInForce | ENUM | NO | 生效时间 |
| quantity | DECIMAL | NO | 下单数量 |
| reduceOnly | STRING | NO | true/false，只减仓 |
| price | DECIMAL | NO | 委托价格 |
| newClientOrderId | STRING | NO | 用户自定义订单ID |
| stopPrice | DECIMAL | NO | 触发价格 |
| closePosition | STRING | NO | true/false，全平标志 |
| activationPrice | DECIMAL | NO | 追踪止损激活价格 |
| callbackRate | DECIMAL | NO | 追踪止损回调比例 |
| workingType | ENUM | NO | 条件价格触发类型 |
| priceProtect | STRING | NO | true/false，条件订单触发保护 |
| newOrderRespType | ENUM | NO | 响应类型 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**批量下单** `POST /dapi/v1/batchOrders`
- **权重：** 5
- **功能：** 单次请求最多包含5个订单

###### 账户和持仓信息（需要签名）

**账户信息** `GET /dapi/v1/account`
- **权重：** 5

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**响应字段：**
- canTrade: 可否交易
- canDeposit: 可否入金
- canWithdraw: 可否出金
- feeTier: 手续费等级
- updateTime: 更新时间
- totalInitialMargin: 总初始保证金
- totalMaintMargin: 总维持保证金
- totalWalletBalance: 账户余额
- totalUnrealizedProfit: 全部未实现盈亏
- totalMarginBalance: 总保证金余额
- totalPositionInitialMargin: 持仓所需起始保证金
- totalOpenOrderInitialMargin: 当前挂单所需起始保证金
- totalCrossWalletBalance: 全仓账户余额
- totalCrossUnPnl: 全仓持仓未实现盈亏
- availableBalance: 可用余额

**持仓信息** `GET /dapi/v1/positionRisk`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| marginAsset | STRING | NO | 保证金资产 |
| pair | STRING | NO | 交易对 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**账户成交历史** `GET /dapi/v1/userTrades`
- **权重：** 20

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 交易对 |
| pair | STRING | NO | 交易对基础货币 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| fromId | LONG | NO | 起始成交ID |
| limit | INT | NO | 默认500，最大1000 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**收入历史** `GET /dapi/v1/income`
- **权重：** 20

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 交易对 |
| incomeType | ENUM | NO | 收入类型 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| limit | INT | NO | 默认100，最大1000 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**收入类型枚举：**
- TRANSFER: 转账
- WELCOME_BONUS: 欢迎奖金
- REALIZED_PNL: 已实现盈亏
- FUNDING_FEE: 资金费
- COMMISSION: 手续费
- INSURANCE_CLEAR: 保险基金清算
- REFERRAL_KICKBACK: 推荐人返佣

#### 欧式期权（European Options）
- **文档地址：** [https://developers.binance.com/docs/derivatives/option/general-info](https://developers.binance.com/docs/derivatives/option/general-info)
- **基础URL：** `https://eapi.binance.com`
- **测试网URL：** `https://testnet.binanceops.com`
- **WebSocket URL：** `wss://nbstream.binance.com/eoptions/ws/`
- **功能：** 期权合约交易

##### 期权类型
- **看涨期权（Call）：** 买入权利
- **看跌期权（Put）：** 卖出权利
- **到期时间：** 每日、每周、每月到期

##### 主要端点

###### 市场数据端点

**期权信息** `GET /eapi/v1/exchangeInfo`
- **权重：** 1

**深度信息** `GET /eapi/v1/depth`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 期权交易对 |
| limit | INT | NO | 默认100，最大1000 |

**K线数据** `GET /eapi/v1/klines`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 期权交易对 |
| interval | ENUM | YES | K线间隔 |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| limit | INT | NO | 默认500，最大1500 |

**行情数据** `GET /eapi/v1/ticker`
- **权重：** 1（单个），5（所有）

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 期权交易对 |

**标记价格** `GET /eapi/v1/mark`
- **权重：** 1（单个），5（所有）

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 期权交易对 |

###### 交易端点（需要签名）

**下单** `POST /eapi/v1/order`
- **权重：** 1
- **数据源：** 撮合引擎

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 期权交易对 |
| side | ENUM | YES | 买卖方向 (BUY, SELL) |
| type | ENUM | YES | 订单类型 (LIMIT, MARKET) |
| quantity | DECIMAL | YES | 下单数量 |
| price | DECIMAL | NO | 委托价格（限价单必需） |
| timeInForce | ENUM | NO | 生效时间 (GTC, IOC, FOK) |
| reduceOnly | BOOLEAN | NO | 只减仓，默认false |
| postOnly | BOOLEAN | NO | 只做maker，默认false |
| newOrderRespType | ENUM | NO | 响应类型 |
| clientOrderId | STRING | NO | 用户自定义订单ID |
| isMmp | BOOLEAN | NO | 是否为MMP订单 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**批量下单** `POST /eapi/v1/batchOrders`
- **权重：** 5
- **功能：** 单次请求最多包含20个订单

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| orders | LIST | YES | 订单列表，最多20个 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**查询订单** `GET /eapi/v1/order`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 期权交易对 |
| orderId | LONG | NO | 订单ID |
| clientOrderId | STRING | NO | 客户端订单ID |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**撤销订单** `DELETE /eapi/v1/order`
- **权重：** 1

**撤销所有挂单** `DELETE /eapi/v1/allOpenOrders`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 期权交易对 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

###### 账户信息（需要签名）

**账户信息** `GET /eapi/v1/account`
- **权重：** 5

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**响应字段：**
- totalWalletBalance: 账户余额
- totalMarginBalance: 总保证金余额
- totalPositionInitialMargin: 持仓保证金
- totalOpenOrderInitialMargin: 挂单保证金
- totalCrossWalletBalance: 全仓账户余额
- totalCrossUnPnl: 全仓未实现盈亏
- availableBalance: 可用余额
- maxWithdrawAmount: 最大可转出金额

**持仓信息** `GET /eapi/v1/position`
- **权重：** 5

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 期权交易对 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**成交历史** `GET /eapi/v1/userTrades`
- **权重：** 5

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 期权交易对 |
| fromId | LONG | NO | 起始成交ID |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| limit | INT | NO | 默认500，最大1000 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**历史订单** `GET /eapi/v1/historyOrders`
- **权重：** 5

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | YES | 期权交易对 |
| orderId | LONG | NO | 起始订单ID |
| startTime | LONG | NO | 起始时间 |
| endTime | LONG | NO | 结束时间 |
| limit | INT | NO | 默认500，最大1000 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

##### 期权特殊功能

**做市商保护（MMP）** `POST /eapi/v1/mmpSet`
- **权重：** 1
- **功能：** 设置做市商保护参数

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| underlying | STRING | YES | 标的资产 |
| windowTimeInMilliseconds | LONG | YES | 时间窗口（毫秒） |
| frozenTimeInMilliseconds | LONG | YES | 冻结时间（毫秒） |
| qtyLimit | DECIMAL | YES | 数量限制 |
| deltaLimit | DECIMAL | YES | Delta限制 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**做市商保护状态** `GET /eapi/v1/mmpSet`
- **权重：** 1

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| underlying | STRING | YES | 标的资产 |
| recvWindow | LONG | NO | 时间窗口 |
| timestamp | LONG | YES | 时间戳 |

**希腊字母计算** `GET /eapi/v1/optionInfo`
- **权重：** 1
- **功能：** 获取期权的Delta、Gamma、Theta、Vega等希腊字母

**参数：**
| 名称 | 类型 | 是否必需 | 描述 |
|------|------|----------|------|
| symbol | STRING | NO | 期权交易对 |

#### 合约算法交易（Futures Algo Trading）
- **文档地址：** [https://developers.binance.com/docs/algo/Introduction](https://developers.binance.com/docs/algo/Introduction)
- **功能：** 合约算法订单、策略交易等

##### 算法类型
- **TWAP：** 时间加权平均价格算法
- **VP：** 成交量参与算法
- **实施快捷方式：** 立即执行算法

### 3. 行情数据 API

#### REST API 行情
- **文档地址：** [https://developers.binance.com/docs/binance-spot-api-docs/rest-api#market-data-endpoints](https://developers.binance.com/docs/binance-spot-api-docs/rest-api#market-data-endpoints)
- **功能：** 实时价格、深度数据、K线数据、交易历史等

#### WebSocket 流数据
- **文档地址：** [https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams)
- **主要WebSocket URL：** `wss://stream.binance.com:9443` 或 `wss://stream.binance.com:443`
- **纯市场数据URL：** `wss://data-stream.binance.vision` （仅市场数据，无用户数据）

##### WebSocket API（交互式）
- **基础端点：** `wss://ws-api.binance.com:443/ws-api/v3`
- **测试网端点：** `wss://ws-api.testnet.binance.vision/ws-api/v3`
- **备用端口：** 9443（如果443端口有问题）
- **功能：** 支持请求-响应模式的交互式API调用

###### WebSocket API特性
- **连接时长：** 单个连接仅在24小时内有效，之后会断开
- **签名支持：** 支持HMAC、RSA、Ed25519密钥类型
- **响应格式：** 默认JSON，可选SBE格式
- **心跳机制：** 服务器每20秒发送ping帧
- **时间戳格式：** 默认毫秒，可通过`timeUnit=MICROSECOND`使用微秒

###### 心跳要求
- 服务器每20秒发送ping帧
- 客户端必须在1分钟内回复pong帧，否则连接断开
- 收到ping时必须尽快回复带有ping负载的pong
- 允许主动发送pong帧，但不能防止断开
- **建议：** pong帧负载为空

##### WebSocket 数据流

###### 连接限制
- **连接限制：** 每IP每5分钟最多300个连接
- **消息限制：** 每连接每秒最多5条消息
- **流限制：** 每连接最多订阅1024个数据流
- **连接时长：** 单个连接最多24小时自动断开
- **数据顺序：** 按时间顺序返回，除非另有说明

###### 主要数据流类型

**交易相关流：**
- **聚合交易流：** `<symbol>@aggTrade` - 推送聚合交易信息
- **逐笔交易流：** `<symbol>@trade` - 推送每笔交易信息

**K线数据流：**
- **格式：** `<symbol>@kline_<interval>`
- **支持间隔：** 1s, 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
- **特点：** K线按其开盘时间唯一标识

**深度数据流：**
- **全量深度：** `<symbol>@depth` - 推送订单簿变化
- **部分深度：** `<symbol>@depth<levels>[@100ms]` - 推送Top N档位
- **支持档位：** 5, 10, 20
- **更新频率：** 默认1000ms，可选100ms

**价格统计流：**
- **24hr行情：** `<symbol>@ticker` - 推送24小时价格统计
- **迷你行情：** `<symbol>@miniTicker` - 推送精简版价格统计
- **最优价格：** `<symbol>@bookTicker` - 推送最优买卖价格
- **平均价格：** `<symbol>@avgPrice` - 推送平均价格

**全市场流：**
- **所有交易对行情：** `!ticker@arr` - 推送所有交易对24hr统计
- **所有迷你行情：** `!miniTicker@arr` - 推送所有交易对精简统计
- **所有最优价格：** `!bookTicker` - 推送所有交易对最优价格

###### 时区支持
- **UTC时区：** 默认UTC+0时区
- **自定义时区：** 添加时区后缀，如`<symbol>@kline_1d@+08:00`
- **支持格式：**
  - 小时和分钟：`-1:00`, `05:45`
  - 仅小时：`0`, `8`, `4`
  - 范围：`[-12:00 到 +14:00]`

###### 动态订阅管理
```json
// 订阅流
{
  "method": "SUBSCRIBE",
  "params": [
    "btcusdt@aggTrade",
    "btcusdt@depth"
  ],
  "id": 1
}

// 取消订阅
{
  "method": "UNSUBSCRIBE",
  "params": [
    "btcusdt@aggTrade"
  ],
  "id": 2
}

// 查看当前订阅
{
  "method": "LIST_SUBSCRIPTIONS",
  "id": 3
}

// 设置属性
{
  "method": "SET_PROPERTY",
  "params": [
    "combined",
    true
  ],
  "id": 4
}

// 查看属性
{
  "method": "GET_PROPERTY",
  "params": [
    "combined"
  ],
  "id": 5
}
```

###### 流访问方式

**单一流：**
```
wss://stream.binance.com:9443/ws/btcusdt@aggTrade
```

**组合流：**
```
wss://stream.binance.com:9443/stream?streams=btcusdt@aggTrade/btcusdt@depth
```

**微秒时间戳：**
```
wss://stream.binance.com:9443/stream?streams=btcusdt@aggTrade&timeUnit=MICROSECOND
```

###### 用户数据流
- **创建监听键：** `POST /api/v3/userDataStream`
- **保持监听键：** `PUT /api/v3/userDataStream`
- **关闭监听键：** `DELETE /api/v3/userDataStream`
- **连接用户流：** `wss://stream.binance.com:9443/ws/<listenKey>`

**用户数据推送：**
- **账户更新：** 余额变化、权限变更
- **余额更新：** 所有余额变化（包括0余额变化）
- **订单更新：** 订单状态变化、成交信息
- **OCO更新：** OCO订单状态变化

**示例消息格式：**
```json
{
  "e": "outboundAccountPosition",
  "E": 1564034571105,
  "u": 1564034571073,
  "B": [
    {
      "a": "ETH",
      "f": "10000.000000",
      "l": "0.000000"
    }
  ]
}
```

### 4. 投资与服务 API

#### 钱包管理
- **文档地址：** [https://developers.binance.com/docs/wallet/introduction](https://developers.binance.com/docs/wallet/introduction)
- **功能：** 资产查询、转账、充提币等

#### 保本赚币
- **文档地址：** [https://developers.binance.com/docs/simple_earn/Introduction](https://developers.binance.com/docs/simple_earn/Introduction)
- **功能：** 理财产品订阅、收益查询等

#### 矿池
- **文档地址：** [https://developers.binance.com/docs/mining/Introduction](https://developers.binance.com/docs/mining/Introduction)
- **功能：** 挖矿账户管理、收益统计等

#### 买币服务
- **文档地址：** [https://developers.binance.com/docs/c2c/introduction](https://developers.binance.com/docs/c2c/introduction)
- **功能：** C2C交易、法币购买等

#### 法币交易
- **文档地址：** [https://developers.binance.com/docs/fiat/introduction](https://developers.binance.com/docs/fiat/introduction)
- **功能：** 法币充值、提现等

#### ETH质押
- **文档地址：** [https://developers.binance.com/docs/staking/Introduction](https://developers.binance.com/docs/staking/Introduction)
- **功能：** ETH 2.0质押服务

#### 质押借币
- **文档地址：** [https://developers.binance.com/docs/crypto_loan/Introduction](https://developers.binance.com/docs/crypto_loan/Introduction)
- **功能：** 抵押借贷服务

### 5. 管理功能 API

#### 子账户管理
- **文档地址：** [https://developers.binance.com/docs/sub_account/Introduction](https://developers.binance.com/docs/sub_account/Introduction)
- **功能：** 子账户创建、管理、资产分配等

#### 税务报表API
- **功能：** 交易记录导出、税务报表生成

## 🔐 API认证与安全

### 1. API密钥类型
- **HMAC密钥：** 传统的API Key + Secret模式
- **RSA密钥：** 更安全的RSA公私钥模式（推荐）
- **Ed25519密钥：** 最新的椭圆曲线密钥（性能最佳）

### 2. 安全级别
- **NONE：** 公开访问，无需认证
- **MARKET_DATA：** 需要API Key
- **USER_STREAM：** 需要API Key
- **USER_DATA：** 需要API Key + 签名
- **TRADE：** 需要API Key + 签名

### 3. 签名算法
- **HMAC SHA256：** 用于HMAC密钥
- **RSASSA-PKCS1-v1_5：** 用于RSA密钥
- **Ed25519：** 用于Ed25519密钥

## 📊 限制与配额

### 1. IP限制
- 基于IP地址的请求频率限制
- 不同端点有不同的权重值
- 超限会收到429错误码

### 2. 订单限制
- 基于账户的订单频率限制
- 包含秒级、分钟级、日级限制
- 响应头会包含当前使用量

### 3. WebSocket连接限制
- 每个IP最多300个连接（5分钟内）
- 每个连接最多订阅1024个流
- 每秒最多5条消息

## 💻 SDK与开发工具

### 1. 官方Python SDK（推荐）

#### 项目概述
- **项目地址：** [binance-connector-python](https://github.com/binance/binance-connector-python)
- **特点：** 模块化设计，25个独立包，按需安装
- **维护状态：** 币安官方维护，使用OpenAPI Generator自动生成
- **Python版本要求：** 3.9+

#### 可用模块列表

**交易模块：**
- `binance-sdk-spot` - 现货交易
- `binance-sdk-margin-trading` - 杠杆交易
- `binance-sdk-derivatives-trading-usds-futures` - U本位合约
- `binance-sdk-derivatives-trading-coin-futures` - 币本位合约
- `binance-sdk-derivatives-trading-options` - 期权交易
- `binance-sdk-derivatives-trading-portfolio-margin` - 组合保证金期货
- `binance-sdk-derivatives-trading-portfolio-margin-pro` - 组合保证金Pro
- `binance-sdk-copy-trading` - 跟单交易

**算法与转换：**
- `binance-sdk-algo` - 算法交易
- `binance-sdk-convert` - 闪兑服务

**理财服务：**
- `binance-sdk-simple-earn` - 简单收益
- `binance-sdk-staking` - 质押服务
- `binance-sdk-dual-investment` - 双币投资

**借贷服务：**
- `binance-sdk-crypto-loan` - 加密货币借贷
- `binance-sdk-vip-loan` - VIP借贷

**账户管理：**
- `binance-sdk-wallet` - 钱包管理
- `binance-sdk-sub-account` - 子账户管理

**支付交易：**
- `binance-sdk-pay` - 币安支付
- `binance-sdk-c2c` - C2C交易
- `binance-sdk-fiat` - 法币交易

**其他服务：**
- `binance-sdk-mining` - 矿池服务
- `binance-sdk-nft` - NFT服务
- `binance-sdk-gift-card` - 礼品卡
- `binance-sdk-rebate` - 返佣服务

### 2. 安装方式

#### 单模块安装
```bash
# 使用pip安装现货交易模块
pip install binance-sdk-spot

# 使用poetry安装
poetry add binance-sdk-spot
```

#### 多模块安装
```bash
# 安装多个相关模块
pip install binance-sdk-spot binance-sdk-margin-trading binance-sdk-staking

# 使用poetry安装多个模块
poetry add binance-sdk-spot binance-sdk-margin-trading binance-sdk-staking
```

### 3. 使用示例

#### 现货交易示例
```python
from binance_sdk_spot import SpotTradingClient
import os

# 初始化客户端
client = SpotTradingClient(
    api_key=os.getenv('BINANCE_API_KEY'),
    api_secret=os.getenv('BINANCE_API_SECRET'),
    base_url='https://api.binance.com'  # 生产环境
    # base_url='https://testnet.binance.vision'  # 测试环境
)

# 获取账户信息
try:
    account_info = client.get_account()
    print(f"账户状态: {account_info['accountType']}")
    print(f"余额信息: {account_info['balances'][:5]}")  # 显示前5个余额
except Exception as e:
    print(f"获取账户信息失败: {e}")

# 获取交易对信息
exchange_info = client.get_exchange_info()
print(f"可用交易对数量: {len(exchange_info['symbols'])}")

# 获取当前价格
ticker = client.get_ticker_price(symbol='BTCUSDT')
print(f"BTC/USDT 当前价格: {ticker['price']}")

# 下限价买单（示例，请谨慎使用）
# order = client.new_order(
#     symbol='BTCUSDT',
#     side='BUY',
#     type='LIMIT',
#     timeInForce='GTC',
#     quantity='0.001',
#     price='30000.00'
# )
```

#### U本位合约示例
```python
from binance_sdk_derivatives_trading_usds_futures import UsdsFuturesClient

# 初始化合约客户端
futures_client = UsdsFuturesClient(
    api_key=os.getenv('BINANCE_API_KEY'),
    api_secret=os.getenv('BINANCE_API_SECRET'),
    base_url='https://fapi.binance.com'
)

# 获取合约账户信息
account = futures_client.get_account()
print(f"合约账户余额: {account['totalWalletBalance']} USDT")
print(f"可用余额: {account['availableBalance']} USDT")

# 获取持仓信息
positions = futures_client.get_position_risk()
active_positions = [p for p in positions if float(p['positionAmt']) != 0]
print(f"当前持仓数量: {len(active_positions)}")

# 获取合约价格
ticker = futures_client.get_ticker_price(symbol='BTCUSDT')
print(f"BTC合约价格: {ticker['price']}")
```

#### 质押服务示例
```python
from binance_sdk_staking import StakingClient

# 初始化质押客户端
staking_client = StakingClient(
    api_key=os.getenv('BINANCE_API_KEY'),
    api_secret=os.getenv('BINANCE_API_SECRET')
)

# 获取质押产品列表
products = staking_client.get_staking_product_list(product='STAKING')
print(f"可用质押产品: {len(products)}")

# 获取个人质押记录
personal_left_quota = staking_client.get_personal_left_quota(
    product='STAKING',
    productId='ETH001'
)
print(f"ETH质押剩余额度: {personal_left_quota}")
```

### 4. 其他官方SDK
- **Java：** [binance-connector-java](https://github.com/binance/binance-connector-java)
- **Node.js：** [binance-connector-node](https://github.com/binance/binance-connector-node)

### 3. Postman集合
- **GitHub地址：** [binance-api-postman](https://github.com/binance-exchange/binance-api-postman)
- **功能：** 预配置的API请求集合，方便测试

## 🌐 测试环境

### 1. 现货测试网
- **网址：** [https://testnet.binance.vision/](https://testnet.binance.vision/)
- **API URL：** `https://testnet.binance.vision`

### 2. 期货测试网
- **网址：** [https://testnet.binancefuture.com/](https://testnet.binancefuture.com/)
- **API URL：** `https://testnet.binancefuture.com`
- **WebSocket：** `wss://fstream.binancefuture.com`

## 📖 错误代码与处理

### 1. HTTP状态码详解
- **403 Forbidden：** WAF（Web应用防火墙）限制，请求被拦截
- **408 Request Timeout：** 等待后端服务器响应超时
- **418 I'm a teapot：** IP被自动封禁（发送429后继续请求导致）
- **429 Too Many Requests：** 超过频率限制，需要退避重试
- **503 Service Unavailable：** 服务不可用，可能原因：
  - "Unknown error, please check your request or try again later." - 请求已发送但超时，执行状态未知
  - "Service Unavailable." - 服务暂时不可用，需要重试
  - "Internal error; unable to process your request. Please try again." - 内部错误，可以重新发送请求

### 2. 常见业务错误码
- **-1000：** 未知错误
- **-1001：** 服务器断开连接
- **-1002：** 您无权使用此请求
- **-1003：** 请求太频繁
- **-1006：** 意外的响应
- **-1007：** 超时
- **-1014：** 不支持的订单组合
- **-1015：** 新订单太多
- **-1016：** 服务器已关闭
- **-1020：** 不支持的操作
- **-1021：** 时间戳超出recvWindow范围
- **-1022：** 签名无效
- **-1100：** 非法字符
- **-1101：** 参数太多
- **-1102：** 强制参数丢失
- **-1103：** 未知参数
- **-1104：** 重复参数
- **-1105：** 参数为空
- **-1106：** 不需要参数
- **-1111：** 精度过高
- **-1112：** 无订单
- **-1114：** 时间未同步
- **-1115：** 无效时间间隔
- **-1116：** 无效符号
- **-1117：** 无效监听键
- **-1118：** 无效间隔
- **-1119：** 无效符号
- **-1120：** 无效间隔
- **-1121：** 无效符号
- **-1125：** 无效监听键
- **-1130：** 数据发送非法

### 3. 交易相关错误码
- **-2010：** 新订单被拒绝
- **-2011：** 订单取消被拒绝
- **-2013：** 订单不存在
- **-2014：** API键格式无效
- **-2015：** API键无效、IP限制或权限不足
- **-2016：** 交易被禁用
- **-2017：** 余额不足
- **-2018：** 保证金不足
- **-2019：** 无法填充订单
- **-2020：** 订单会立即触发
- **-2021：** 订单价格比市场价高太多
- **-2022：** 订单价格比市场价低太多

### 4. 错误处理最佳实践
- **指数退避重试：** 遇到429或503时，使用指数退避策略重试
- **错误日志记录：** 详细记录API调用错误，便于问题排查
- **监控告警：** 设置错误率和响应时间监控
- **优雅降级：** 在API不可用时提供备用方案

## 💡 API调用示例

### 1. Python示例（现货交易）

```python
import hmac
import hashlib
import time
import requests
from urllib.parse import urlencode

# API配置
API_KEY = "your_api_key"
SECRET_KEY = "your_secret_key"
BASE_URL = "https://api.binance.com"

def generate_signature(query_string, secret_key):
    """生成HMAC SHA256签名"""
    return hmac.new(
        secret_key.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

def get_account_info():
    """获取账户信息"""
    endpoint = "/api/v3/account"
    timestamp = int(time.time() * 1000)

    params = {
        'timestamp': timestamp,
        'recvWindow': 5000
    }

    query_string = urlencode(params)
    signature = generate_signature(query_string, SECRET_KEY)
    params['signature'] = signature

    headers = {
        'X-MBX-APIKEY': API_KEY
    }

    response = requests.get(BASE_URL + endpoint, params=params, headers=headers)
    return response.json()

def place_order(symbol, side, type, quantity, price=None):
    """下单示例"""
    endpoint = "/api/v3/order"
    timestamp = int(time.time() * 1000)

    params = {
        'symbol': symbol,
        'side': side,  # BUY or SELL
        'type': type,  # MARKET, LIMIT, etc.
        'quantity': quantity,
        'timestamp': timestamp,
        'recvWindow': 5000
    }

    if price and type == 'LIMIT':
        params['price'] = price
        params['timeInForce'] = 'GTC'

    query_string = urlencode(params)
    signature = generate_signature(query_string, SECRET_KEY)
    params['signature'] = signature

    headers = {
        'X-MBX-APIKEY': API_KEY
    }

    response = requests.post(BASE_URL + endpoint, params=params, headers=headers)
    return response.json()

# 使用示例
if __name__ == "__main__":
    # 获取账户信息
    account = get_account_info()
    print("账户信息:", account)

    # 下限价买单
    order = place_order('BTCUSDT', 'BUY', 'LIMIT', '0.001', '30000')
    print("订单结果:", order)
```

### 2. WebSocket连接示例

```python
import websocket
import json

def on_message(ws, message):
    """处理WebSocket消息"""
    data = json.loads(message)
    if 'stream' in data:
        stream_name = data['stream']
        stream_data = data['data']
        print(f"收到 {stream_name} 数据:", stream_data)
    else:
        print("收到数据:", data)

def on_error(ws, error):
    """处理WebSocket错误"""
    print("WebSocket错误:", error)

def on_close(ws, close_status_code, close_msg):
    """WebSocket关闭"""
    print("WebSocket连接已关闭")

def on_open(ws):
    """WebSocket连接成功"""
    print("WebSocket连接已建立")

    # 订阅多个数据流
    subscribe_msg = {
        "method": "SUBSCRIBE",
        "params": [
            "btcusdt@ticker",
            "ethusdt@ticker",
            "bnbusdt@depth5@100ms"
        ],
        "id": 1
    }
    ws.send(json.dumps(subscribe_msg))

# 建立WebSocket连接
if __name__ == "__main__":
    ws = websocket.WebSocketApp(
        "wss://stream.binance.com:9443/ws/",
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    ws.run_forever()
```

### 3. JavaScript示例（Node.js）

```javascript
const crypto = require('crypto');
const axios = require('axios');

class BinanceAPI {
    constructor(apiKey, secretKey) {
        this.apiKey = apiKey;
        this.secretKey = secretKey;
        this.baseURL = 'https://api.binance.com';
    }

    generateSignature(queryString) {
        return crypto
            .createHmac('sha256', this.secretKey)
            .update(queryString)
            .digest('hex');
    }

    async request(method, endpoint, params = {}) {
        const timestamp = Date.now();
        const queryParams = { ...params, timestamp, recvWindow: 5000 };

        const queryString = new URLSearchParams(queryParams).toString();
        const signature = this.generateSignature(queryString);

        const config = {
            method,
            url: `${this.baseURL}${endpoint}?${queryString}&signature=${signature}`,
            headers: {
                'X-MBX-APIKEY': this.apiKey
            }
        };

        try {
            const response = await axios(config);
            return response.data;
        } catch (error) {
            throw new Error(`API请求失败: ${error.response?.data?.msg || error.message}`);
        }
    }

    // 获取账户信息
    async getAccountInfo() {
        return await this.request('GET', '/api/v3/account');
    }

    // 获取当前价格
    async getPrice(symbol) {
        return await this.request('GET', '/api/v3/ticker/price', { symbol });
    }

    // 下单
    async placeOrder(symbol, side, type, quantity, price = null) {
        const params = { symbol, side, type, quantity };

        if (price && type === 'LIMIT') {
            params.price = price;
            params.timeInForce = 'GTC';
        }

        return await this.request('POST', '/api/v3/order', params);
    }
}

// 使用示例
async function main() {
    const api = new BinanceAPI('your_api_key', 'your_secret_key');

    try {
        // 获取BTC价格
        const btcPrice = await api.getPrice('BTCUSDT');
        console.log('BTC价格:', btcPrice);

        // 获取账户信息
        const account = await api.getAccountInfo();
        console.log('账户余额:', account.balances.slice(0, 5));

    } catch (error) {
        console.error('错误:', error.message);
    }
}

main();
```

## 📝 使用建议

### 1. 最佳实践
- **优先使用WebSocket：** 实时数据用WebSocket，查询数据用REST API
- **选择高性能签名：** Ed25519 > RSA > HMAC SHA256
- **合理设置时间窗口：** recvWindow建议设置为5000ms以下
- **实现指数退避：** 遇到限制时使用指数退避重试策略
- **监控API使用量：** 通过响应头监控权重使用情况

### 2. 性能优化策略
- **批量操作：** 使用批量接口减少API调用次数
- **数据缓存：** 缓存交易对信息、汇率等静态或准静态数据
- **连接复用：** 合理设置HTTP连接池，复用TCP连接
- **压缩传输：** 启用gzip压缩减少网络传输
- **就近访问：** 根据地理位置选择最近的API节点

### 3. 安全风险控制
- **API权限最小化：** 只开启必要的API权限
- **IP白名单：** 在币安账户中设置API的IP白名单
- **密钥轮换：** 定期更换API密钥
- **异常监控：** 监控异常交易和API调用
- **资金管理：** 设置合理的订单金额和仓位限制
- **多重验证：** 重要操作启用双重身份验证

## 📥 如何获取完整文档

### 1. 官方下载方式
由于币安API文档内容庞大且经常更新，建议直接访问官方文档获取最新版本：

1. **在线查看：** 访问 [https://developers.binance.com/](https://developers.binance.com/)
2. **GitHub源码：** [binance-spot-api-docs](https://github.com/binance/binance-spot-api-docs)
3. **API规范：** [binance-api-swagger](https://github.com/binance-exchange/binance-api-swagger)

### 2. 本地部署文档
```bash
# 克隆官方文档仓库
git clone https://github.com/binance/binance-spot-api-docs.git

# 查看文档
cd binance-spot-api-docs
# 文档为Markdown格式，可用任意Markdown阅读器查看
```

### 3. 开发工具
- **Postman集合：** 导入官方Postman集合进行API测试
- **Swagger UI：** 使用OpenAPI规范文件生成交互式文档
- **官方SDK：** 使用官方提供的各语言SDK

## 🔗 相关链接

- **币安开发者平台：** [https://developers.binance.com/](https://developers.binance.com/)
- **API状态页面：** [https://binance.statuspage.io/](https://binance.statuspage.io/)
- **开发者社区：** [https://dev.binance.vision/](https://dev.binance.vision/)
- **官方支持：** [https://www.binance.com/zh-CN/support](https://www.binance.com/zh-CN/support)

## 📄 版权声明

本文档内容来源于币安官方API文档，仅用于学习和开发参考。请以官方最新文档为准。

---

**最后更新：** 2025年1月

**文档来源：** 币安官方API文档整理
