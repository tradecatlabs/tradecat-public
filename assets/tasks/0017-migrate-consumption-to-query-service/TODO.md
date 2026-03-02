# TODO：可执行清单（按优先级）

> 说明：本任务新增硬约束为“只保留新逻辑”，因此所有步骤都以“删除旧直连与回退”为 Gate 条件之一。

- [ ] P0: 快照提交（执行前止损点） | Verify: `git status --porcelain` 为空或可解释 | Gate: `git commit -m \"chore: snapshot before enforcing query-service-only\"`

- [ ] P0: 盘点 consumption 直连 PG 命中点清单 | Verify: `rg -n \"psycopg|psycopg_pool|FROM\\s+tg_cards|tg_cards\\.|FROM\\s+market_data|market_data\\.\" services/consumption -S` | Gate: 输出命中列表并标注“允许/不允许”

- [ ] P0: api-service 增加 `/api/v1` Query Service 路由骨架 | Verify: `rg -n \"api/v1\" services/consumption/api-service/src -S` 有命中 | Gate: `curl -sS http://127.0.0.1:8088/api/v1/health | jq .success`
- [ ] P0: api-service 实现统一时间模块（UTC 解析+输出） | Verify: `pytest -q services/consumption/api-service/tests -k time` | Gate: 覆盖 `Z/+00:00/无时区` 三类输入
- [ ] P0: api-service 实现“有效行过滤”模块 | Verify: `pytest -q services/consumption/api-service/tests -k filter` | Gate: 占位/全空行不出现在 `/v1` 输出
- [ ] P0: api-service 实现 `/api/v1/dashboard`（wide/long） | Verify: `curl -sS \"http://127.0.0.1:8088/api/v1/dashboard?intervals=5m,15m,1h,4h,1d,1w&shape=wide\" | jq '.success'` | Gate: 输出包含 `ts_utc/ts_ms`
- [ ] P0: api-service 实现 `/api/v1/symbol/{symbol}/snapshot` | Verify: `curl -sS \"http://127.0.0.1:8088/api/v1/symbol/BTCUSDT/snapshot?intervals=5m,15m,1h,4h,1d,1w\" | jq '.success'` | Gate: 输出分 panel 且周期齐全（缺失用 null）

- [ ] P0: api-service 删除 indicator router 动态 import TG provider | Verify: `rg -n \"spec_from_file_location|sys\\.path\\.insert\\(.*telegram-service\" services/consumption/api-service/src/routers/indicator.py -S` 无命中 | Gate: 旧 `/api/indicator/snapshot`（如保留）内部转调 query 层

- [ ] P0: telegram-service 重写 data_provider 为 HTTP（无 psycopg） | Verify: `rg -n \"psycopg|PgRankingDataProvider\" services/consumption/telegram-service/src/cards/data_provider.py -S` 无命中 | Gate: `python3 -m py_compile services/consumption/telegram-service/src/bot/app.py`
- [ ] P0: telegram-service 删除排行榜服务 fallback 路径 | Verify: `rg -n \"回退旧逻辑|fallback|handler\\.get_\" services/consumption/telegram-service/src/cards/排行榜服务.py -S` 无命中 | Gate: 运行一张卡片可成功渲染（本地日志无异常栈）
- [ ] P0: telegram-service 移除 requirements 中 psycopg | Verify: `rg -n \"psycopg\" services/consumption/telegram-service/requirements*.txt -S` 无命中 | Gate: `pip install -r services/consumption/telegram-service/requirements.txt` 可完成（执行 Agent 自行验证）

- [ ] P0: sheets-service 幂等存储迁移到 Sheets（隐藏 tab/metadata） | Verify: `rg -n \"PgIdempotencyStore|psycopg\" services/consumption/sheets-service/src/idempotency.py -S` 无命中 | Gate: 连跑两次导出不重复写入（命中幂等）
- [ ] P0: sheets-service 移除 requirements 中 psycopg | Verify: `rg -n \"psycopg\" services/consumption/sheets-service/requirements*.txt -S` 无命中 | Gate: `python3 -m compileall -q services/consumption/sheets-service/src`

- [ ] P0: 更新 `.env.example`（新增 Query Service base url/token 与多 DSN） | Verify: `rg -n \"QUERY_SERVICE_BASE_URL|QUERY_PG_\" assets/config/.env.example -S` 有命中 | Gate: 文档说明与变量默认值可用
- [ ] P0: 更新 telegram/sheets README（数据源口径） | Verify: `rg -n \"DATABASE_URL.*tg_cards\" services/consumption/telegram-service/README.md services/consumption/sheets-service/README.md -S` 无命中 | Gate: README 指向 Query Service

- [ ] P0: verify/CI 门禁 enforce consumption 禁止直连 DB | Verify: `./scripts/verify.sh` | Gate: 通过；且在任意 consumption 目录加入 `import psycopg` 会失败

- [ ] P1: Query Service 多数据源注册表（domain→pool） | Verify: `curl -sS http://127.0.0.1:8088/api/v1/health | jq '.data.sources'` | Gate: 能显示 indicators/market/other 三类数据源状态
- [ ] P1: Query Service 缓存与慢查询红线 | Verify: 日志出现 `duration_ms/db_time_ms/cache_hit` | Gate: dashboard 在短时间内重复请求命中缓存

## Parallelizable（可并行）

- api-service 的 `time.py`/`filters.py` 单测可与 router 骨架并行。
- telegram-service 与 sheets-service 的“移除 psycopg”可并行（都依赖 Query Service 完成后再联调）。

