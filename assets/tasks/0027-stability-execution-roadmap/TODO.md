# TODO - stability-execution-roadmap

> 规则：每一行遵循  
> `[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`  
> 严禁在任务证据中写入明文密码/Token/Service Account JSON。

## P0（必须优先）

- [ ] P0: 基线冻结（Phase 0） | Verify: `git rev-parse --short HEAD` | Gate: 把 HEAD 写入 `assets/tasks/0027-stability-execution-roadmap/STATUS.md`
- [ ] P0: 基线服务门禁 | Verify: `./scripts/verify.sh` | Gate: ✅ 通过；输出片段写入 `assets/tasks/0027-stability-execution-roadmap/STATUS.md`
- [ ] P0: 基线核心服务 check | Verify: `cd services/consumption/api-service && make check` | Gate: ✅ 通过（其余服务按各自任务门禁执行）

- [ ] P0: 执行 `0018`（ban/backoff）P0 清单 | Verify: `sed -n '1,40p' assets/tasks/0018-stabilize-data-service-ban-backoff/TODO.md` | Gate: `0018` 的 P0 项全部勾选 + `STATUS.md` 有证据
- [ ] P0: 执行 `0012`（Sheets 加固）P0 清单 | Verify: `sed -n '1,60p' assets/tasks/0012-sheets-service-hardening/TODO.md` | Gate: `0012` 的 P0 项全部勾选 + `STATUS.md` 有证据

## P1（重要）

- [ ] P1: `0015` 补齐 P0“SQLite 真实表结构提取”证据 | Verify: `sed -n '1,60p' assets/tasks/0015-unify-all-storage-to-postgres/TODO.md` | Gate: `assets/tasks/0015-unify-all-storage-to-postgres/TODO.md:8` 勾选且清单落盘
- [ ] P1: `0015` 完成 P2（移除 sqlite 残留/清理 .db/文档同步） | Verify: `sed -n '18,40p' assets/tasks/0015-unify-all-storage-to-postgres/TODO.md` | Gate: P2 三项勾选 + `./scripts/verify.sh` 通过

- [ ] P1: `0025` 完成 P2（statement_timeout + sys.path 收敛） | Verify: `sed -n '1,60p' assets/tasks/0025-query-service-production-hardening/TODO.md` | Gate: `assets/tasks/0025-query-service-production-hardening/TODO.md:21` 两项勾选 + `STATUS.md` 有故障注入证据

- [ ] P1: 对齐 `0020`（避免 INDEX=Done 但 TODO 未闭环） | Verify: `nl -ba assets/tasks/0020-data-api-contract-hardening/TODO.md | sed -n '1,40p'` | Gate: P0:7、P2:26-27 要么补齐并勾选，要么把 INDEX 状态回退为 In Progress 并在 `STATUS.md` 写清原因

- [ ] P1: 对齐 `0024`（避免 P1/P2 漂移） | Verify: `nl -ba assets/tasks/0024-query-service-security-reliability-hardening/TODO.md | sed -n '1,80p'` | Gate: 若已被 0025 覆盖，则在 0024 中补齐证据并勾选/标记 Done；若仍未做，明确剩余项并纳入 0025/新任务

## P2（收尾）

- [ ] P2: 更新 `assets/tasks/INDEX.md` 状态与真实进度一致 | Verify: `rg -n \"\\| 00(12|15|18|20|24|25|27) \\|\" assets/tasks/INDEX.md` | Gate: 每个 Done 任务都有对应 `STATUS.md` 证据
- [ ] P2: 统一“端到端冒烟清单”并落盘到 `assets/tasks/0027-stability-execution-roadmap/STATUS.md` | Verify: `ls -la assets/tasks/0027-stability-execution-roadmap` | Gate: `STATUS.md` 含 ≥10 条关键命令与断言

## Parallelizable（可并行）

- `0018`（采集 ban/backoff）与 `0012`（Sheets 加固）可并行推进，但最终必须串行过全仓门禁。
- `0015 P2` 与 `0025 P2` 可并行推进（一个偏存储清理，一个偏 Query Service 生产化）。

