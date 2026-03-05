# TODO

> 每一项都必须“可验证”，并写明 Gate（验收门槛）。

## P0

- [x] P0: `prune_tabs` 调度化（interval + keep hash） | Verify: `rg -n \"prune_tabs\" logs/sheets.systemd.log | wc -l` 24h 内显著下降 | Gate: `ACCEPTANCE.B1/B2`
- [x] P0: 读请求弱网重试覆盖 `SSLError/ConnectionResetError` | Verify: 人为断网/注入失败后服务可自恢复 | Gate: `ACCEPTANCE.A1/A2`
- [x] P0: 新增 `--snapshot-col-widths`（输出看板/币种查询/Polymarket 三表 env 行） | Verify: 运行命令输出 5 行 env | Gate: `ACCEPTANCE.C1`

## P1

- [x] P1: 日志 debug 开关（默认安静） | Verify: `SHEETS_LOG_LEVEL=info` 时无 `[DEBUG]` | Gate: `ACCEPTANCE.D1`
- [x] P1: `prune_tabs` 单行摘要日志（执行/跳过/原因） | Verify: systemd log 可 grep 到摘要 | Gate: `ACCEPTANCE.D2`
- [x] P1: 更新 `services/consumption/sheets-service/README.md` 说明新增 CLI | Verify: README 可直接复制执行 | Gate: 文档一致性

## P2（可选）

- [ ] P2: i18n 缺失键补齐（减少噪音） | Verify: 日志不再出现缺失键告警 | Gate: 不影响卡片值
- [ ] P2: server Python 升级到 3.12（消除 FutureWarning） | Verify: `python --version` | Gate: 服务无回归
