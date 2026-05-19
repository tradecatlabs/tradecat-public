# Deployment and Operations

TradeCat Public 不部署真实交易服务。可运行形态只有本地 public-readonly + paper/watch。

## 安装

```bash
python3 -m pip install -c constraints.txt -e ".[dev]"
```

## 本地 paper/watch

```bash
bash scripts/start-auto-paper.sh ops-check --json
bash scripts/start-auto-paper.sh start --json
bash scripts/start-auto-paper.sh status --json
bash scripts/start-auto-paper.sh stop --json
```

运行态写入 ignored `.runtime/auto-paper/`。不要把运行日志、账本、SQLite audit journal、PID 文件或缓存提交到 Git。
常驻事实源默认是 `.runtime/auto-paper/paper_ledger.json` 与 `.runtime/auto-paper/cycles.jsonl`。
单轮 public-readonly/paper cycle 默认受 `TRADECAT_AUTO_PAPER_CYCLE_TIMEOUT_SECONDS=6000` 限制，避免进程仍在但心跳长期停滞。
启动脚本默认生成并沿用 ignored `.runtime/auto-paper/paper_autonomy_profile.json`，用于 paper-only 自治开仓；Agent/Hermes 显式写入的 `agent_trade_thesis.v1` 仍通过 `TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH` 优先注入。要恢复严格等待外部 thesis，设置 `TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED=0`。用户后续要限制仓位、杠杆、退出或组合风险时，再显式传入 profile/policy。

启动脚本也默认运行 `strategy-review` 并写入 ignored `.runtime/auto-paper/strategy_state.json`。该状态根据本地 paper outcome 自动暂停亏损 symbol、亏损信号类型或亏损方向，并限制最大 open positions 与单币并发；设置 `TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_ENABLED=0` 可关闭这层 paper/watch 自我迭代过滤。

## Web 监控

```bash
python3 scripts/serve-auto-paper-monitor.py --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/`。页面只展示本地 paper/watch、审计日志、账本、输入信号、Agent decision text 和依赖链健康。

## 环境配置

参考 `.env.example`。允许配置 public 网络代理和本地 runtime 路径；不允许配置 Binance key、secret、listen key、账户 ID、真实下单或签名请求。

## 健康检查

```bash
bash scripts/start-auto-paper.sh status --json
bash scripts/run-tradecat.sh health-report --json
bash scripts/run-tradecat.sh paper-report --json
bash scripts/run-tradecat.sh latest-cycle --json
bash scripts/run-tradecat.sh latest-decision --json
bash scripts/run-tradecat.sh audit-journal --json
```

## 发布前门禁

```bash
bash scripts/agent-smoke.sh
bash scripts/verify.sh
bash scripts/validate-skill.sh --strict
bash scripts/security-scan.sh
bash scripts/supply-chain-audit.sh
git diff --check
```

如果要发布 tag，先更新 `CHANGELOG.md`，确认版本号与 `pyproject.toml` 一致，再创建 `vMAJOR.MINOR.PATCH` tag。
