# Deployment and Operations

TradeCat Public 不部署真实交易服务。可运行形态只有本地 public-readonly + paper/watch。
逐步操作清单见 `docs/operations-runbook.md`。

## 安装

```bash
python3 -m pip install -c constraints.txt -e ".[dev]"
```

## 本地 paper/watch

默认运维口径是手动运行，不常驻。启动 loop 会持续读取公开在线表格、
Binance public/read-only 数据和本地 Agent/thesis 上下文，可能产生网络/API/token
成本；启动前必须确认预算、代理和运行目的。

```bash
bash scripts/start-auto-paper.sh ops-check --json
bash scripts/start-auto-paper.sh start --json
bash scripts/start-auto-paper.sh status --json
bash scripts/start-auto-paper.sh stop --json
```

运行态写入 ignored `.runtime/auto-paper/`。不要把运行日志、账本、SQLite audit journal、PID 文件或缓存提交到 Git。
常驻事实源默认是 `.runtime/auto-paper/paper_ledger.json` 与 `.runtime/auto-paper/cycles.jsonl`。
单轮 public-readonly/paper cycle 默认受 `TRADECAT_AUTO_PAPER_CYCLE_TIMEOUT_SECONDS=6000` 限制，避免进程仍在但心跳长期停滞。
启动脚本默认不生成 ignored `.runtime/auto-paper/paper_autonomy_profile.json`，
缺少 Agent/Hermes 显式 `agent_trade_thesis.v1` 或显式 profile 时必须
fail-closed。只有设置 `TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED=1` 或传入
`TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH`，才允许使用 paper-only runtime profile。
用户后续要限制仓位、杠杆、退出或组合风险时，再显式传入 profile/policy。

启动脚本也默认运行 `strategy-review` 并写入 ignored `.runtime/auto-paper/strategy_state.json`。该状态根据本地 paper outcome 自动暂停亏损 symbol、亏损信号类型或亏损方向，并限制最大 open positions 与单币并发；设置 `TRADECAT_AUTO_PAPER_STRATEGY_REVIEW_ENABLED=0` 可关闭这层 paper/watch 自我迭代过滤。

长期常驻不是默认模式。确需常驻时，使用 user systemd service 作为唯一生命周期 owner：

```bash
bash scripts/start-auto-paper.sh systemd-install --json
systemctl --user status tradecat-auto-paper.service
```

该安装入口会禁用旧版 `tradecat-auto-paper.timer`，停止已有手动 `_run`，再启用长驻
`tradecat-auto-paper.service`。不要同时让 timer `_cycle` 和手动 `_run` 写同一套
`.runtime/auto-paper/`。

## Web 监控

```bash
python3 scripts/serve-auto-paper-monitor.py --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/`。页面只读展示本地 paper/watch、审计日志、账本、输入信号、Agent decision text 和依赖链健康；它不会启动 auto-paper loop。

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
python3 scripts/ops-audit.py --json
```

`ops-audit.py` 只读检查 auto-paper 状态、旧 systemd unit/drop-in、tmux pane、残留进程、
监控端口、crontab、runtime owner 和 ignored runtime autonomy profile。CI 只证明代码和门禁通过，
不代表本机 loop 正在运行。

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
