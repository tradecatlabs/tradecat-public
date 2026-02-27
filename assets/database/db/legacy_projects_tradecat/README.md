# legacy_projects_tradecat

这是从旧项目路径拷贝过来的 **低频/LF DDL 旧版快照**，用于对照与回溯（不要把它当成当前真相源）。

- 来源（历史备份路径示例）：`$LEGACY_TRADECAT_ROOT/assets/database/db`
- 拷贝时间：2026-02-17
- 内容：
  - `schema/*.sql`（001–007）
  - `setup_candle_notify_trigger.sql`

## 使用建议

- 当前仓库的“真相入口”是 `assets/database/db/stacks/{lf,hf}.sql`（见 `assets/database/db/README.md`）。
- 这里的文件 **不应** 被任何自动化脚本默认执行；只用于：
  - diff 对比（找出新旧 DDL 行为差异）
  - 复刻旧环境（明确你就是要跑旧版 DDL）
