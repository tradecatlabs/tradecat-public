# Operations Runbook

TradeCat Public 的默认运行态是手动、只读、paper/watch。不要把 CI 绿色、GitHub push 成功或
Web monitor 打开理解为 auto-paper loop 正在运行。

## 1. 查看当前状态

```bash
python3 scripts/ops-audit.py --json
bash scripts/start-auto-paper.sh status --json
```

`ops-audit.py` 是首选入口。它只读检查：

- auto-paper 是否运行。
- user systemd 中是否残留 `tradecat-auto-paper.*` 或旧 `tradecat-daemon.service`。
- tmux pane、进程、端口 `8765`、crontab 是否有 runtime 残留。
- ignored `.runtime/auto-paper/paper_autonomy_profile.json` 是否存在、是否被配置。
- 当前 paper sizing 来源是 `agent_trade_thesis`、`paper_autonomy_profile` 还是 `agent_required_missing`。

## 2. 启动前检查

默认不要常驻启动。启动前必须确认：

- 本轮确实需要 paper loop，而不是只要读报告或看历史账本。
- 代理、公开在线表格和 Binance public/read-only 网络可用。
- token/API/网络成本预算可接受。
- 是否由 Agent thesis 提供 sizing/exits，或显式启用 runtime profile。

严格 Agent thesis 模式：

```bash
export TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED=0
export TRADECAT_AUTO_PAPER_AGENT_TRADE_THESIS_PATH=.runtime/auto-paper/agent_trade_thesis.json
```

显式 runtime profile 模式：

```bash
export TRADECAT_AUTO_PAPER_AUTONOMY_ENABLED=1
```

## 3. 手动运行与停止

```bash
bash scripts/start-auto-paper.sh ops-check --json
bash scripts/start-auto-paper.sh start --json
bash scripts/start-auto-paper.sh status --json
bash scripts/start-auto-paper.sh stop --json
python3 scripts/ops-audit.py --json
```

`stop` 后必须再跑 `ops-audit.py`，确认 `ok=true`、`manual_mode=true`、无 issues/warnings。

## 4. 常驻运行

常驻不是默认模式。确需常驻时只允许一个 lifecycle owner：

```bash
bash scripts/start-auto-paper.sh systemd-install --json
systemctl --user status tradecat-auto-paper.service
```

停用并清理：

```bash
bash scripts/start-auto-paper.sh systemd-uninstall --json
python3 scripts/ops-audit.py --json
```

如果 `ops-audit.py` 报告旧 `tradecat-daemon.service` 或 `tradecat-auto-paper.service.d/proxy.conf`，
先确认它们不是当前任务需要的服务，再删除对应 user systemd 文件并执行：

```bash
systemctl --user daemon-reload
systemctl --user reset-failed tradecat-daemon.service tradecat-auto-paper.service tradecat-auto-paper.timer
```

## 5. 查看报告与账本

```bash
bash scripts/run-tradecat.sh paper-report --json
bash scripts/run-tradecat.sh latest-cycle --json
bash scripts/run-tradecat.sh latest-decision --json
bash scripts/run-tradecat.sh audit-journal --json
bash scripts/run-tradecat.sh health-report --json
```

本地 Web monitor 是只读页面，不会启动 auto-paper loop：

```bash
python3 scripts/serve-auto-paper-monitor.py --host 127.0.0.1 --port 8765
```

## 6. CI 与运行态边界

CI 验证代码、契约、测试和安全门禁；本地运行态必须用 `ops-audit.py` 或 status 命令确认。
`tradecat-public` 是公开 Skill/Agent + paper/watch 仓库；当前 remote 名称 `tukuaiai/tradecat`
不代表旧私有 TradeCat 运行态，也不代表实盘 executor。
