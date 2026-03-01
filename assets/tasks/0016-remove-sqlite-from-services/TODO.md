# TODO：可执行清单（按优先级）

- [ ] P0: 快照提交（执行前止损点） | Verify: `git status --porcelain` 为空或可解释 | Gate: `git commit -m \"chore: snapshot before removing sqlite remnants\"`
- [ ] P0: 锁定服务侧 SQLite 命中点清单 | Verify: `rg -n \"sqlite3|aiosqlite|sqlite_engine|SQLiteSignalEngine|market_data\\.db\" services/compute/signal-service services/consumption/api-service` | Gate: 输出命中列表（用于对照修复）

- [ ] P0: signal-service：修正事件默认 source（sqlite->pg） | Verify: `rg -n \"source: str = \\\"sqlite\\\"\" services/compute/signal-service/src/events/types.py` 无命中 | Gate: `pytest -q` 通过
- [ ] P0: signal-service：删除/替换 sqlite_engine 测试用例 | Verify: `rg -n \"sqlite_engine|SQLiteSignalEngine\" services/compute/signal-service/tests` 无命中 | Gate: `cd services/compute/signal-service && make test`
- [ ] P0: signal-service：重写 history 测试为 unit（fake psycopg） | Verify: `rg -n \"history\\.db\" services/compute/signal-service/tests` 无命中 | Gate: `cd services/compute/signal-service && make test`

- [ ] P0: api-service：更新 docs 数据源映射（SQLite->PG） | Verify: `rg -n \"\\| /indicator/\\* \\| SQLite\" services/consumption/api-service/docs/改动1.md` 无命中 | Gate: 文档表格显示 tg_cards/signal_state

- [ ] P1: sheets-service：清理/迁移 remote sqlite 遗留文件（不再出现 market_data.db 快照） | Verify: `find services/consumption/sheets-service -path '*/data/*' -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3'` 为空 | Gate: `cd services/consumption/sheets-service && make start --once` 可运行
- [ ] P1: trading-service：删除/迁移历史 market_data.db 副本 | Verify: `find services/compute/trading-service -path '*/libs/*' -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3'` 为空 | Gate: `cd services/compute/trading-service && make start --once` 可运行

- [ ] P1: 仓库级验收扫描（限定核心服务目录） | Verify: `rg -n --hidden --no-ignore-vcs \"sqlite3|aiosqlite|sqlite_master\" services/consumption/api-service/src services/consumption/sheets-service/src services/consumption/telegram-service/src services/consumption/vis-service/src services/compute/ai-service/src services/compute/signal-service/src services/compute/trading-service/src` | Gate: 无命中

- [ ] P2: nofx-dev：明确外部镜像定位并避免验收误伤 | Verify: `rg -n \"nofx-dev\" README.md assets/config/.env.example` | Gate: 文档明确其非核心链路；验收扫描命令排除 nofx-dev
- [ ] P2: 选择性严格化（可选）：将 nofx-dev 迁出 services/（move 到 assets/repo/） | Verify: `test -d services/consumption/nofx-dev` 不存在 | Gate: README/脚本引用全部更新

## Review（执行后复盘要点）

- 是否仍存在“服务运行时”会打开 `.db` 的路径？
- 是否把 SQLite 仅限定在迁移工具/外部镜像范围内？
- 是否在 README/服务 docs 中形成了“单 PG”一致口径？

