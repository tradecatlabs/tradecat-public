# 币安API全面端点枚举和分析报告

基于对币安官方API文档的访问和分析，我为您提供以下详细的API端点枚举：

## 📊 1. 现货交易API (Spot Trading API)

### 基础URL
- 主要端点: `https://api.binance.com`
- 备用端点: `https://api-gcp.binance.com`, `https://api1.binance.com`, `https://api2.binance.com`, `https://api3.binance.com`, `https://api4.binance.com`

### 1.1 市场数据端点 (Market Data Endpoints)

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/api/v3/ping` | GET | 1 | 否 | 测试连接 |
| `/api/v3/time` | GET | 1 | 否 | 获取服务器时间 |
| `/api/v3/exchangeInfo` | GET | 20 | 否 | 获取交易所信息 |
| `/api/v3/depth` | GET | 1-100 | 否 | 获取订单簿深度 |
| `/api/v3/trades` | GET | 10 | 否 | 获取近期成交 |
| `/api/v3/historicalTrades` | GET | 25 | 是 | 获取历史成交 |
| `/api/v3/aggTrades` | GET | 2 | 否 | 获取聚合成交 |
| `/api/v3/klines` | GET | 2 | 否 | 获取K线数据 |
| `/api/v3/uiKlines` | GET | 2 | 否 | 获取UI K线数据 |
| `/api/v3/avgPrice` | GET | 2 | 否 | 获取平均价格 |
| `/api/v3/ticker/24hr` | GET | 1-80 | 否 | 获取24小时价格统计 |
| `/api/v3/ticker/tradingDay` | GET | 4 | 否 | 获取交易日价格统计 |
| `/api/v3/ticker/price` | GET | 1-4 | 否 | 获取最新价格 |
| `/api/v3/ticker/bookTicker` | GET | 1-4 | 否 | 获取最优挂单价格 |
| `/api/v3/ticker` | GET | 2-80 | 否 | 获取滚动窗口价格统计 |

参数详情示例 - `/api/v3/klines`:
| 参数名 | 类型 | 必需 | 描述 | 示例值 |
|--------|------|------|------|-------|
| symbol | STRING | 是 | 交易对 | BTCUSDT |
| interval | ENUM | 是 | K线间隔 | 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M |
| startTime | LONG | 否 | 开始时间 | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 1499644800000 |
| timeZone | STRING | 否 | 时区 | 0 (UTC) |
| limit | INT | 否 | 数量限制 | 500 (默认), 最大1000 |

### 1.2 账户和交易端点 (Account & Trading Endpoints)

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/api/v3/order/test` | POST | 1 | 是 | 测试下单 |
| `/api/v3/order` | POST | 1 | 是 | 下单 |
| `/api/v3/order` | DELETE | 1 | 是 | 撤销订单 |
| `/api/v3/openOrders` | DELETE | 1 | 是 | 撤销所有订单 |
| `/api/v3/order` | GET | 4 | 是 | 查询订单 |
| `/api/v3/openOrders` | GET | 6 | 是 | 查询当前挂单 |
| `/api/v3/allOrders` | GET | 20 | 是 | 查询所有订单 |
| `/api/v3/order/oco` | POST | 1 | 是 | OCO下单 |
| `/api/v3/orderList` | DELETE | 1 | 是 | 撤销OCO订单 |
| `/api/v3/orderList` | GET | 4 | 是 | 查询OCO订单 |
| `/api/v3/allOrderList` | GET | 20 | 是 | 查询所有OCO订单 |
| `/api/v3/openOrderList` | GET | 6 | 是 | 查询OCO挂单 |
| `/api/v3/account` | GET | 20 | 是 | 查询账户信息 |
| `/api/v3/myTrades` | GET | 20 | 是 | 查询成交历史 |
| `/api/v3/rateLimit/order` | GET | 40 | 是 | 查询订单速率限制 |
| `/api/v3/order/amend/keepPriority` | PUT | 1 | 是 | 修改订单 |

参数详情示例 - `/api/v3/order` (POST):
| 参数名 | 类型 | 必需 | 描述 | 示例值 |
|--------|------|------|------|-------|
| symbol | STRING | 是 | 交易对 | BTCUSDT |
| side | ENUM | 是 | 买卖方向 | BUY, SELL |
| type | ENUM | 是 | 订单类型 | LIMIT, MARKET, STOP_LOSS, STOP_LOSS_LIMIT, TAKE_PROFIT, TAKE_PROFIT_LIMIT, LIMIT_MAKER |
| timeInForce | ENUM | 否 | 有效时间 | GTC, IOC, FOK |
| quantity | DECIMAL | 否 | 数量 | 1.00000000 |
| quoteOrderQty | DECIMAL | 否 | 报价数量 | 10.00000000 |
| price | DECIMAL | 否 | 价格 | 0.1 |
| newClientOrderId | STRING | 否 | 客户端订单ID | my_order_id_1 |
| strategyId | INT | 否 | 策略ID | 1 |
| strategyType | INT | 否 | 策略类型 | 1000000 |
| stopPrice | DECIMAL | 否 | 止损价格 | 0.1 |
| trailingDelta | LONG | 否 | 追踪止损 | 10 |
| icebergQty | DECIMAL | 否 | 冰山数量 | 0.1 |
| newOrderRespType | ENUM | 否 | 响应类型 | ACK, RESULT, FULL |
| selfTradePreventionMode | ENUM | 否 | 自成交防护 | EXPIRE_TAKER, EXPIRE_MAKER, EXPIRE_BOTH, NONE |
| goodTillDate | LONG | 否 | 有效期 | 1693207680000 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 1499827319559 |

## 📈 2. 期货交易API (Futures Trading API)

### 基础URL
- U本位合约: `https://fapi.binance.com`
- 币本位合约: `https://dapi.binance.com`

### 2.1 U本位合约API端点

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/fapi/v1/ping` | GET | 1 | 否 | 测试连接 |
| `/fapi/v1/time` | GET | 1 | 否 | 获取服务器时间 |
| `/fapi/v1/exchangeInfo` | GET | 1 | 否 | 获取交易所信息 |
| `/fapi/v1/depth` | GET | 1-50 | 否 | 获取订单簿深度 |
| `/fapi/v1/trades` | GET | 1 | 否 | 获取近期成交 |
| `/fapi/v1/historicalTrades` | GET | 20 | 是 | 获取历史成交 |
| `/fapi/v1/aggTrades` | GET | 1 | 否 | 获取聚合成交 |
| `/fapi/v1/klines` | GET | 1 | 否 | 获取K线数据 |
| `/fapi/v1/continuousKlines` | GET | 1 | 否 | 获取连续合约K线 |
| `/fapi/v1/indexPriceKlines` | GET | 1 | 否 | 获取指数价格K线 |
| `/fapi/v1/markPriceKlines` | GET | 1 | 否 | 获取标记价格K线 |
| `/fapi/v1/premiumIndexKlines` | GET | 1 | 否 | 获取溢价指数K线 |
| `/fapi/v1/premiumIndex` | GET | 1 | 否 | 获取标记价格和资金费率 |
| `/fapi/v1/fundingRate` | GET | 1 | 否 | 获取资金费率历史 |
| `/fapi/v1/fundingInfo` | GET | 1 | 否 | 获取资金费率信息 |
| `/fapi/v1/ticker/24hr` | GET | 1-80 | 否 | 获取24小时价格统计 |
| `/fapi/v1/ticker/price` | GET | 1-2 | 否 | 获取最新价格 |
| `/fapi/v1/ticker/bookTicker` | GET | 1-2 | 否 | 获取最优挂单价格 |
| `/fapi/v1/openInterest` | GET | 1 | 否 | 获取持仓量 |
| `/fapi/v1/constituents` | GET | 2 | 否 | 获取指数成分 |
| `/fapi/v1/assetIndex` | GET | 1 | 否 | 获取多资产模式汇率指数 |

### 2.2 期货高级数据端点

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/futures/data/openInterestHist` | GET | 1 | 否 | 获取持仓量历史 |
| `/futures/data/topLongShortAccountRatio` | GET | 1 | 否 | 获取大户账户数多空比 |
| `/futures/data/topLongShortPositionRatio` | GET | 1 | 否 | 获取大户持仓量多空比 |
| `/futures/data/globalLongShortAccountRatio` | GET | 1 | 否 | 获取多空账户数比例 |
| `/futures/data/takerlongshortRatio` | GET | 1 | 否 | 获取合约主动买卖量 |
| `/futures/data/basis` | GET | 1 | 否 | 获取基差数据 |

### 2.3 期货交易端点

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/fapi/v1/order` | POST | 0 | 是 | 下单 |
| `/fapi/v1/order` | DELETE | 1 | 是 | 撤销订单 |
| `/fapi/v1/allOpenOrders` | DELETE | 1 | 是 | 撤销所有订单 |
| `/fapi/v1/order` | GET | 1 | 是 | 查询订单 |
| `/fapi/v1/openOrders` | GET | 1 | 是 | 查询当前挂单 |
| `/fapi/v1/allOrders` | GET | 5 | 是 | 查询所有订单 |
| `/fapi/v2/balance` | GET | 5 | 是 | 查询余额 |
| `/fapi/v2/account` | GET | 5 | 是 | 查询账户信息 |
| `/fapi/v1/userTrades` | GET | 5 | 是 | 查询成交历史 |
| `/fapi/v1/positionRisk` | GET | 5 | 是 | 查询持仓风险 |
| `/fapi/v1/leverage` | POST | 1 | 是 | 调整杠杆 |
| `/fapi/v1/marginType` | POST | 1 | 是 | 变更保证金模式 |
| `/fapi/v1/positionMargin` | POST | 1 | 是 | 调整逐仓保证金 |

## 🎯 3. 期权API (Options API)

### 基础URL
- 欧式期权: `https://eapi.binance.com`

### 3.1 期权市场数据端点

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/eapi/v1/ping` | GET | 1 | 否 | 测试连接 |
| `/eapi/v1/time` | GET | 1 | 否 | 获取服务器时间 |
| `/eapi/v1/exchangeInfo` | GET | 1 | 否 | 获取交易所信息 |
| `/eapi/v1/depth` | GET | 1 | 否 | 获取订单簿深度 |
| `/eapi/v1/klines` | GET | 1 | 否 | 获取K线数据 |
| `/eapi/v1/mark` | GET | 1 | 否 | 获取标记价格 |
| `/eapi/v1/ticker` | GET | 1 | 否 | 获取24小时价格统计 |
| `/eapi/v1/index` | GET | 1 | 否 | 获取指数价格 |
| `/eapi/v1/exerciseHistory` | GET | 1 | 否 | 获取行权历史 |
| `/eapi/v1/openInterest` | GET | 1 | 否 | 获取持仓量 |

## 💰 4. 杠杆交易API (Margin Trading API)

### 4.1 杠杆账户端点

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/sapi/v1/margin/account` | GET | 10 | 是 | 查询杠杆账户详情 |
| `/sapi/v1/margin/asset` | GET | 10 | 是 | 查询杠杆资产 |
| `/sapi/v1/margin/pair` | GET | 10 | 是 | 查询杠杆交易对 |
| `/sapi/v1/margin/allAssets` | GET | 1 | 是 | 查询所有杠杆资产 |
| `/sapi/v1/margin/allPairs` | GET | 1 | 是 | 查询所有杠杆交易对 |
| `/sapi/v1/margin/priceIndex` | GET | 10 | 是 | 查询杠杆价格指数 |
| `/sapi/v1/margin/transfer` | POST | 600 | 是 | 杠杆账户转账 |
| `/sapi/v1/margin/loan` | POST | 3000 | 是 | 杠杆账户借贷 |
| `/sapi/v1/margin/repay` | POST | 3000 | 是 | 杠杆账户还贷 |
| `/sapi/v1/margin/order` | POST | 6 | 是 | 杠杆账户下单 |
| `/sapi/v1/margin/order` | DELETE | 10 | 是 | 杠杆账户撤单 |
| `/sapi/v1/margin/openOrders` | GET | 10 | 是 | 查询杠杆挂单 |
| `/sapi/v1/margin/allOrders` | GET | 200 | 是 | 查询杠杆所有订单 |
| `/sapi/v1/margin/myTrades` | GET | 10 | 是 | 查询杠杆成交历史 |

## 💼 5. 钱包API (Wallet API)

### 5.1 钱包端点

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/sapi/v1/system/status` | GET | 1 | 否 | 获取系统状态 |
| `/sapi/v1/capital/config/getall` | GET | 10 | 是 | 获取所有币种信息 |
| `/sapi/v1/account/snapshot` | GET | 2400 | 是 | 获取账户快照 |
| `/sapi/v1/account/disableFastWithdrawSwitch` | POST | 1 | 是 | 关闭快速提现 |
| `/sapi/v1/account/enableFastWithdrawSwitch` | POST | 1 | 是 | 开启快速提现 |
| `/sapi/v1/capital/withdraw/apply` | POST | 600 | 是 | 提现 |
| `/sapi/v1/capital/deposit/hisrec` | GET | 1 | 是 | 获取充值历史 |
| `/sapi/v1/capital/withdraw/history` | GET | 18000 | 是 | 获取提现历史 |
| `/sapi/v1/capital/deposit/address` | GET | 10 | 是 | 获取充值地址 |
| `/sapi/v1/account/status` | GET | 1 | 是 | 获取账户状态 |
| `/sapi/v1/account/apiTradingStatus` | GET | 1 | 是 | 获取API交易状态 |
| `/sapi/v1/asset/dust` | POST | 10 | 是 | 小额资产转换 |
| `/sapi/v1/asset/dust-btc` | POST | 1 | 是 | 获取小额资产转换BTC估值 |
| `/sapi/v1/asset/dividendRecord` | GET | 10 | 是 | 获取资产分红记录 |
| `/sapi/v1/asset/assetDetail` | GET | 1 | 是 | 获取资产详情 |
| `/sapi/v1/asset/tradeFee` | GET | 1 | 是 | 获取交易手续费率 |
| `/sapi/v1/asset/transfer` | POST | 1 | 是 | 用户万能转账 |
| `/sapi/v1/asset/transfer` | GET | 1 | 是 | 查询用户万能转账历史 |

## 👥 6. 子账户API (Sub-account API)

### 6.1 子账户管理端点

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/sapi/v1/sub-account/list` | GET | 1 | 是 | 查询子账户列表 |
| `/sapi/v1/sub-account/sub/transfer/history` | GET | 1 | 是 | 查询子账户转账历史 |
| `/sapi/v1/sub-account/futures/account` | GET | 1 | 是 | 查询子账户期货账户详情 |
| `/sapi/v1/sub-account/futures/accountSummary` | GET | 1 | 是 | 查询子账户期货账户汇总 |
| `/sapi/v1/sub-account/futures/positionRisk` | GET | 1 | 是 | 查询子账户期货持仓风险 |
| `/sapi/v1/sub-account/futures/transfer` | POST | 1 | 是 | 子账户期货转账 |
| `/sapi/v1/sub-account/margin/account` | GET | 1 | 是 | 查询子账户杠杆账户详情 |
| `/sapi/v1/sub-account/margin/accountSummary` | GET | 1 | 是 | 查询子账户杠杆账户汇总 |
| `/sapi/v1/sub-account/spotSummary` | GET | 1 | 是 | 查询子账户现货账户汇总 |
| `/sapi/v1/sub-account/status` | GET | 1 | 是 | 查询子账户状态 |
| `/sapi/v1/sub-account/margin/enable` | POST | 1 | 是 | 为子账户开通杠杆 |
| `/sapi/v1/sub-account/futures/enable` | POST | 1 | 是 | 为子账户开通期货 |
| `/sapi/v1/sub-account/transfer/subToSub` | POST | 1 | 是 | 子账户之间转账 |
| `/sapi/v1/sub-account/transfer/subToMaster` | POST | 1 | 是 | 子账户转账至主账户 |
| `/sapi/v1/sub-account/universalTransfer` | POST | 1 | 是 | 子账户万能转账 |

## 🌐 7. WebSocket数据流API

### 7.1 现货WebSocket流

| 流名称 | 描述 | 示例 |
|--------|------|------|
| `<symbol>@aggTrade` | 聚合交易流 | `btcusdt@aggTrade` |
| `<symbol>@trade` | 逐笔交易流 | `btcusdt@trade` |
| `<symbol>@kline_<interval>` | K线流 | `btcusdt@kline_1m` |
| `<symbol>@miniTicker` | 精简24小时统计 | `btcusdt@miniTicker` |
| `<symbol>@ticker` | 24小时完整统计 | `btcusdt@ticker` |
| `<symbol>@bookTicker` | 最优挂单信息流 | `btcusdt@bookTicker` |
| `<symbol>@depth<levels>` | 有限档深度信息流 | `btcusdt@depth5` |
| `<symbol>@depth` | 增量深度信息流 | `btcusdt@depth` |
| `!miniTicker@arr` | 全市场精简统计流 | `!miniTicker@arr` |
| `!ticker@arr` | 全市场统计流 | `!ticker@arr` |
| `!bookTicker` | 全市场最优挂单流 | `!bookTicker` |

### 7.2 期货WebSocket流

| 流名称 | 描述 | 示例 |
|--------|------|------|
| `<symbol>@aggTrade` | 聚合交易流 | `btcusdt@aggTrade` |
| `<symbol>@markPrice` | 标记价格流 | `btcusdt@markPrice` |
| `<symbol>@kline_<interval>` | K线流 | `btcusdt@kline_1m` |
| `<symbol>@continuousKline_<contractType>_<interval>` | 连续合约K线流 | `btcusdt@continuousKline_perpetual_1m` |
| `<symbol>@miniTicker` | 精简24小时统计 | `btcusdt@miniTicker` |
| `<symbol>@ticker` | 24小时完整统计 | `btcusdt@ticker` |
| `<symbol>@bookTicker` | 最优挂单信息流 | `btcusdt@bookTicker` |
| `<symbol>@forceOrder` | 强平订单流 | `btcusdt@forceOrder` |
| `<symbol>@depth<levels>@<speed>` | 有限档深度信息流 | `btcusdt@depth5@100ms` |

### 7.3 用户数据流

| 流类型 | 描述 | 获取方式 |
|--------|------|----------|
| 现货用户数据流 | 账户更新、订单更新、余额更新 | POST `/api/v3/userDataStream` |
| 期货用户数据流 | 账户更新、订单更新、持仓更新 | POST `/fapi/v1/listenKey` |
| 杠杆用户数据流 | 杠杆账户更新、订单更新 | POST `/sapi/v1/userDataStream` |

## 🔧 8. 其他重要API分类

### 8.1 保本赚币API (Simple Earn)

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/sapi/v1/simple-earn/flexible/list` | GET | 150 | 是 | 获取活期产品列表 |
| `/sapi/v1/simple-earn/locked/list` | GET | 150 | 是 | 获取定期产品列表 |
| `/sapi/v1/simple-earn/flexible/subscribe` | POST | 1 | 是 | 申购活期产品 |
| `/sapi/v1/simple-earn/locked/subscribe` | POST | 1 | 是 | 申购定期产品 |
| `/sapi/v1/simple-earn/flexible/redeem` | POST | 1 | 是 | 赎回活期产品 |
| `/sapi/v1/simple-earn/flexible/history/subscriptionRecord` | GET | 150 | 是 | 获取活期申购记录 |
| `/sapi/v1/simple-earn/locked/history/subscriptionRecord` | GET | 150 | 是 | 获取定期申购记录 |

### 8.2 矿池API (Mining)

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/sapi/v1/mining/pub/algoList` | GET | 1 | 是 | 获取算法列表 |
| `/sapi/v1/mining/pub/coinList` | GET | 1 | 是 | 获取币种列表 |
| `/sapi/v1/mining/worker/detail` | GET | 5 | 是 | 获取矿工详情 |
| `/sapi/v1/mining/worker/list` | GET | 5 | 是 | 获取矿工列表 |
| `/sapi/v1/mining/payment/list` | GET | 5 | 是 | 获取收益列表 |
| `/sapi/v1/mining/statistics/user/status` | GET | 5 | 是 | 获取用户状态 |
| `/sapi/v1/mining/statistics/user/list` | GET | 5 | 是 | 获取用户列表 |

### 8.3 法币API (Fiat)

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/sapi/v1/fiat/orders` | GET | 90000 | 是 | 获取法币订单历史 |
| `/sapi/v1/fiat/payments` | GET | 1 | 是 | 获取法币支付历史 |

### 8.4 C2C API

| API端点 | HTTP方法 | 权重 | 签名 | 描述 |
|---------|----------|------|------|------|
| `/sapi/v1/c2c/orderMatch/listUserOrderHistory` | GET | 1 | 是 | 获取C2C交易历史 |

## 📋 9. API使用限制和注意事项

### 9.1 权重限制
- 现货API: 每分钟6000权重
- 期货API: 每分钟2400权重
- 其他API: 根据具体端点而定

### 9.2 订单限制
- 现货: 每秒10个订单，每日200,000个订单
- 期货: 每秒300个订单，每日1,200,000个订单

### 9.3 IP限制
- 每个IP每分钟最多1200个请求
- 超过限制将被暂时封禁

### 9.4 签名要求
- 使用HMAC SHA256签名
- 支持RSA和Ed25519密钥
- 时间戳误差不能超过5000毫秒

## 🔐 10. 安全性和最佳实践

### 10.1 API密钥管理
- 定期轮换API密钥
- 使用IP白名单限制
- 设置适当的权限级别

### 10.2 错误处理
- 实现指数退避重试机制
- 监控API响应状态码
- 处理网络超时和连接错误

### 10.3 数据完整性
- 验证响应数据格式
- 实现数据校验机制
- 监控数据延迟和丢失

## 📊 总结

币安API提供了极其丰富的功能，涵盖：

1. 现货交易: 完整的现货交易功能
2. 期货交易: U本位和币本位合约
3. 期权交易: 欧式期权支持
4. 杠杆交易: 杠杆账户管理
5. 钱包功能: 充值提现和资产管理
6. 子账户: 企业级账户管理
7. WebSocket: 实时数据流
8. 增值服务: 理财、矿池、法币等

建议的实施优先级：
1. 首先实现现货和期货的市场数据API
2. 然后添加交易相关API
3. 最后集成钱包和其他增值服务API

这个全面的API覆盖确保您的数据收集模块能够访问币安平台的所有主要功能和数据。

---

# 币安API详细参数说明文档

## 📊 1. 现货交易API详细参数

### 1.1 市场数据端点参数详情

#### `GET /api/v3/exchangeInfo` - 交易所信息

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| symbols | ARRAY | 否 | 交易对数组 | 无 | ["BTCUSDT","BNBBTC"] | ["BTCUSDT","ETHUSDT"] |
| permissions | ARRAY | 否 | 权限过滤 | 无 | ["SPOT","MARGIN","LEVERAGED"] | ["SPOT"] |

响应字段说明:
```json
{
  "timezone": "UTC",
  "serverTime": 1565246363776,
  "rateLimits": [
    {
      "rateLimitType": "REQUEST_WEIGHT",
      "interval": "MINUTE",
      "intervalNum": 1,
      "limit": 6000
    }
  ],
  "exchangeFilters": [],
  "symbols": [
    {
      "symbol": "ETHBTC",
      "status": "TRADING",
      "baseAsset": "ETH",
      "baseAssetPrecision": 8,
      "quoteAsset": "BTC",
      "quotePrecision": 8,
      "quoteAssetPrecision": 8,
      "baseCommissionPrecision": 8,
      "quoteCommissionPrecision": 8,
      "orderTypes": ["LIMIT", "LIMIT_MAKER", "MARKET", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"],
      "icebergAllowed": true,
      "ocoAllowed": true,
      "quoteOrderQtyMarketAllowed": true,
      "allowTrailingStop": false,
      "cancelReplaceAllowed": true,
      "isSpotTradingAllowed": true,
      "isMarginTradingAllowed": true,
      "filters": [...]
    }
  ]
}
```

#### `GET /api/v3/depth` - 订单簿深度

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| limit | INT | 否 | 返回的档位数量 | 100 | 5, 10, 20, 50, 100, 500, 1000, 5000 | 100 |

权重消耗:
- limit=5,10,20,50,100: 权重=1
- limit=500: 权重=5
- limit=1000: 权重=10
- limit=5000: 权重=50

#### `GET /api/v3/trades` - 近期成交

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| limit | INT | 否 | 返回的成交数量 | 500 | 1-1000 | 500 |

#### `GET /api/v3/historicalTrades` - 历史成交

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| limit | INT | 否 | 返回的成交数量 | 500 | 1-1000 | 500 |
| fromId | LONG | 否 | 从哪个成交ID开始返回 | 无 | 有效的成交ID | 28457 |

#### `GET /api/v3/aggTrades` - 聚合成交

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| fromId | LONG | 否 | 从哪个聚合成交ID开始返回 | 无 | 有效的聚合成交ID | 28457 |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的聚合成交数量 | 500 | 1-1000 | 500 |

#### `GET /api/v3/klines` - K线数据

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| interval | ENUM | 是 | K线间隔 | 无 | 1s,1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| timeZone | STRING | 否 | 时区 | 0 (UTC) | 时区偏移或时区名称 | +08:00 |
| limit | INT | 否 | 返回的K线数量 | 500 | 1-1000 | 500 |

K线数据格式:
```json
[
  [
    1499040000000,      // 开盘时间
    "0.01634790",       // 开盘价
    "0.80000000",       // 最高价
    "0.01575800",       // 最低价
    "0.01577100",       // 收盘价
    "148976.11427815",  // 成交量
    1499644799999,      // 收盘时间
    "2434.19055334",    // 成交额
    308,                // 成交笔数
    "1756.87402397",    // 主动买入成交量
    "28.46694368",      // 主动买入成交额
    "17928899.62484339" // 忽略此参数
  ]
]
```

#### `GET /api/v3/avgPrice` - 平均价格

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |

#### `GET /api/v3/ticker/24hr` - 24小时价格统计

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| symbols | ARRAY | 否 | 交易对数组 | 无 | ["BTCUSDT","BNBBTC"] | ["BTCUSDT","ETHUSDT"] |
| type | ENUM | 否 | 统计类型 | FULL | FULL, MINI | FULL |

权重消耗:
- 单个symbol: 权重=2
- 无symbol参数(所有交易对): 权重=80
- symbols数组: 权重=symbols数量×2

#### `GET /api/v3/ticker/tradingDay` - 交易日价格统计

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| symbols | ARRAY | 否 | 交易对数组 | 无 | ["BTCUSDT","BNBBTC"] | ["BTCUSDT","ETHUSDT"] |
| timeZone | STRING | 否 | 时区 | 0 (UTC) | 时区偏移或时区名称 | +08:00 |
| type | ENUM | 否 | 统计类型 | FULL | FULL, MINI | FULL |

#### `GET /api/v3/ticker/price` - 最新价格

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| symbols | ARRAY | 否 | 交易对数组 | 无 | ["BTCUSDT","BNBBTC"] | ["BTCUSDT","ETHUSDT"] |

#### `GET /api/v3/ticker/bookTicker` - 最优挂单价格

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| symbols | ARRAY | 否 | 交易对数组 | 无 | ["BTCUSDT","BNBBTC"] | ["BTCUSDT","ETHUSDT"] |

### 1.2 账户和交易端点参数详情

#### `POST /api/v3/order` - 下单

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| side | ENUM | 是 | 买卖方向 | 无 | BUY, SELL | BUY |
| type | ENUM | 是 | 订单类型 | 无 | LIMIT, MARKET, STOP_LOSS, STOP_LOSS_LIMIT, TAKE_PROFIT, TAKE_PROFIT_LIMIT, LIMIT_MAKER | LIMIT |
| timeInForce | ENUM | 否 | 有效时间 | 无 | GTC, IOC, FOK | GTC |
| quantity | DECIMAL | 否 | 数量 | 无 | 大于0的数字 | 1.00000000 |
| quoteOrderQty | DECIMAL | 否 | 报价数量 | 无 | 大于0的数字 | 10.00000000 |
| price | DECIMAL | 否 | 价格 | 无 | 大于0的数字 | 0.1 |
| newClientOrderId | STRING | 否 | 客户端订单ID | 无 | 字符串，最大36字符 | my_order_id_1 |
| strategyId | INT | 否 | 策略ID | 无 | 整数 | 1 |
| strategyType | INT | 否 | 策略类型 | 无 | 整数，1000000以下 | 1000000 |
| stopPrice | DECIMAL | 否 | 止损价格 | 无 | 大于0的数字 | 0.1 |
| trailingDelta | LONG | 否 | 追踪止损 | 无 | 整数 | 10 |
| icebergQty | DECIMAL | 否 | 冰山数量 | 无 | 大于0的数字 | 0.1 |
| newOrderRespType | ENUM | 否 | 响应类型 | ACK | ACK, RESULT, FULL | RESULT |
| selfTradePreventionMode | ENUM | 否 | 自成交防护 | EXPIRE_MAKER | EXPIRE_TAKER, EXPIRE_MAKER, EXPIRE_BOTH, NONE | EXPIRE_MAKER |
| goodTillDate | LONG | 否 | 有效期 | 无 | Unix时间戳(毫秒) | 1693207680000 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

订单类型参数要求:

| 订单类型 | 必需参数 | 可选参数 |
|----------|----------|----------|
| LIMIT | timeInForce, quantity, price | icebergQty |
| MARKET | quantity 或 quoteOrderQty | 无 |
| STOP_LOSS | quantity, stopPrice | trailingDelta |
| STOP_LOSS_LIMIT | timeInForce, quantity, price, stopPrice | icebergQty, trailingDelta |
| TAKE_PROFIT | quantity, stopPrice | trailingDelta |
| TAKE_PROFIT_LIMIT | timeInForce, quantity, price, stopPrice | icebergQty, trailingDelta |
| LIMIT_MAKER | quantity, price | icebergQty |

#### `DELETE /api/v3/order` - 撤销订单

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| orderId | LONG | 否 | 订单ID | 无 | 有效的订单ID | 28 |
| origClientOrderId | STRING | 否 | 原始客户端订单ID | 无 | 字符串 | myOrder1 |
| newClientOrderId | STRING | 否 | 新的客户端订单ID | 无 | 字符串，最大36字符 | cancelMyOrder1 |
| cancelRestrictions | ENUM | 否 | 撤销限制 | 无 | ONLY_NEW, ONLY_PARTIALLY_FILLED | ONLY_NEW |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /api/v3/order` - 查询订单

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| orderId | LONG | 否 | 订单ID | 无 | 有效的订单ID | 28 |
| origClientOrderId | STRING | 否 | 原始客户端订单ID | 无 | 字符串 | myOrder1 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /api/v3/openOrders` - 查询当前挂单

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /api/v3/allOrders` - 查询所有订单

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| orderId | LONG | 否 | 订单ID | 无 | 有效的订单ID | 28 |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的订单数量 | 500 | 1-1000 | 500 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /api/v3/order/oco` - OCO下单

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| listClientOrderId | STRING | 否 | 订单列表客户端ID | 无 | 字符串，最大36字符 | C3wyj4WVEktd7u9aVBRXcN |
| side | ENUM | 是 | 买卖方向 | 无 | BUY, SELL | SELL |
| quantity | DECIMAL | 是 | 数量 | 无 | 大于0的数字 | 1 |
| limitClientOrderId | STRING | 否 | 限价单客户端ID | 无 | 字符串，最大36字符 | pO9ufTiFGg3nw2fOdgeOXa |
| price | DECIMAL | 是 | 限价单价格 | 无 | 大于0的数字 | 2 |
| limitIcebergQty | DECIMAL | 否 | 限价单冰山数量 | 无 | 大于0的数字 | 0.1 |
| stopClientOrderId | STRING | 否 | 止损单客户端ID | 无 | 字符串，最大36字符 | TXOvglzXuaubXAaENpaRCB |
| stopPrice | DECIMAL | 是 | 止损价格 | 无 | 大于0的数字 | 0.9 |
| stopLimitPrice | DECIMAL | 否 | 止损限价 | 无 | 大于0的数字 | 0.8 |
| stopIcebergQty | DECIMAL | 否 | 止损单冰山数量 | 无 | 大于0的数字 | 0.1 |
| stopLimitTimeInForce | ENUM | 否 | 止损限价单有效时间 | 无 | GTC, FOK, IOC | GTC |
| newOrderRespType | ENUM | 否 | 响应类型 | ACK | ACK, RESULT, FULL | RESULT |
| selfTradePreventionMode | ENUM | 否 | 自成交防护 | EXPIRE_MAKER | EXPIRE_TAKER, EXPIRE_MAKER, EXPIRE_BOTH, NONE | EXPIRE_MAKER |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /api/v3/account` - 查询账户信息

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| omitZeroBalances | BOOLEAN | 否 | 忽略零余额 | false | true, false | true |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /api/v3/myTrades` - 查询成交历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| orderId | LONG | 否 | 订单ID | 无 | 有效的订单ID | 28 |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| fromId | LONG | 否 | 从哪个成交ID开始返回 | 无 | 有效的成交ID | 28457 |
| limit | INT | 否 | 返回的成交数量 | 500 | 1-1000 | 500 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

## 📈 2. 期货交易API详细参数

### 2.1 U本位合约市场数据端点

#### `GET /fapi/v1/exchangeInfo` - 交易所信息

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| symbols | ARRAY | 否 | 交易对数组 | 无 | ["BTCUSDT","ETHUSDT"] | ["BTCUSDT","ETHUSDT"] |

#### `GET /fapi/v1/depth` - 订单簿深度

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| limit | INT | 否 | 返回的档位数量 | 500 | 5, 10, 20, 50, 100, 500, 1000 | 100 |

#### `GET /fapi/v1/klines` - K线数据

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| interval | ENUM | 是 | K线间隔 | 无 | 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的K线数量 | 500 | 1-1500 | 500 |

#### `GET /fapi/v1/continuousKlines` - 连续合约K线

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| pair | STRING | 是 | 交易对 | 无 | 有效的交易对 | BTCUSDT |
| contractType | ENUM | 是 | 合约类型 | 无 | PERPETUAL, CURRENT_MONTH, NEXT_MONTH, CURRENT_QUARTER, NEXT_QUARTER | PERPETUAL |
| interval | ENUM | 是 | K线间隔 | 无 | 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的K线数量 | 500 | 1-1500 | 500 |

#### `GET /fapi/v1/indexPriceKlines` - 指数价格K线

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| pair | STRING | 是 | 交易对 | 无 | 有效的交易对 | BTCUSDT |
| interval | ENUM | 是 | K线间隔 | 无 | 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的K线数量 | 500 | 1-1500 | 500 |

#### `GET /fapi/v1/markPriceKlines` - 标记价格K线

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| interval | ENUM | 是 | K线间隔 | 无 | 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的K线数量 | 500 | 1-1500 | 500 |

#### `GET /fapi/v1/premiumIndexKlines` - 溢价指数K线

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| interval | ENUM | 是 | K线间隔 | 无 | 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的K线数量 | 500 | 1-1500 | 500 |

#### `GET /fapi/v1/premiumIndex` - 标记价格和资金费率

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |

#### `GET /fapi/v1/fundingRate` - 资金费率历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的数量 | 100 | 1-1000 | 100 |

#### `GET /fapi/v1/ticker/24hr` - 24小时价格统计

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| pair | STRING | 否 | 交易对 | 无 | 有效的交易对 | BTCUSDT |

#### `GET /fapi/v1/openInterest` - 持仓量

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |

### 2.2 期货高级数据端点参数

#### `GET /futures/data/openInterestHist` - 持仓量历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| period | ENUM | 是 | 统计周期 | 无 | 5m,15m,30m,1h,2h,4h,6h,12h,1d | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的数量 | 30 | 1-500 | 30 |

#### `GET /futures/data/topLongShortAccountRatio` - 大户账户数多空比

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| period | ENUM | 是 | 统计周期 | 无 | 5m,15m,30m,1h,2h,4h,6h,12h,1d | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的数量 | 30 | 1-500 | 30 |

#### `GET /futures/data/topLongShortPositionRatio` - 大户持仓量多空比

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| period | ENUM | 是 | 统计周期 | 无 | 5m,15m,30m,1h,2h,4h,6h,12h,1d | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的数量 | 30 | 1-500 | 30 |

#### `GET /futures/data/globalLongShortAccountRatio` - 多空账户数比例

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| period | ENUM | 是 | 统计周期 | 无 | 5m,15m,30m,1h,2h,4h,6h,12h,1d | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的数量 | 30 | 1-500 | 30 |

#### `GET /futures/data/takerlongshortRatio` - 合约主动买卖量

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| period | ENUM | 是 | 统计周期 | 无 | 5m,15m,30m,1h,2h,4h,6h,12h,1d | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的数量 | 30 | 1-500 | 30 |

### 2.3 期货交易端点参数

#### `POST /fapi/v1/order` - 下单

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| side | ENUM | 是 | 买卖方向 | 无 | BUY, SELL | BUY |
| positionSide | ENUM | 否 | 持仓方向 | BOTH | BOTH, LONG, SHORT | LONG |
| type | ENUM | 是 | 订单类型 | 无 | LIMIT, MARKET, STOP, TAKE_PROFIT, STOP_MARKET, TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET | LIMIT |
| timeInForce | ENUM | 否 | 有效时间 | 无 | GTC, IOC, FOK, GTX, GTD | GTC |
| quantity | DECIMAL | 否 | 数量 | 无 | 大于0的数字 | 1.00 |
| reduceOnly | STRING | 否 | 只减仓 | false | true, false | false |
| price | DECIMAL | 否 | 价格 | 无 | 大于0的数字 | 9000 |
| newClientOrderId | STRING | 否 | 客户端订单ID | 无 | 字符串，最大36字符 | my_order_id_1 |
| strategyId | LONG | 否 | 策略ID | 无 | 整数 | 1 |
| strategyType | LONG | 否 | 策略类型 | 无 | 整数，1000000以下 | 1000000 |
| stopPrice | DECIMAL | 否 | 止损价格 | 无 | 大于0的数字 | 9100 |
| closePosition | STRING | 否 | 平仓 | false | true, false | false |
| activationPrice | DECIMAL | 否 | 激活价格 | 无 | 大于0的数字 | 9020 |
| callbackRate | DECIMAL | 否 | 回调比率 | 无 | 0.1-5 | 0.1 |
| workingType | ENUM | 否 | 条件价格触发类型 | CONTRACT_PRICE | MARK_PRICE, CONTRACT_PRICE | CONTRACT_PRICE |
| priceProtect | STRING | 否 | 价格保护 | false | true, false | false |
| newOrderRespType | ENUM | 否 | 响应类型 | ACK | ACK, RESULT | RESULT |
| priceMatch | ENUM | 否 | 价格匹配模式 | NONE | NONE, OPPONENT, OPPONENT_5, OPPONENT_10, OPPONENT_20, QUEUE, QUEUE_5, QUEUE_10, QUEUE_20 | NONE |
| selfTradePreventionMode | ENUM | 否 | 自成交防护 | NONE | NONE, EXPIRE_TAKER, EXPIRE_MAKER, EXPIRE_BOTH | NONE |
| goodTillDate | LONG | 否 | 有效期 | 无 | Unix时间戳(毫秒) | 1693207680000 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /fapi/v2/account` - 查询账户信息

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /fapi/v1/positionRisk` - 查询持仓风险

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /fapi/v1/leverage` - 调整杠杆

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| leverage | INT | 是 | 杠杆倍数 | 无 | 1-125 | 10 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /fapi/v1/marginType` - 变更保证金模式

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| marginType | ENUM | 是 | 保证金模式 | 无 | ISOLATED, CROSSED | ISOLATED |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

## 💰 3. 杠杆交易API详细参数

### 3.1 杠杆账户端点参数

#### `GET /sapi/v1/margin/account` - 查询杠杆账户详情

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/margin/transfer` - 杠杆账户转账

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| asset | STRING | 是 | 资产名称 | 无 | 有效的资产符号 | BTC |
| amount | DECIMAL | 是 | 转账数量 | 无 | 大于0的数字 | 1.01 |
| type | INT | 是 | 转账类型 | 无 | 1(现货转杠杆), 2(杠杆转现货) | 1 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/margin/loan` - 杠杆账户借贷

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| asset | STRING | 是 | 资产名称 | 无 | 有效的资产符号 | BTC |
| isIsolated | STRING | 否 | 是否逐仓 | FALSE | TRUE, FALSE | FALSE |
| symbol | STRING | 否 | 逐仓交易对 | 无 | 有效的交易对符号 | BTCUSDT |
| amount | DECIMAL | 是 | 借贷数量 | 无 | 大于0的数字 | 1.01 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/margin/repay` - 杠杆账户还贷

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| asset | STRING | 是 | 资产名称 | 无 | 有效的资产符号 | BTC |
| isIsolated | STRING | 否 | 是否逐仓 | FALSE | TRUE, FALSE | FALSE |
| symbol | STRING | 否 | 逐仓交易对 | 无 | 有效的交易对符号 | BTCUSDT |
| amount | DECIMAL | 是 | 还贷数量 | 无 | 大于0的数字 | 1.01 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/margin/order` - 杠杆账户下单

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| isIsolated | STRING | 否 | 是否逐仓 | FALSE | TRUE, FALSE | FALSE |
| side | ENUM | 是 | 买卖方向 | 无 | BUY, SELL | BUY |
| type | ENUM | 是 | 订单类型 | 无 | LIMIT, MARKET, STOP_LOSS_LIMIT, TAKE_PROFIT_LIMIT | LIMIT |
| quantity | DECIMAL | 否 | 数量 | 无 | 大于0的数字 | 1.00000000 |
| quoteOrderQty | DECIMAL | 否 | 报价数量 | 无 | 大于0的数字 | 10.00000000 |
| price | DECIMAL | 否 | 价格 | 无 | 大于0的数字 | 0.1 |
| stopPrice | DECIMAL | 否 | 止损价格 | 无 | 大于0的数字 | 0.1 |
| newClientOrderId | STRING | 否 | 客户端订单ID | 无 | 字符串，最大36字符 | my_order_id_1 |
| icebergQty | DECIMAL | 否 | 冰山数量 | 无 | 大于0的数字 | 0.1 |
| newOrderRespType | ENUM | 否 | 响应类型 | ACK | ACK, RESULT, FULL | RESULT |
| sideEffectType | ENUM | 否 | 副作用类型 | NO_SIDE_EFFECT | NO_SIDE_EFFECT, MARGIN_BUY, AUTO_REPAY | NO_SIDE_EFFECT |
| timeInForce | ENUM | 否 | 有效时间 | 无 | GTC, IOC, FOK | GTC |
| autoRepayAtCancel | BOOLEAN | 否 | 撤单时自动还贷 | false | true, false | false |
| selfTradePreventionMode | ENUM | 否 | 自成交防护 | EXPIRE_MAKER | EXPIRE_TAKER, EXPIRE_MAKER, EXPIRE_BOTH, NONE | EXPIRE_MAKER |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

## 💼 4. 钱包API详细参数

### 4.1 钱包端点参数

#### `GET /sapi/v1/capital/config/getall` - 获取所有币种信息

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/account/snapshot` - 获取账户快照

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| type | STRING | 是 | 账户类型 | 无 | SPOT, MARGIN, FUTURES | SPOT |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的数量 | 5 | 5-30 | 10 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/capital/withdraw/apply` - 提现

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| coin | STRING | 是 | 币种名称 | 无 | 有效的币种符号 | BTC |
| withdrawOrderId | STRING | 否 | 客户端提现ID | 无 | 字符串 | my_withdraw_001 |
| network | STRING | 否 | 网络 | 无 | 有效的网络名称 | ETH |
| address | STRING | 是 | 提现地址 | 无 | 有效的地址 | 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa |
| addressTag | STRING | 否 | 地址标签 | 无 | 字符串 | 12345 |
| amount | DECIMAL | 是 | 提现数量 | 无 | 大于0的数字 | 1.01 |
| transactionFeeFlag | BOOLEAN | 否 | 手续费扣除方式 | false | true, false | false |
| name | STRING | 否 | 地址名称 | 无 | 字符串 | address_name |
| walletType | INT | 否 | 钱包类型 | 0 | 0(现货钱包), 1(资金钱包) | 0 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/capital/deposit/hisrec` - 获取充值历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| coin | STRING | 否 | 币种名称 | 无 | 有效的币种符号 | BTC |
| status | INT | 否 | 状态 | 无 | 0(待确认), 6(已确认), 1(已到账) | 1 |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| offset | INT | 否 | 偏移量 | 0 | 0以上的整数 | 0 |
| limit | INT | 否 | 返回的数量 | 1000 | 1-1000 | 100 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/capital/withdraw/history` - 获取提现历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| coin | STRING | 否 | 币种名称 | 无 | 有效的币种符号 | BTC |
| withdrawOrderId | STRING | 否 | 客户端提现ID | 无 | 字符串 | my_withdraw_001 |
| status | INT | 否 | 状态 | 无 | 0(邮件确认), 1(取消), 2(等待确认), 3(拒绝), 4(处理中), 5(失败), 6(完成) | 6 |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| offset | INT | 否 | 偏移量 | 0 | 0以上的整数 | 0 |
| limit | INT | 否 | 返回的数量 | 1000 | 1-1000 | 100 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/capital/deposit/address` - 获取充值地址

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| coin | STRING | 是 | 币种名称 | 无 | 有效的币种符号 | BTC |
| network | STRING | 否 | 网络 | 无 | 有效的网络名称 | BTC |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/asset/dust` - 小额资产转换

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| asset | ARRAY | 是 | 资产数组 | 无 | 有效的资产符号数组 | ["ETH","LTC","TRX"] |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/asset/tradeFee` - 获取交易手续费率

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 交易对名称 | 无 | 有效的交易对符号 | BTCUSDT |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/asset/transfer` - 用户万能转账

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| type | ENUM | 是 | 转账类型 | 无 | MAIN_C2C, MAIN_UMFUTURE, MAIN_CMFUTURE, MAIN_MARGIN, MAIN_MINING, C2C_MAIN, C2C_UMFUTURE, C2C_MINING, C2C_MARGIN, UMFUTURE_MAIN, UMFUTURE_C2C, UMFUTURE_MARGIN, CMFUTURE_MAIN, CMFUTURE_MARGIN, MARGIN_MAIN, MARGIN_UMFUTURE, MARGIN_CMFUTURE, MARGIN_C2C, MINING_MAIN, MINING_UMFUTURE, MINING_C2C, MARGIN_CROSS_MARGIN, ISOLATEDMARGIN_MARGIN, ISOLATEDMARGIN_ISOLATEDMARGIN | MAIN_UMFUTURE |
| asset | STRING | 是 | 资产名称 | 无 | 有效的资产符号 | BTC |
| amount | DECIMAL | 是 | 转账数量 | 无 | 大于0的数字 | 1.01 |
| fromSymbol | STRING | 否 | 来源逐仓交易对 | 无 | 有效的交易对符号 | BTCUSDT |
| toSymbol | STRING | 否 | 目标逐仓交易对 | 无 | 有效的交易对符号 | BNBUSDT |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

## 👥 5. 子账户API详细参数

### 5.1 子账户管理端点参数

#### `GET /sapi/v1/sub-account/list` - 查询子账户列表

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| email | STRING | 否 | 子账户邮箱 | 无 | 有效的邮箱地址 | testsub@gmail.com |
| isFreeze | STRING | 否 | 是否冻结 | 无 | true, false | true |
| page | INT | 否 | 页码 | 1 | 1以上的整数 | 1 |
| limit | INT | 否 | 每页数量 | 1 | 1-200 | 10 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/sub-account/sub/transfer/history` - 查询子账户转账历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| fromEmail | STRING | 否 | 发送方邮箱 | 无 | 有效的邮箱地址 | from@test.com |
| toEmail | STRING | 否 | 接收方邮箱 | 无 | 有效的邮箱地址 | to@test.com |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| page | INT | 否 | 页码 | 1 | 1以上的整数 | 1 |
| limit | INT | 否 | 每页数量 | 500 | 1-500 | 100 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/sub-account/futures/account` - 查询子账户期货账户详情

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| email | STRING | 是 | 子账户邮箱 | 无 | 有效的邮箱地址 | testsub@gmail.com |
| futuresType | INT | 否 | 期货类型 | 1 | 1(USDT-M期货), 2(COIN-M期货) | 1 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/sub-account/futures/transfer` - 子账户期货转账

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| email | STRING | 是 | 子账户邮箱 | 无 | 有效的邮箱地址 | testsub@gmail.com |
| asset | STRING | 是 | 资产名称 | 无 | 有效的资产符号 | USDT |
| amount | DECIMAL | 是 | 转账数量 | 无 | 大于0的数字 | 1.01 |
| type | INT | 是 | 转账类型 | 无 | 1(现货转期货), 2(期货转现货), 3(现货转币本位期货), 4(币本位期货转现货) | 1 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/sub-account/universalTransfer` - 子账户万能转账

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| fromEmail | STRING | 否 | 发送方邮箱 | 无 | 有效的邮箱地址 | from@test.com |
| toEmail | STRING | 否 | 接收方邮箱 | 无 | 有效的邮箱地址 | to@test.com |
| fromAccountType | ENUM | 是 | 发送方账户类型 | 无 | SPOT, USDT_FUTURE, COIN_FUTURE, MARGIN, ISOLATED_MARGIN | SPOT |
| toAccountType | ENUM | 是 | 接收方账户类型 | 无 | SPOT, USDT_FUTURE, COIN_FUTURE, MARGIN, ISOLATED_MARGIN | USDT_FUTURE |
| clientTranId | STRING | 否 | 客户端转账ID | 无 | 字符串 | 118263407119 |
| symbol | STRING | 否 | 逐仓交易对 | 无 | 有效的交易对符号 | BTCUSDT |
| asset | STRING | 是 | 资产名称 | 无 | 有效的资产符号 | USDT |
| amount | DECIMAL | 是 | 转账数量 | 无 | 大于0的数字 | 1.01 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

## 🎯 6. 期权API详细参数

### 6.1 期权市场数据端点参数

#### `GET /eapi/v1/exchangeInfo` - 交易所信息

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| 无参数 | - | - | - | - | - | - |

#### `GET /eapi/v1/depth` - 订单簿深度

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 期权合约名称 | 无 | 有效的期权合约符号 | BTC-200730-9000-C |
| limit | INT | 否 | 返回的档位数量 | 100 | 10, 20, 50, 100 | 100 |

#### `GET /eapi/v1/klines` - K线数据

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 期权合约名称 | 无 | 有效的期权合约符号 | BTC-200730-9000-C |
| interval | ENUM | 是 | K线间隔 | 无 | 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M | 1h |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的K线数量 | 500 | 1-1500 | 500 |

#### `GET /eapi/v1/mark` - 标记价格

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 期权合约名称 | 无 | 有效的期权合约符号 | BTC-200730-9000-C |

#### `GET /eapi/v1/ticker` - 24小时价格统计

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 期权合约名称 | 无 | 有效的期权合约符号 | BTC-200730-9000-C |

#### `GET /eapi/v1/index` - 指数价格

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| underlying | STRING | 是 | 标的资产 | 无 | 有效的标的资产符号 | BTCUSDT |

#### `GET /eapi/v1/exerciseHistory` - 行权历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| underlying | STRING | 是 | 标的资产 | 无 | 有效的标的资产符号 | BTCUSDT |
| startTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1499040000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1499644800000 |
| limit | INT | 否 | 返回的数量 | 100 | 1-100 | 100 |

#### `GET /eapi/v1/openInterest` - 持仓量

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| underlyingAsset | STRING | 是 | 标的资产 | 无 | 有效的标的资产符号 | BTC |
| expiration | STRING | 否 | 到期日 | 无 | YYYYMMDD格式 | 20200730 |

### 6.2 期权交易端点参数

#### `POST /eapi/v1/order` - 下单

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 是 | 期权合约名称 | 无 | 有效的期权合约符号 | BTC-200730-9000-C |
| side | ENUM | 是 | 买卖方向 | 无 | BUY, SELL | BUY |
| type | ENUM | 是 | 订单类型 | 无 | LIMIT, MARKET | LIMIT |
| quantity | DECIMAL | 是 | 数量 | 无 | 大于0的数字 | 1 |
| price | DECIMAL | 否 | 价格 | 无 | 大于0的数字 | 100 |
| timeInForce | ENUM | 否 | 有效时间 | 无 | GTC, IOC, FOK | GTC |
| reduceOnly | BOOLEAN | 否 | 只减仓 | false | true, false | false |
| postOnly | BOOLEAN | 否 | 只做maker | false | true, false | false |
| newOrderRespType | ENUM | 否 | 响应类型 | ACK | ACK, RESULT | RESULT |
| clientOrderId | STRING | 否 | 客户端订单ID | 无 | 字符串，最大36字符 | my_order_id_1 |
| isMmp | BOOLEAN | 否 | 是否MMP订单 | false | true, false | false |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /eapi/v1/account` - 查询账户信息

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /eapi/v1/position` - 查询持仓信息

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| symbol | STRING | 否 | 期权合约名称 | 无 | 有效的期权合约符号 | BTC-200730-9000-C |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

## 🌐 7. WebSocket数据流详细参数

### 7.1 现货WebSocket流参数

#### 连接信息
- 基础URL: `wss://stream.binance.com:9443/ws/`
- 组合流URL: `wss://stream.binance.com:9443/stream?streams=`

#### 流订阅格式

| 流类型 | 格式 | 参数说明 | 示例 |
|--------|------|----------|------|
| 聚合交易流 | `<symbol>@aggTrade` | symbol: 小写交易对 | `btcusdt@aggTrade` |
| 逐笔交易流 | `<symbol>@trade` | symbol: 小写交易对 | `btcusdt@trade` |
| K线流 | `<symbol>@kline_<interval>` | symbol: 小写交易对<br>interval: K线间隔 | `btcusdt@kline_1m` |
| 精简24小时统计 | `<symbol>@miniTicker` | symbol: 小写交易对 | `btcusdt@miniTicker` |
| 24小时完整统计 | `<symbol>@ticker` | symbol: 小写交易对 | `btcusdt@ticker` |
| 最优挂单信息流 | `<symbol>@bookTicker` | symbol: 小写交易对 | `btcusdt@bookTicker` |
| 有限档深度信息流 | `<symbol>@depth<levels>[@<speed>]` | symbol: 小写交易对<br>levels: 5,10,20<br>speed: 1000ms,100ms | `btcusdt@depth5@100ms` |
| 增量深度信息流 | `<symbol>@depth[@<speed>]` | symbol: 小写交易对<br>speed: 1000ms,100ms | `btcusdt@depth@100ms` |

#### K线间隔枚举值
```
1s, 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
```

#### 组合流示例
```
wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/bnbusdt@ticker/ethusdt@ticker
```

### 7.2 期货WebSocket流参数

#### 连接信息
- U本位合约: `wss://fstream.binance.com/ws/`
- 币本位合约: `wss://dstream.binance.com/ws/`

#### 流订阅格式

| 流类型 | 格式 | 参数说明 | 示例 |
|--------|------|----------|------|
| 聚合交易流 | `<symbol>@aggTrade` | symbol: 小写交易对 | `btcusdt@aggTrade` |
| 标记价格流 | `<symbol>@markPrice[@<speed>]` | symbol: 小写交易对<br>speed: 1s,3s | `btcusdt@markPrice@1s` |
| 全市场标记价格流 | `!markPrice@arr[@<speed>]` | speed: 1s,3s | `!markPrice@arr@1s` |
| K线流 | `<symbol>@kline_<interval>` | symbol: 小写交易对<br>interval: K线间隔 | `btcusdt@kline_1m` |
| 连续合约K线流 | `<symbol>@continuousKline_<contractType>_<interval>` | symbol: 小写交易对<br>contractType: perpetual,current_month,next_month,current_quarter,next_quarter<br>interval: K线间隔 | `btcusdt@continuousKline_perpetual_1m` |
| 精简24小时统计 | `<symbol>@miniTicker` | symbol: 小写交易对 | `btcusdt@miniTicker` |
| 24小时完整统计 | `<symbol>@ticker` | symbol: 小写交易对 | `btcusdt@ticker` |
| 最优挂单信息流 | `<symbol>@bookTicker` | symbol: 小写交易对 | `btcusdt@bookTicker` |
| 强平订单流 | `<symbol>@forceOrder` | symbol: 小写交易对 | `btcusdt@forceOrder` |
| 有限档深度信息流 | `<symbol>@depth<levels>[@<speed>]` | symbol: 小写交易对<br>levels: 5,10,20<br>speed: 250ms,500ms,100ms | `btcusdt@depth5@100ms` |
| 增量深度信息流 | `<symbol>@depth[@<speed>]` | symbol: 小写交易对<br>speed: 250ms,500ms,100ms | `btcusdt@depth@100ms` |

### 7.3 用户数据流参数

#### 现货用户数据流

获取listenKey:
```http
POST /api/v3/userDataStream
```

延长listenKey:
```http
PUT /api/v3/userDataStream
```
| 参数名 | 类型 | 必需 | 描述 |
|--------|------|------|------|
| listenKey | STRING | 是 | 用户数据流密钥 |

关闭用户数据流:
```http
DELETE /api/v3/userDataStream
```
| 参数名 | 类型 | 必需 | 描述 |
|--------|------|------|------|
| listenKey | STRING | 是 | 用户数据流密钥 |

#### 期货用户数据流

获取listenKey:
```http
POST /fapi/v1/listenKey
```

延长listenKey:
```http
PUT /fapi/v1/listenKey
```

关闭用户数据流:
```http
DELETE /fapi/v1/listenKey
```

#### 杠杆用户数据流

获取listenKey:
```http
POST /sapi/v1/userDataStream
```
| 参数名 | 类型 | 必需 | 描述 |
|--------|------|------|------|
| isIsolated | STRING | 否 | 是否逐仓 |
| symbol | STRING | 否 | 逐仓交易对 |

## 🔧 8. 其他重要API详细参数

### 8.1 保本赚币API (Simple Earn)

#### `GET /sapi/v1/simple-earn/flexible/list` - 获取活期产品列表

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| asset | STRING | 否 | 资产名称 | 无 | 有效的资产符号 | BTC |
| current | LONG | 否 | 当前页 | 1 | 1以上的整数 | 1 |
| size | LONG | 否 | 每页数量 | 10 | 1-100 | 10 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/simple-earn/locked/list` - 获取定期产品列表

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| asset | STRING | 否 | 资产名称 | 无 | 有效的资产符号 | BTC |
| current | LONG | 否 | 当前页 | 1 | 1以上的整数 | 1 |
| size | LONG | 否 | 每页数量 | 10 | 1-100 | 10 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/simple-earn/flexible/subscribe` - 申购活期产品

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| productId | STRING | 是 | 产品ID | 无 | 有效的产品ID | TKO001 |
| amount | DECIMAL | 是 | 申购数量 | 无 | 大于0的数字 | 1.01 |
| autoSubscribe | BOOLEAN | 否 | 自动申购 | true | true, false | true |
| sourceAccount | ENUM | 否 | 资金来源 | SPOT | SPOT, FUND, ALL | SPOT |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/simple-earn/locked/subscribe` - 申购定期产品

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| projectId | STRING | 是 | 项目ID | 无 | 有效的项目ID | Axs*90 |
| amount | DECIMAL | 是 | 申购数量 | 无 | 大于0的数字 | 1.01 |
| autoSubscribe | BOOLEAN | 否 | 自动申购 | true | true, false | true |
| sourceAccount | ENUM | 否 | 资金来源 | SPOT | SPOT, FUND, ALL | SPOT |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `POST /sapi/v1/simple-earn/flexible/redeem` - 赎回活期产品

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| productId | STRING | 是 | 产品ID | 无 | 有效的产品ID | TKO001 |
| redeemAll | BOOLEAN | 否 | 全部赎回 | false | true, false | false |
| amount | DECIMAL | 否 | 赎回数量 | 无 | 大于0的数字 | 1.01 |
| destAccount | ENUM | 否 | 目标账户 | SPOT | SPOT, FUND, ALL | SPOT |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

### 8.2 矿池API (Mining)

#### `GET /sapi/v1/mining/pub/algoList` - 获取算法列表

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/mining/pub/coinList` - 获取币种列表

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/mining/worker/detail` - 获取矿工详情

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| algo | STRING | 是 | 算法 | 无 | 有效的算法名称 | sha256 |
| userName | STRING | 是 | 用户名 | 无 | 矿工用户名 | 123 |
| workerName | STRING | 是 | 矿工名称 | 无 | 矿工名称 | bhdc1.16A10404B |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/mining/worker/list` - 获取矿工列表

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| algo | STRING | 是 | 算法 | 无 | 有效的算法名称 | sha256 |
| userName | STRING | 是 | 用户名 | 无 | 矿工用户名 | 123 |
| pageIndex | INT | 否 | 页码 | 1 | 1以上的整数 | 1 |
| sort | INT | 否 | 排序 | 0 | 0(默认), 1(算力升序), 2(算力降序), 3(最后提交时间升序), 4(最后提交时间降序) | 0 |
| sortColumn | INT | 否 | 排序列 | 0 | 0(默认), 1(算力), 2(最后提交时间) | 0 |
| workerStatus | INT | 否 | 矿工状态 | 0 | 0(全部), 1(有效), 2(无效), 3(失效) | 0 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/mining/payment/list` - 获取收益列表

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| algo | STRING | 是 | 算法 | 无 | 有效的算法名称 | sha256 |
| userName | STRING | 是 | 用户名 | 无 | 矿工用户名 | 123 |
| coin | STRING | 否 | 币种 | 无 | 有效的币种符号 | BTC |
| startDate | LONG | 否 | 开始日期 | 无 | Unix时间戳(毫秒) | 1587903000000 |
| endDate | LONG | 否 | 结束日期 | 无 | Unix时间戳(毫秒) | 1587903000000 |
| pageIndex | INT | 否 | 页码 | 1 | 1以上的整数 | 1 |
| pageSize | INT | 否 | 每页数量 | 20 | 5-200 | 20 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

### 8.3 法币API (Fiat)

#### `GET /sapi/v1/fiat/orders` - 获取法币订单历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| transactionType | INT | 是 | 交易类型 | 无 | 0(充值), 1(提现) | 0 |
| beginTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1587903000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1587903000000 |
| page | INT | 否 | 页码 | 1 | 1以上的整数 | 1 |
| rows | INT | 否 | 每页数量 | 100 | 1-500 | 100 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

#### `GET /sapi/v1/fiat/payments` - 获取法币支付历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| transactionType | INT | 是 | 交易类型 | 无 | 0(买入), 1(卖出) | 0 |
| beginTime | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1587903000000 |
| endTime | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1587903000000 |
| page | INT | 否 | 页码 | 1 | 1以上的整数 | 1 |
| rows | INT | 否 | 每页数量 | 100 | 1-500 | 100 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

### 8.4 C2C API

#### `GET /sapi/v1/c2c/orderMatch/listUserOrderHistory` - 获取C2C交易历史

| 参数名 | 类型 | 必需 | 描述 | 默认值 | 取值范围/枚举值 | 示例值 |
|--------|------|------|------|--------|-----------------|--------|
| tradeType | ENUM | 是 | 交易类型 | 无 | BUY, SELL | BUY |
| startTimestamp | LONG | 否 | 开始时间 | 无 | Unix时间戳(毫秒) | 1587903000000 |
| endTimestamp | LONG | 否 | 结束时间 | 无 | Unix时间戳(毫秒) | 1587903000000 |
| page | INT | 否 | 页码 | 1 | 1以上的整数 | 1 |
| rows | INT | 否 | 每页数量 | 100 | 1-100 | 100 |
| recvWindow | LONG | 否 | 接收窗口 | 5000 | 1-60000 | 5000 |
| timestamp | LONG | 是 | 时间戳 | 无 | Unix时间戳(毫秒) | 1499827319559 |

## 📋 9. 响应格式和错误代码

### 9.1 标准响应格式

#### 成功响应
```json
{
  "symbol": "BTCUSDT",
  "orderId": 28,
  "orderListId": -1,
  "clientOrderId": "6gCrw2kRUAF9CvJDGP16IP",
  "transactTime": 1507725176595,
  "price": "0.00000000",
  "origQty": "10.00000000",
  "executedQty": "10.00000000",
  "cummulativeQuoteQty": "10.00000000",
  "status": "FILLED",
  "timeInForce": "GTC",
  "type": "MARKET",
  "side": "SELL"
}
```

#### 错误响应
```json
{
  "code": -1121,
  "msg": "Invalid symbol."
}
```

### 9.2 常见错误代码

| 错误代码 | HTTP状态码 | 错误信息 | 描述 |
|----------|------------|----------|------|
| -1000 | 400 | UNKNOWN | 未知错误 |
| -1001 | 401 | DISCONNECTED | 内部错误，无法处理您的请求 |
| -1002 | 401 | UNAUTHORIZED | 您无权执行此请求 |
| -1003 | 429 | TOO_MANY_REQUESTS | 请求过于频繁 |
| -1006 | 409 | UNEXPECTED_RESP | 从消息总线收到意外的响应 |
| -1007 | 408 | TIMEOUT | 等待后端服务器响应超时 |
| -1014 | 400 | UNKNOWN_ORDER_COMPOSITION | 不支持的订单组合 |
| -1015 | 429 | TOO_MANY_ORDERS | 新订单太多 |
| -1016 | 400 | SERVICE_SHUTTING_DOWN | 服务器下线 |
| -1020 | 400 | UNSUPPORTED_OPERATION | 不支持此操作 |
| -1021 | 401 | INVALID_TIMESTAMP | 时间戳不在recvWindow内 |
| -1022 | 401 | INVALID_SIGNATURE | 签名无效 |
| -1100 | 400 | ILLEGAL_CHARS | 参数中包含非法字符 |
| -1101 | 400 | TOO_MANY_PARAMETERS | 发送的参数太多 |
| -1102 | 400 | MANDATORY_PARAM_EMPTY_OR_MALFORMED | 强制参数为空或格式错误 |
| -1103 | 400 | UNKNOWN_PARAM | 发送了未知参数 |
| -1104 | 400 | UNREAD_PARAMETERS | 并非所有发送的参数都被读取 |
| -1105 | 400 | PARAM_EMPTY | 参数为空 |
| -1106 | 400 | PARAM_NOT_REQUIRED | 不需要此参数 |
| -1111 | 400 | BAD_PRECISION | 精度超过此资产定义的最大值 |
| -1112 | 400 | NO_DEPTH | 此交易对没有订单 |
| -1114 | 400 | TIF_NOT_REQUIRED | 不需要TimeInForce参数 |
| -1115 | 400 | INVALID_TIF | 无效的timeInForce |
| -1116 | 400 | INVALID_ORDER_TYPE | 无效的订单类型 |
| -1117 | 400 | INVALID_SIDE | 无效的买卖方向 |
| -1118 | 400 | EMPTY_NEW_CL_ORD_ID | 新的客户订单ID为空 |
| -1119 | 400 | EMPTY_ORG_CL_ORD_ID | 原始客户订单ID为空 |
| -1120 | 400 | BAD_INTERVAL | 无效的时间间隔 |
| -1121 | 400 | BAD_SYMBOL | 无效的交易对 |
| -1125 | 400 | INVALID_LISTEN_KEY | 此listenKey不存在 |
| -1127 | 400 | MORE_THAN_XX_HOURS | 查询间隔太大 |
| -1128 | 400 | OPTIONAL_PARAMS_BAD_COMBO | 可选参数组合无效 |
| -1130 | 400 | INVALID_PARAMETER | 发送的参数为空或格式错误 |
| -2010 | 400 | NEW_ORDER_REJECTED | 新订单被拒绝 |
| -2011 | 400 | CANCEL_REJECTED | 撤销订单被拒绝 |
| -2013 | 400 | NO_SUCH_ORDER | 订单不存在 |
| -2014 | 400 | BAD_API_KEY_FMT | API密钥格式无效 |
| -2015 | 401 | REJECTED_MBX_KEY | 无效的API密钥、IP或操作权限 |
| -2016 | 400 | NO_TRADING_WINDOW | 没有交易窗口 |

### 9.3 订单状态枚举

| 状态 | 描述 |
|------|------|
| NEW | 新建订单 |
| PARTIALLY_FILLED | 部分成交 |
| FILLED | 完全成交 |
| CANCELED | 已撤销 |
| PENDING_CANCEL | 撤销中 |
| REJECTED | 订单被拒绝 |
| EXPIRED | 订单过期 |
| EXPIRED_IN_MATCH | 订单在撮合时过期 |

### 9.4 订单类型枚举

| 类型 | 描述 |
|------|------|
| LIMIT | 限价单 |
| MARKET | 市价单 |
| STOP_LOSS | 止损单 |
| STOP_LOSS_LIMIT | 止损限价单 |
| TAKE_PROFIT | 止盈单 |
| TAKE_PROFIT_LIMIT | 止盈限价单 |
| LIMIT_MAKER | 限价只做maker单 |

### 9.5 时间有效性枚举

| 类型 | 描述 |
|------|------|
| GTC | Good Till Canceled - 成交为止 |
| IOC | Immediate or Cancel - 无法立即成交的部分就撤销 |
| FOK | Fill or Kill - 无法全部立即成交就撤销 |
| GTX | Good Till Crossing - 无法成为挂单方就撤销 |
| GTD | Good Till Date - 在指定时间前有效 |

## 🔐 10. 签名认证详细说明

### 10.1 签名算法

#### HMAC SHA256签名
```python
import hmac
import hashlib
import time

def create_signature(query_string, secret_key):
    return hmac.new(
        secret_key.encode('utf-8'),
        query_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

# 示例
secret_key = "your_secret_key"
query_string = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
signature = create_signature(query_string, secret_key)
```

#### RSA签名
```python
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

def create_rsa_signature(query_string, private_key_path):
    with open(private_key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None
        )
    
    signature = private_key.sign(
        query_string.encode('utf-8'),
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    
    return base64.b64encode(signature).decode('utf-8')
```

#### Ed25519签名
```python
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

def create_ed25519_signature(query_string, private_key_path):
    with open(private_key_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None
        )
    
    signature = private_key.sign(query_string.encode('utf-8'))
    return base64.b64encode(signature).decode('utf-8')
```

### 10.2 请求头设置

| 头部名称 | 描述 | 示例值 |
|----------|------|--------|
| X-MBX-APIKEY | API密钥 | your_api_key |
| Content-Type | 内容类型 | application/x-www-form-urlencoded |
| X-MBX-SIGNATURE | 签名 | signature_value |

### 10.3 时间戳要求

- 时间戳必须是Unix时间戳（毫秒）
- 服务器时间与请求时间的差异不能超过recvWindow（默认5000毫秒）
- 建议定期同步服务器时间

```python
import time
import requests

def get_server_time():
    response = requests.get('https://api.binance.com/api/v3/time')
    return response.json()['serverTime']

def get_timestamp():
    return int(time.time() * 1000)
```

## 📊 总结

这份详细的参数说明文档涵盖了币安API的所有主要端点和参数，包括：

1. 现货交易API - 完整的市场数据和交易参数
2. 期货交易API - U本位和币本位合约的所有参数
3. 期权API - 期权交易的详细参数说明
4. 杠杆交易API - 杠杆账户管理和交易参数
5. 钱包API - 资产管理和转账参数
6. 子账户API - 企业级账户管理参数
7. WebSocket流 - 实时数据流的订阅参数
8. 其他API - 理财、矿池、法币等增值服务参数
9. 响应格式 - 标准响应和错误处理
10. 签名认证 - 详细的安全认证说明

每个参数都包含了：
- 参数名称和类型
- 是否必需
- 详细描述
- 默认值
- 取值范围或枚举值
- 实际示例值

这份文档可以作为您开发币安数据收集模块的完整参考手册，确保能够正确使用所有API端点和参数。
