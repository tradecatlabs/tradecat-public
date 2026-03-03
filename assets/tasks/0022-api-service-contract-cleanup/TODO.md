# TODO - 执行清单（可并行标注）

> 每行格式：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

## P0（必须）

[ ] P0: 冻结现状证据（get_pg_pool 散落点） | Verify: `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/{coins,base_data,signal,indicator}.py -S` | Gate: 有匹配
[ ] P0: 扩展 `error_response` 支持 `extra`（保持兼容） | Verify: `rg -n "def error_response\\(.*extra" services/consumption/api-service/src/utils/errors.py -S` | Gate: 有匹配且旧调用不需改
[ ] P0: futures 缺表返回补齐 `missing_table` | Verify: `curl -s -m 2 "http://127.0.0.1:8088/api/futures/ohlc/history?symbol=BTC&interval=6h&limit=1" | head` | Gate: JSON 含 `missing_table`
[ ] P0: coins/base_data/signal/indicator 改用 datasources(INDICATORS) | Verify: `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/{coins,base_data,signal,indicator}.py -S` | Gate: 无匹配
[ ] P0: 单测补齐（missing_table + 路由无直连） | Verify: `cd services/consumption/api-service && make test` | Gate: 全绿
[ ] P0: ruff E/F 快检（CI 同款） | Verify: `services/consumption/api-service/.venv/bin/ruff check services/ --ignore E501,E402 --select E,F` | Gate: All checks passed!

## P1（重要）

[ ] P1: tasks 状态对齐（0015/0020） | Verify: `rg -n "\\| 0015 \\|" assets/tasks/INDEX.md && sed -n '1,20p' assets/tasks/0015-unify-all-storage-to-postgres/STATUS.md` | Gate: 状态一致
[ ] P1: 记录动态冒烟证据（重启后关键 curl） | Verify: `cd services/consumption/api-service && ./scripts/start.sh status` | Gate: API 运行中且日志无异常

## P2（优化）

[ ] P2: 统一缺表/参数错误输出 helper（减少重复） | Verify: `rg -n "missing_table" services/consumption/api-service/src/routers -S` | Gate: 逻辑集中可复用

## 可并行（Parallelizable）

- P0: `error_response(extra)` 与 “路由连接池替换” 可并行
- P0: “测试补齐” 可与路由替换并行（在接口可跑后）

