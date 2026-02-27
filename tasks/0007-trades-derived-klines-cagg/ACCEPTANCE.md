# ACCEPTANCE

## AC1｜连续聚合创建成功

- 验证：
  - `SELECT * FROM timescaledb_information.continuous_aggregates WHERE view_schema='crypto' AND view_name LIKE 'cagg_%';`
- 通过条件：至少存在 3 个 1m cagg（UM/CM/Spot 各 1 个）。

## AC2｜K 线字段口径正确

- 验证（抽样 1 个 bucket）：
  - open=第一笔 price
  - close=最后一笔 price
  - high/low=区间 max/min(price)
  - volume=sum(qty)
  - quote_volume=sum(quote_qty)
  - trade_count=count(*)
  - taker_buy_volume=sum(qty) WHERE is_buyer_maker=false
  - taker_buy_quote_volume=sum(quote_qty) WHERE is_buyer_maker=false
- 通过条件：与手工聚合 SQL 对得上。

## AC3｜刷新策略存在且可控

- 验证：`timescaledb_information.jobs` 存在对应 policy，且 start/end offset 合理（避免写放大）。
- 通过条件：policy 存在并能按配置刷新。

