# ACCEPTANCE - stability-execution-roadmap

> 说明：本任务的验收以“任务闭环 + 证据留存 + 门禁通过”为核心。  
> 执行时必须把关键命令输出片段写入各任务自己的 `STATUS.md`，并同步更新 `assets/tasks/INDEX.md` 状态。

## A) Happy Path（成功路径）

1) **采集稳定性闭环**
   - `0018-stabilize-data-service-ban-backoff` 的 P0/P1 全部勾选完成。
   - 证据：`assets/tasks/0018-stabilize-data-service-ban-backoff/STATUS.md` 包含：
     - ban 识别与退避的日志样例（不含敏感信息）
     - 30 分钟观察期内无“重启风暴”的统计/片段
     - 相关服务 `make check` 或最小验证命令通过

2) **Sheets 导出稳定性闭环**
   - `0012-sheets-service-hardening` 的 P0 至少全部完成（P1/P2 可按任务定义推进）。
   - 证据：`assets/tasks/0012-sheets-service-hardening/STATUS.md` 包含：
     - 弱网重试覆盖验证（模拟或故障注入）
     - `prune_tabs` 调度化后 24h 日志计数对比（降噪/降频）
     - `--snapshot-col-widths` CLI 输出样例（不含敏感表格 ID）

3) **“单 PG”收口（禁止运行依赖 SQLite）**
   - `0015-unify-all-storage-to-postgres` 的 P2 三项全部完成并勾选：
     - `rg -n "import sqlite3" services` 空（允许外部仓库 `assets/repo/**` 例外）
     - `find . -name "*.db" -not -path "*/assets/repo/*"` 不再出现“运行期依赖”的 `.db`
     - README/运维文档只保留“迁移说明”，不再指示依赖 `.db`
   - 证据：`assets/tasks/0015-unify-all-storage-to-postgres/STATUS.md` 写入上述命令输出片段。

4) **Query Service 生产化 P2 收口**
   - `0025-query-service-production-hardening` 的 P2 两项全部完成并勾选（statement_timeout + sys.path 收敛）。
   - 证据：`assets/tasks/0025-query-service-production-hardening/STATUS.md` 写入：
     - statement_timeout 故障注入（`pg_sleep`）验证
     - `rg -n "sys\\.path\\.insert" services | wc -l` 前后对比与回归验证命令

5) **契约层文档对齐**
   - `0020-data-api-contract-hardening` 的未勾选项要么补齐证据并勾选，要么将任务状态回退为 In Progress 并明确原因（禁止“INDEX Done + TODO 未闭环”）。
   - 证据：`assets/tasks/0020-data-api-contract-hardening/STATUS.md` 更新，且 `assets/tasks/INDEX.md` 状态与其一致。

6) **全仓门禁通过**
   - `./scripts/verify.sh` ✅
   - 核心服务（至少 api-service、telegram-service、trading-service、data-service、sheets-service）`make check` ✅  
     > 若某服务没有 `make check`，必须在对应任务的 `TODO.md` 中写清替代的验证命令与 Gate。

## B) Edge Cases（至少 3 个边缘场景）

1) **无法在测试环境复现 418 ban**
   - 验收要求：必须提供可重复的“模拟 ban”验证路径（单测或最小脚本），确保退避逻辑被覆盖。
   - Gate：`0018` 的 `STATUS.md` 记录“模拟/单测覆盖”的证据。

2) **Sheets API 间歇性抖动**
   - 验收要求：必须覆盖 `SSLError/ConnectionResetError` 等瞬断，并证明不会导致无限重试/写入风暴。
   - Gate：`0012` 的 `STATUS.md` 含失败注入与最终成功/降级的证据。

3) **SQLite 清理误伤外部仓库**
   - 验收要求：任何清理命令都必须排除 `assets/repo/**`，并先 dry-run 生成清单再执行。
   - Gate：`0015` 的 `STATUS.md` 必须包含清单化证据（例如 `find ... -not -path "*/assets/repo/*"` 输出）。

4) **statement_timeout 误伤“正常慢查询”**
   - 验收要求：超时必须可配置（env），并对关键端点做回归冒烟（避免误判为“服务挂了”）。
   - Gate：`0025` 的 `STATUS.md` 记录默认值、覆盖方式与回归请求样例。

## C) Anti-Goals（禁止性准则）

- 不得在 tasks/STATUS 中写入任何明文密码、token、Service Account JSON 内容。
- 不得把“表结构变更/数据回填/大规模重算”夹带进本稳定性路线图（除非明确在相关任务范围内）。
- 不得用“静默降级/吞异常”来换取表面稳定；失败语义必须可观测、可定位。

