# TODO

> 每一项都必须“可验证”，并写明 Gate（验收门槛）。

## P0（必须）

- [ ] P0: Stage 0 盘点全仓库 `libs` 引用（import/path/systemd/docs） | Verify: `rg -n "import\\s+libs\\b|from\\s+libs\\b|libs/" -S . | wc -l` | Gate: 形成清单并写入 `STATUS.md`
- [ ] P0: Stage 1 执行 `libs/external` → `assets/repo`（目录当前被 `.gitignore` 忽略，使用 `mv` 迁移） | Verify: `ls -la assets/repo | head` | Gate: `ACCEPTANCE.A1`
- [ ] P0: Stage 1 清理运行时引用（若存在）并确保 runtime 侧 `libs/external` 为 0 | Verify: `rg -n "libs/external" -S services scripts config docs | wc -l` | Gate: `ACCEPTANCE.A2`
- [ ] P0: Stage 1 基线验证（不允许破坏现有启动链路） | Verify: `./scripts/check_env.sh` | Gate: `ACCEPTANCE.A3`

## P1（高风险阶段：必须有兼容层）

- [ ] P1: 选择兼容层策略（symlink vs Python re-export），并写入 `STATUS.md` 决策 | Verify: `cat assets/tasks/0013-rename-libs-to-assets/STATUS.md | rg -n "compat"` | Gate: 决策可追溯
- [ ] P1: Stage 2 执行 `libs/` → `assets/`（带兼容层） | Verify: `python3 -c "import libs.common; print('ok')"` | Gate: `ACCEPTANCE.B1`
- [ ] P1: 迁移配置模板与脚本默认路径（`libs/database` → `assets/database`） | Verify: `rg -n "libs/database" -S config/.env.example scripts services | head` | Gate: 引用下降且无运行时断裂
- [ ] P1: 启动链路验证（顶层脚本） | Verify: `./scripts/start.sh start && ./scripts/start.sh status` | Gate: `ACCEPTANCE.B4`

## P2（收尾）

- [ ] P2: 文档同步（README/AGENTS/analysis docs） | Verify: `rg -n "libs/" -S README.md AGENTS.md docs | head` | Gate: 文档不误导
- [ ] P2: 移除兼容层（仅在确认所有引用已迁移后） | Verify: `rg -n "\\bimport\\s+libs\\b|\\bfrom\\s+libs\\b" -S services scripts | head` 输出为空 | Gate: 无 `ModuleNotFoundError`
