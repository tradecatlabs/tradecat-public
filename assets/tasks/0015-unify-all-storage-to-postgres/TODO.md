# TODO（执行清单）

> 规则：每一步都必须执行 Verify；Gate 不满足不得进入下一步。

## P0（必须做）

- [ ] P0: 冻结现状清单（SQLite/PG 使用点盘点） | Verify: `rg -n "import sqlite3|sqlite3\\.connect" services` | Gate: 输出文件清单与用途分层（指标/状态/幂等/外部仓库）
- [ ] P0: 提取 SQLite 真实表结构（指标库 + 状态库） | Verify: `sqlite3 assets/database/services/telegram-service/market_data.db ".tables"` | Gate: 生成 “表名→字段→类型” 清单（落到 `assets/docs/analysis/` 或任务目录）
- [ ] P0: 设计并新增 `signal_state` DDL | Verify: `psql "$DATABASE_URL" -f assets/database/db/schema/022_signal_state.sql` | Gate: `\\dt signal_state.*` 可见且含必要索引
- [ ] P0: 设计并新增 `sheets_state` DDL | Verify: `psql "$DATABASE_URL" -f assets/database/db/schema/023_sheets_state.sql` | Gate: `\\dt sheets_state.*` 可见
- [ ] P0: 实现 state/幂等 PG 存储模块（接口不变，内部换后端） | Verify: 单元测试/最小脚本写入+读取 | Gate: 不依赖任何 `.db` 文件即可跑通
- [ ] P0: 提供 SQLite→PG 一次性迁移脚本（含 dry-run） | Verify: `--dry-run` 只读不写；`--apply` 写入后对账 | Gate: 对账通过（count/hash）

## P1（应做）

- [ ] P1: trading-service 默认写端切 `pg`（保留 dual 作为回滚） | Verify: 跑一次计算周期，PG 表有新增 | Gate: 写入延迟不显著劣化
- [ ] P1: telegram-service/api-service/sheets-service 默认读端切 `pg` | Verify: 关键接口/导出结果一致 | Gate: 影子读对账通过
- [ ] P1: ai-service 指标读取切 PG | Verify: AI 报告生成链路可跑通 | Gate: 无 sqlite 依赖

## P2（收敛/清理）

- [ ] P2: 移除 SQLite 代码路径与遗留脚本（保留迁移工具） | Verify: `rg -n "import sqlite3" services` 为空 | Gate: CI/本地验证全绿
- [ ] P2: 清理 `.db` 产物与远端快照逻辑（remote_db） | Verify: `find . -name "*.db" -not -path "*/assets/repo/*"` | Gate: 运行不依赖本地 DB 文件
- [ ] P2: 文档同步（README/架构图/运维口径） | Verify: `rg -n "market_data\\.db" README* assets/docs` 仅保留“历史/迁移说明” | Gate: 文档与代码一致

## 可并行（Parallelizable）

- DDL 设计（P0）与 迁移脚本骨架（P0）可并行推进。
- 消费端切读（P1）与 AI 切读（P1）可并行，但需统一验收对账口径。

