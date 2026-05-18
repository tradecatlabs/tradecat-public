# TradeCat Public Skill

这是嵌入在 `tradecat-public` 正常 Python 项目里的 Hermes/Codex Skill 包。Skill 包负责 Agent 激活、机器契约、角色配置和操作边界；具体实现位于仓库根目录的 `src/`、`contracts/`、`resources/`、`scripts/`、`tests/`。

## 入口

- Skill 激活：`SKILL.md`
- 机器主契约：`agents/manifest.json`
- Hermes profile：`agents/hermes.yaml`
- OpenAI profile：`agents/openai.yaml`
- 操作指南：`references/hermes-agent-guide.md`
- 安全边界：`references/private-executor-boundary.md`

## 使用

在仓库根目录运行：

```bash
python3 scripts/request.py signal_flow --format json --limit 5
python3 scripts/request.py anomaly_panel --format json --limit 0
bash scripts/run-tradecat.sh soft-layer --json
bash scripts/run-tradecat.sh paper-report --json
bash scripts/start-auto-paper.sh status --json
```

从本 Skill 目录运行时，薄 wrapper 会自动跳回仓库根：

```bash
bash scripts/run-tradecat.sh soft-layer --json
```

## 边界

- 不读取 Binance key。
- 不签名请求。
- 不调用真实账户、订单、杠杆、保证金修改端点。
- 不真实下单。
- 不恢复退役的本地 TUI、安装器或 cache-browser 产品线。
- 运行态只允许写入 ignored `.runtime/`、`.tradecat/`、`.venv/` 等本地目录。

## 验证

```bash
bash ../../scripts/validate-skill.sh --strict
bash ../../scripts/agent-smoke.sh
bash ../../scripts/verify.sh
```
