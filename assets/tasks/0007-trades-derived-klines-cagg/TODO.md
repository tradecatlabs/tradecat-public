# TODO

- [ ] P0: 设计 cagg SQL 与 policy 参数 | Verify: SQL 可读且可复用 | Gate: review 通过
- [ ] P0: 创建 3 个 1m cagg | Verify: `timescaledb_information.continuous_aggregates` | Gate: AC1
- [ ] P0: 抽样手工对账 1 个 bucket | Verify: 手工 SQL vs cagg | Gate: AC2
- [ ] P1: 配置刷新窗口并验证 job | Verify: `timescaledb_information.jobs` | Gate: AC3

