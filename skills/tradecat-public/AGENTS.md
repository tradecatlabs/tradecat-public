# tradecat-public Skill 包说明

本文件作用域：`tradecat-public/skills/tradecat-public/**`。这里是 Hermes/Codex Skill 包，不是 Python 项目根。

## 结构

```text
skills/tradecat-public/
|-- SKILL.md
|-- README.md
|-- AGENTS.md
|-- agents/
|   |-- manifest.json
|   |-- hermes.yaml
|   `-- openai.yaml
|-- references/
`-- scripts/
    |-- run-tradecat.sh
    `-- validate-skill.sh
```

## 职责

- `SKILL.md`：Skill 激活、使用场景、安全边界和快速命令。
- `agents/manifest.json`：唯一机器主契约，路径按仓库根目录解释。
- `agents/*.yaml`：平台适配 profile，只能引用 manifest。
- `references/`：长文档、Agent 契约、Hermes 操作指南和安全边界。
- `scripts/`：薄 wrapper，负责从 Skill 目录跳回仓库根脚本。

## 禁区

- 不放 Python 源码、测试、contracts、resources 或运行态。
- 不复制第二份项目实现。
- 不写 `.runtime/`、`.tradecat/`、`.venv/`、`.env` 或任何凭证。
- 不授权真实 Binance key、签名请求、账户读取或真实下单。

## 上下游

```text
Hermes/Agent
-> SKILL.md
-> agents/manifest.json
-> ../../scripts/run-tradecat.sh
-> ../../src + ../../contracts + ../../resources
-> ignored ../../.runtime paper/watch state
```
