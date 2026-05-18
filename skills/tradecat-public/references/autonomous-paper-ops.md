# Autonomous Paper Ops

本文件定义 TradeCat public paper/watch 长期运行的运维依赖链。它只覆盖
`.runtime/auto-paper/` 本地纸面运行态；不读取 Binance key、不签名、不调用账户或订单接口、不真实下单。

## 依赖链

```text
Hermes/operator supervisor
-> tradecat-public repository-root Python project
-> embedded Skill package at skills/tradecat-public/
-> skills/tradecat-public/agents/manifest.json
-> root .venv Python environment
-> public online sheet signal source
-> Agent/Hermes Binance public-readonly market context
-> context-audit
-> agent_trade_thesis.v1 or local paper_autonomy_profile.v1 with explicit paper sizing and exits
-> portfolio_risk_policy / paper kill switch
-> auto-paper run-loop
-> paper ledger / cycle archive / SQLite audit journal
-> health-report / daily-report / alert-payload
```

## 运维对象

| 对象 | TradeCat 落点 | 验收 |
| --- | --- | --- |
| 生命周期 | `start-auto-paper.sh start/status/stop/heal --json` 和 user systemd timer | `running=true`，或 `heal` 能在缺进程时拉起 paper loop |
| 防重启风暴 | systemd `StartLimitIntervalSec`、`StartLimitBurst`、`RestartSec` | 单元文件包含限制，失败不会无限紧密重启 |
| 身份权限 | `ops-check --json` 输出 `uid/run_as_root` | 能看出是否 root；public paper/watch 不要求 Binance 凭证 |
| 日志审计 | `paper-run-loop.log`、`paper_audit.sqlite3`、`cycles.jsonl` | 日志、cycle、audit chain 可排查且只在 `.runtime/auto-paper/` |
| 健康检查 | `health-report --json` | 可发现 `heartbeat_stale`、ledger/archive/audit 异常 |
| 依赖管理 | `ops-check --json` 检查 Python、路径、磁盘、systemctl、OS limit | `ok=true` 且 `blocking_checks=[]` |
| 配置校验 | `ops-check --json` 检查 runtime path 隔离、https base URL、credential env names | 配置错误时返回 `paper_ops_preflight_failed` |
| 进程数量 | PID 文件和 `status --json` 单实例边界 | 只认一个 `paper-run-loop.pid` |
| 文件描述符 | `ops-check --json` 检查 `nofile_limit`，systemd 写 `LimitNOFILE` | FD soft limit 不低于阈值 |
| 自动告警 | `alert-payload --kind daily --json` 和 health alerts | 告警 payload 保持 `telegram_alerts.v1` 且 safety 全 false |
| 变更回滚 | Git tag/commit 回滚代码，运行态不入库 | 回滚不覆盖 `.runtime/auto-paper/` 账本和审计链 |
| 权限审计 | OS/shell/systemd 日志 + local audit journal | 谁启停服务由宿主审计，TradeCat 记录 paper cycle/audit |
| 灾备恢复 | `.runtime/auto-paper/` 的 ledger/archive/journal 可备份恢复 | 恢复后 `health-report` 可重新读出 state/ledger/archive/audit |

## 命令序列

先做本地依赖预检：

```bash
bash scripts/start-auto-paper.sh ops-check --json
```

启动或自愈本地 paper/watch 常驻运行态：

```bash
bash scripts/start-auto-paper.sh heal --json
bash scripts/start-auto-paper.sh status --json
```

若 operator 明确要求“让 Agent/AI 在纸面环境内自主开仓”，不要改代码里的默认金额；
应在 gitignored `.runtime/auto-paper/` 下放一个 `paper_autonomy_profile.v1`，并通过
`TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH` 注入。该 profile 只能给 paper/watch
提供 `requested_margin_usdt` / `paper_leverage` / exit bps / 最大持仓时间 /
同币种多仓授权；如显式设置 `allow_agent_direction_override=true`，还可只在
`direction_conflict` 这类软方向冲突上授权 Agent/纸面 profile 覆盖方向，不能覆盖
低分、kill switch 或组合风控拒绝；`real_orders`、`signed_requests`、`reads_api_keys` 和
`binance_account_state` 必须为 `false`。

```bash
TRADECAT_AUTO_PAPER_AUTONOMY_PROFILE_PATH=.runtime/auto-paper/paper_autonomy_profile.json \
  bash scripts/start-auto-paper.sh restart --json
```

使用 user systemd timer 作为长期 keepalive：

```bash
bash scripts/start-auto-paper.sh systemd-install --json
systemctl --user status tradecat-auto-paper.timer
```

健康、日报和告警：

```bash
bash scripts/start-auto-paper.sh health --json
bash scripts/start-auto-paper.sh daily --json
bash scripts/start-auto-paper.sh alert --json
```

外接 HDMI 或独立终端观察窗口：

```bash
bash scripts/monitor-auto-paper.sh --interval 5
```

该窗口每轮只读取本地 `status`、`health`、paper ledger、audit journal、ops
preflight 和 log tail；它不会写运行态，也不会联网下单。

停止：

```bash
bash scripts/start-auto-paper.sh stop --json
```

## 硬边界

- `ops-check` 可以报告 credential-like 环境变量名，但不得读取变量值。
- `auto-paper` 只运行 public-readonly + paper/watch。
- 缺 Agent thesis 或本地 paper autonomy profile 明确 sizing 和 exit plan 时继续 fail-closed。
- 所有运行态必须停留在 gitignored `.runtime/auto-paper/`。
- private executor、真实 key、签名、账户、订单和真钱风控不属于 `tradecat-public`。
