# 新结构设计（3 层单向数据流）

> 生成时间: 2026-02-10  
> 目标: 用“目录结构 + 依赖边界”把系统强制收敛为 **采集 → 处理 → 消费** 三层；让代码天然不容易写错。

---

## 1. 设计目标（What good looks like）

- **三层单向流动**：采集只写原始层；处理只读原始层写派生层；消费只读派生层/必要回查原始层。
- **PostgreSQL 真相源**：PG 是权威；SQLite 只允许作为消费侧缓存（可丢、可重建）。
- **幂等优先**：以“至少一次”交付为前提设计表与写入方式（upsert / insert-ignore）。
- **可观测优先**：每层都能独立回答：延迟多少？缺口多少？重复多少？哪里坏了？

非目标（本阶段不做）：
- 不追求“一次性大迁移”；优先可渐进、可回滚。
- 不把 Pine 转译做成“全语言兼容”；先限定子集、先可验证。

---

## 2. 理想形态（Perfect World）

> 根目录只保留 `tradecat/`（实现）+ `docs/`（文档）；其他内容（scripts、deploy、legacy）逐步收敛到 `tradecat/` 内部或外移为工具仓。

```
tradecat/
├── tradecat/                         # 唯一实现入口（Python package / workspace root）
│   ├── __init__.py
│   ├── config.py                     # 配置入口：env/文件/默认值（禁止隐式 cwd）
│   ├── contracts.py                  # 跨层契约：schema/幂等键/quality_flags（单文件，避免“第4层目录”）
│   ├── db.py                         # PG 连接与轻量封装（仅基础能力：连接/迁移钩子/健康检查）
│   ├── observability.py              # 指标/日志/trace 约定（Prometheus/OpenTelemetry 适配点）
│   ├── ingestion/                    # ==================== 采集层 ====================
│   │   ├── __init__.py
│   │   ├── providers/                # 各数据源适配器（只做拉取+标准化，不做计算）
│   │   │   ├── binance/
│   │   │   ├── hyper/
│   │   │   ├── polymarket/
│   │   │   └── altpool/              # “私有方法”数据池：对外只暴露标准化后的 RawEvent
│   │   ├── jobs/                     # 采集任务编排：分区、速率、重试、水位线
│   │   └── storage.py                # 写入 PG raw_*（只写原始层）
│   ├── compute/                      # ==================== 处理/计算层 ====================
│   │   ├── __init__.py
│   │   ├── pipelines/                # 计算流水线：输入分区 -> 计算 -> 写派生层
│   │   ├── indicators/               # 指标库（纯函数/确定性；不做 IO）
│   │   ├── signals/                  # 规则引擎/信号生成（纯计算 + 明确去重键）
│   │   ├── pine/                     # Pine 子集：parser/ir/runtime + 对齐测试（可选 TS/py 实现）
│   │   └── storage.py                # 写入 PG derived_*（只写派生层）
│   └── consumption/                  # ==================== 消费层 ====================
│       ├── __init__.py
│       ├── api/                      # REST/GraphQL（只读 PG + 只读缓存）
│       ├── push/                     # Telegram/钉钉/飞书/Discord（只读 PG；带 dedupe）
│       ├── cache/                    # SQLite/Redis 等缓存实现（允许丢失）
│       └── dedupe.py                 # 统一去重键生成与投递幂等
└── docs/
    └── analysis/
        ├── layer_contract_one_pager.md
        └── repo_structure_design.md
```

### 2.1 依赖边界（硬规则）

- `ingestion/*` **禁止** import `compute/*`、`consumption/*`
- `compute/*` **禁止** import `consumption/*`
- `consumption/*` **禁止**写 PG（派生层/原始层都不写），只能读 + 写缓存
- 共享能力只允许放在 `tradecat/config.py`, `tradecat/contracts.py`, `tradecat/db.py`, `tradecat/observability.py`（“薄而可控”）

---

## 3. 现实渐进方案（Real World, 兼容当前多服务）

> 当前仓库已将 `services/` 按 `ingestion/compute/consumption` 分层落地；`services-preview/` 为历史遗留概念（本仓库目录已移除）。

建议落地顺序：
1) **先落契约**：把跨服务共享的 schema、幂等键、quality_flags 固化（`tradecat/contracts.py`）。  
2) **再落写入边界**：采集写 raw；trading/signal 写 derived；telegram/api 只读。  
3) **最后做目录大迁移**：当 80% 逻辑都被“新契约”约束住后，再搬目录才不会乱。

### 3.1 现有服务到三层的映射（建议）

| 层 | 现有服务（候选） | 角色 |
|---|---|---|
| 采集 | `services/ingestion/binance-vision-service/` | 拉取外部数据 → 标准化 → 写 PG raw_* |
| 处理 | `services/compute/trading-service/`, `services/compute/signal-service/` | 读 raw_* → 计算指标/信号 → 写 derived_* |
| 消费 | `services/consumption/telegram-service/`, `services/consumption/api-service/` | 读 derived_* → 展示/推送（允许写缓存） |

> 注：`services/ingestion/data-service/` 为低频/分时兼容链路（1m K线、5m 指标），默认不进入顶层启动链路，需要时手动运行。

> 注：`services/compute/ai-service/` 更像“消费侧分析”（读派生层做解释/摘要），除非它会反向生成可复用特征写回派生层。

---

## 4. 命名与模块粒度（让代码像刀一样利）

- 对人看的：文档/日志/提示语 **中文**；对机器的：模块/变量/函数 **英文**。
- provider 名称用小写：`binance`, `hyper`, `polymarket`；统一对外暴露同一种数据模型（RawEvent / Candle）。
- 计算侧一切尽量“纯函数”：输入是数组/df/序列，输出是结构化值 + quality_flags；IO 全收敛到 `storage.py`。

---

## 5. Taste Check（我认为最容易写歪的地方）

最不优雅、也最危险的一点：**把“共享工具”做成一个大杂烩包**（common/utils 巨型泥团）。  
它会迅速变成跨层循环依赖的温床，最终逼迫你用“特殊情况 if/else”救火。

约束解法：共享只允许是“薄而硬”的：配置、契约、db、观测——四块之外一律不共享，宁愿复制一小段代码也不要共享错误的抽象。
