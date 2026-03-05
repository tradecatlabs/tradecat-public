# CONTEXT - stability-execution-roadmap

## 1) 现状追溯（Evidence-based）

当前仓库的“核心链路”已完成 Query Service v1 与高周期期货 metrics 的对齐闭环（见 `assets/tasks/0026-closeout-cagg-consumption-contract/STATUS.md`），但仍存在若干 **未闭环的稳定性/运维性任务**，会导致长期运行时的抖动、资源浪费与可观测性退化：

- `0012-sheets-service-hardening`：状态为 Not Started（见 `assets/tasks/INDEX.md:16`），其 P0 项仍未执行（见 `assets/tasks/0012-sheets-service-hardening/TODO.md:7`）。  
- `0018-stabilize-data-service-ban-backoff`：状态为 Not Started（见 `assets/tasks/INDEX.md:22`），其 P0 项仍未执行（见 `assets/tasks/0018-stabilize-data-service-ban-backoff/TODO.md:5`）。  
- `0015-unify-all-storage-to-postgres`：状态为 In Progress（见 `assets/tasks/INDEX.md:19`），仍有 P0/P2 未勾选项（见 `assets/tasks/0015-unify-all-storage-to-postgres/TODO.md:8` 与 `assets/tasks/0015-unify-all-storage-to-postgres/TODO.md:22`）。  
- `0024/0025`：状态为 In Progress（见 `assets/tasks/INDEX.md:28`、`assets/tasks/INDEX.md:29`）；其中 `0025` 的 P2（statement_timeout、sys.path 收敛）未收口（见 `assets/tasks/0025-query-service-production-hardening/TODO.md:21`）。  
- `0020`：虽然在索引中标记 Done（见 `assets/tasks/INDEX.md:24`），但其 TODO 仍留有未勾选项（基线证据 + P2：缓存/请求合并 + OpenAPI）（见 `assets/tasks/0020-data-api-contract-hardening/TODO.md:7`、`assets/tasks/0020-data-api-contract-hardening/TODO.md:26`、`assets/tasks/0020-data-api-contract-hardening/TODO.md:27`）。这属于 **任务文档漂移**，需要通过证据补齐或重新定级到 In Progress。

本任务（0027）不是新增功能，而是把上述“剩余稳定性工作”收敛成一条能执行、能验收、能回滚的路线图，并把 tasks 文档状态对齐为真实状态，避免后续继续出现“索引 Done 但 TODO 未闭环”的多世界语义。

## 2) 约束矩阵（Constraints）

| 约束 | 影响 | 策略 |
|:---|:---|:---|
| tasks 是唯一真相源 | 文档漂移会直接误导执行与验收 | 以 `STATUS.md` 的证据为准反推索引/ TODO 勾选 |
| 敏感信息不能进入仓库 | DSN 密码/Token/Service Account JSON 不得写入任务证据 | `STATUS.md` 只能记录“已设置/已脱敏”的事实，不记录明文 |
| 需要可回滚 | 稳定性改动多为边界/失败语义 | Phase 级别提交 + `git revert` 回滚协议 |
| “正确性 > 安全性 > 可靠性 > 性能 > 可维护性” | 优先级不能反转 | 每一阶段必须先过 correctness/security 门禁再谈优化 |

## 3) 风险量化表（Risk Register）

| 风险点 | 严重程度 | 触发信号（Signal） | 缓解方案（Mitigation） |
|:---|:---:|:---|:---|
| 采集遇 418 ban 进入重启风暴，延长 ban 并制造数据缺口 | High | `418 ... IP banned until ...` 频繁刷屏；daemon 不断重启 ws | 执行 `0018`：ban 识别 + 全局退避 + ban-aware 自愈 |
| Sheets 弱网抖动导致导出失败/配额浪费 | High | `SSLError/ConnectionResetError`；prune_tabs 频繁触发 | 执行 `0012`：读请求重试 + prune 调度化 + 列宽快照 CLI |
| SQLite 残留导致“单 PG”口径失真，运维/备份困难 | Medium | `find . -name "*.db"` 发现运行依赖；`rg import sqlite3` 命中核心服务 | 执行 `0015 P2`：清理残留路径 + 文档同步 |
| Query Service 缺少 statement_timeout，慢查询拖死线程/连接池 | Medium | DB 慢查询时请求超时飙升；连接数耗尽 | 执行 `0025 P2`：statement_timeout + 故障注入验证 |
| sys.path 运行时注入导致部署/测试脆弱（路径变化即炸） | Medium | `rg "sys.path.insert" services` 命中多处 | 执行 `0025 P2`：收敛到单点入口或改包化/部署 PYTHONPATH |
| tasks 索引/状态漂移导致“看起来 Done，实际没做完” | Medium | INDEX=Done 但 TODO 未勾选或 STATUS 无证据 | 在 0027 中进行“文档对齐收敛” |

## 4) 假设与证伪（Assumptions & Falsification）

> 目标：避免“按想象推进”。每条假设都给出一条验证命令。

1) 假设：剩余稳定性工作主要集中在 `0012/0018/0015(P2)/0025(P2)`  
   - 证伪：`rg -n "\\| 00(12|15|18|24|25) \\|" assets/tasks/INDEX.md`
2) 假设：Query Service P0/P1 已通过门禁，当前主要是 P2 收口  
   - 证伪：`sed -n '1,120p' assets/tasks/0025-query-service-production-hardening/TODO.md`
3) 假设：`0020` 存在文档漂移（INDEX Done 但 TODO 未闭环）  
   - 证伪：`nl -ba assets/tasks/0020-data-api-contract-hardening/TODO.md | sed -n '1,40p'`
4) 假设：执行路线图不会要求新增基础设施（仅代码与配置收敛）  
   - 证伪：审查 `assets/tasks/0012-*/PLAN.md`、`assets/tasks/0018-*/PLAN.md` 是否引入外部依赖

