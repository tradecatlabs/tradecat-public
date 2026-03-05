# PLAN - stability-execution-roadmap

## 1) 技术选型分析（至少两案）

### 方案 A：继续按“分散任务”推进（不新增路线图）

- 做法：分别进入 `0018/0012/0015/0025/0020` 目录按各自 TODO 执行，执行完再人工汇总。
- Pros：不新增任务；改动最少。
- Cons：
  - 极易出现 **文档漂移**（索引/状态/证据不同步），见 `0020` 现状（`assets/tasks/0020-data-api-contract-hardening/TODO.md:7` 未勾选但 INDEX 已 Done）。
  - 缺少统一门禁与阶段性回滚点，容易在“并行推进”中引入多世界语义与回归。

### 方案 B（推荐）：引入“执行路线图”作为唯一入口（0027）

- 做法：把剩余稳定性工作按 P0→P1→P2 编排成阶段（Phase），每个 Phase 都有：基线证据 → 变更 → 门禁 → 状态更新 → 回滚点。
- Pros：
  - 统一了执行顺序与门禁口径，减少并行带来的漂移。
  - 允许在“任务粒度”上做可靠回滚（每个 Phase 一个 commit）。
  - 把“任务状态对齐”当作可执行步骤，杜绝 INDEX=Done 但 TODO 未闭环。
- Cons：需要维护一份路线图（但路线图只引用既有任务，不重复写细节，漂移成本可控）。

结论：选择 **方案 B**。

## 2) 逻辑流图（ASCII）

```text
            ┌──────────────────────────────┐
            │ 0018 data-service ban/backoff│
            └──────────────┬───────────────┘
                           │ 采集稳定后数据连续
                           v
┌──────────────┐   ┌──────────────┐   ┌──────────────────┐
│ ingestion(LF) │→→│ compute       │→→│ api-service(/v1)  │
└──────────────┘   └──────────────┘   └─────────┬────────┘
                                                 │
                                                 v
                                      ┌────────────────────┐
                                      │ 0012 sheets-service │
                                      └────────────────────┘

并行收尾：
- 0015：单 PG 收口（无 sqlite 残留）
- 0025：statement_timeout + sys.path 收敛
- 0020：基线证据 + 缓存/OpenAPI 对齐
```

## 3) 分阶段执行（Phase Plan）

> 原则：**每个 Phase 单独 commit**；Phase 未过门禁不进入下一阶段。

### Phase 0：基线冻结（必须）

- 记录当前 HEAD、关键服务状态、关键接口样例（不含敏感信息）。
- 目的：任何回归都可对比“变更前基线”。

### Phase 1（P0）：采集链路 ban/backoff（0018）

- 修改范围（文件级）：`services/ingestion/data-service/src/adapters/ccxt.py`、`.../collectors/backfill.py`、`.../scripts/start.sh`（详见 `assets/tasks/0018-stabilize-data-service-ban-backoff/TODO.md:7`）。
- 验证：30 分钟观察 +（可选）最小单测。

### Phase 2（P0）：Sheets 弱网/配额（0012）

- 修改范围（文件级）：`services/consumption/sheets-service/src/*`（读请求重试、prune 调度、列宽快照 CLI）。
- 验证：弱网故障注入 + 24h 日志计数与摘要。

### Phase 3（P1）：单 PG 收口（0015 P0/P2）

- 修改范围（文件级）：移除核心服务 SQLite 路径；清理运行期 `.db` 依赖；文档同步。
- 验证：`rg import sqlite3`、`find *.db`、`./scripts/verify.sh`。

### Phase 4（P1）：Query Service 生产化 P2（0025 P2 + 0024/0020 文档对齐）

- `0025`：statement_timeout + sys.path 收敛（`assets/tasks/0025-query-service-production-hardening/TODO.md:21`）。
- `0024`：若 P1/P2 已被 0025 覆盖，必须“用证据补齐勾选/同步状态”，或明确仍未完成项（禁止任务漂移）。
- `0020`：补齐基线证据、并完成 P2（缓存/请求合并、OpenAPI），或将任务回退为 In Progress 并写清原因。

### Phase 5：全仓门禁与索引收敛

- `./scripts/verify.sh`、核心服务 `make check`。
- 更新 `assets/tasks/INDEX.md`：把已闭环任务标记 Done，并确保每个 Done 都有 `STATUS.md` 证据支撑。

## 4) 回滚协议（Rollback）

- 每个 Phase 一个 commit；出现回归直接 `git revert <sha>` 回到上一 Phase。
- 若 Query Service 鉴权导致消费端全挂：临时 `QUERY_SERVICE_AUTH_MODE=disabled` 止血（必须在 `STATUS.md` 记录，随后恢复 required）。
- 任何涉及“清理文件/删除产物”的动作必须先 dry-run 输出清单，再执行，避免误删。

