# services/（三层单向数据流）

本目录按 **采集（ingestion）→ 处理/计算（compute）→ 消费（consumption）** 三层拆分服务，用“目录结构”强制依赖方向，降低跨模块耦合与错误写入的概率。

## 目录结构

```
services/
├── ingestion/                       # 采集层：只做拉取/标准化/写入原始事实
│   ├── binance-vision-service/      # Binance Vision Raw 对齐采集（ccxtpro + Vision ZIP 回填）
│   └── data-service/                # 低频/分时采集（1m K线、5m 指标，兼容链路，非默认启动）
├── compute/                          # 处理层：只读采集层事实，计算指标/信号并落派生结果
│   ├── trading-service/             # 指标计算（写入 PG(tg_cards) 指标库供消费侧展示）
│   ├── signal-service/              # 信号检测（只读指标库，写入自身冷却/历史）
│   └── ai-service/                  # AI 分析（读指标/信号做解释与摘要）
└── consumption/                      # 消费层：只读派生结果，负责 API/推送/可视化
    ├── telegram-service/            # Telegram Bot（展示与推送）
    └── api-service/                 # REST API（只读查询）
```
 
> 说明：`data-service` 为兼容链路，不在顶层 `./scripts/start.sh` 默认启动/校验链路内；需要时请手动进入目录运行其 `./scripts/start.sh`。

## 依赖边界（硬规则）

- `ingestion/**` 禁止 import `compute/**`、`consumption/**`
- `compute/**` 禁止 import `consumption/**`
- `consumption/**` 禁止写入 PostgreSQL 业务域（Raw/Derived），只允许写 **缓存/投递去重状态**

> 相关设计依据：`assets/docs/analysis/layer_contract_one_pager.md`、`assets/docs/analysis/repo_structure_design.md`。
