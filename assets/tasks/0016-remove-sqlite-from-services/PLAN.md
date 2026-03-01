# PLAN：服务侧彻底去 SQLite（实施路径）

## 方案对比（至少两种）

### 方案 A（推荐）：核心服务去 SQLite；迁移脚本/外部镜像保留

**做法**
- 只对核心服务目录（api/sheets/telegram/vis/ai/signal/trading）执行“去 SQLite”：
  - 清理错误/过期测试
  - 修正默认字段与文档口径
  - 删除服务目录内遗留 `.db` 文件（或迁到 artifacts）
- 迁移脚本仍保留在 `scripts/`，作为 legacy 数据导入工具
- `nofx-dev` 保持“外部镜像/预览”定位，不强行迁移其内部存储（但必须在验收扫描中排除/或移出 services，见 P2）

**Pros**
- 影响最小，最符合“主链路单 PG”目标
- 可以快速把“误导性残留”清零，降低运维误判

**Cons**
- 仓库仍会出现 SQLite 相关代码（迁移脚本、nofx-dev 外部镜像）

### 方案 B（最严格）：全仓去 SQLite（含 nofx-dev / fate-service / 迁移脚本）

**做法**
- 删除/迁移所有 SQLite 代码与文件，所有数据持久化统一 PG

**Pros**
- “字面意义上的彻底”去 SQLite

**Cons**
- 风险与成本极高：nofx-dev 是独立系统，迁移存储会变成新项目
- 会丢失 SQLite 导入/恢复能力（除非重写为 PG-only 导入器）

**决策**
- 默认选 **方案 A**：保证核心服务运行时完全不依赖 SQLite；把 SQLite 限定在“工具/外部镜像”范围内。

## 数据流（变更后目标态）

```text
TimescaleDB (market_data.*)
   |
   v
trading-service (compute)  --->  PostgreSQL: tg_cards.*
                                     |
                                     +--> telegram-service (cards)
                                     +--> api-service (REST)
                                     +--> ai-service (full fetch)
                                     +--> sheets-service (Sheets export)

signal-service (compute)  --->  PostgreSQL: signal_state.*
sheets-service (consumption) ---> PostgreSQL: sheets_state.*
```

## 原子变更清单（文件级，不写具体代码）

### services/compute/signal-service
- 修正 `SignalEvent.source` 默认值与反序列化默认值（sqlite -> pg）
- 移除/替换 tests 内 sqlite_engine 相关用例
- 将 history 相关测试改为 unit（fake psycopg.connect / fake conn+cursor），避免真实 PG 依赖

### services/consumption/api-service
- 更新 `docs/改动1.md`：移除“SQLite 为运行时数据源”的描述；修正数据源映射表为 PG（tg_cards/signal_state）
- 清理代码注释中“可回退 sqlite”的误导性描述（若无实现）

### services/consumption/sheets-service
- 明确 `data/remote/market_data.db` 与 `local_meta.json` 中 `remote_db.*` 为历史遗留：删除遗留文件或迁移到 artifacts（并确保 src 不再生成/读取）
- README 中强调：幂等与指标源均为 PG

### services/compute/trading-service
- 删除/迁移 `libs/.../market_data.db` 历史副本（确保无代码引用）
- README/错误文案中保持 “021_tg_cards_sqlite_parity.sql” 仅表示“表名对齐历史”，不是运行时 SQLite 依赖

### services/consumption/telegram-service / vis-service / compute/ai-service
- 仅做文档/注释口径收敛（如存在误导性 sqlite 描述则清理）

### services/consumption/nofx-dev（P2）
- 选择其一：
  1) 保持外部镜像不动，但从“核心服务验收扫描”中排除，并在 README 强化其外部定位
  2) 将目录迁移到 `assets/repo/`（作为外部工程镜像），从 `services/` 中移除
  3) 进行真正的存储迁移（SQLite -> PG）（高成本，单独任务）

## 回滚协议

1. 在执行任何删除/重构前，先做一次快照提交（见 TODO 的 P0）。
2. 若出现服务启动失败或验收命令无法通过：
   - 直接 `git revert <commit>` 或 `git reset --hard <sha>` 回到快照点
3. 对“删除遗留 .db 文件”的回滚：
   - 从 `git checkout -- <path>` 或从备份工件目录恢复

