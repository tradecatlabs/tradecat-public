# TODO - 执行清单（可并行标注）

> 每行格式：`[ ] Px: <动作> | Verify: <验证手段> | Gate: <准入>`

## P0（必须）

[ ] P0: 冻结现状与基线证据（保存关键接口样例） | Verify: `curl -s http://127.0.0.1:8088/api/v1/health | head` | Gate: 输出包含 `success`
[x] P0: 建立 card_id 清单（从 TG registry 提取） | Verify: `rg -n \"card_id=\\\"\" services/consumption/telegram-service/src/cards -S | wc -l` | Gate: 行数 > 20
[x] P0: 新增契约模块 `assets/common/contracts/cards_contract.py` | Verify: `test -f assets/common/contracts/cards_contract.py` | Gate: 文件存在且可被 import
[x] P0: api-service 新增 `GET /api/v1/capabilities` | Verify: `curl -s http://127.0.0.1:8088/api/v1/capabilities | head` | Gate: 返回 `cards`
[x] P0: api-service 新增 `GET /api/v1/cards/{card_id}`（排行榜数据） | Verify: `curl -s \"http://127.0.0.1:8088/api/v1/cards/atr_ranking?interval=15m&limit=5\" | head` | Gate: 响应不含 `*.py`
[x] P0: 强化 `GET /api/v1/dashboard` 支持 `cards/intervals/symbols/shape` | Verify: `curl -s \"http://127.0.0.1:8088/api/v1/dashboard?cards=atr_ranking&intervals=15m\" | head` | Gate: 响应包含 `rows`
[x] P0: 迁移 telegram-service 数据读取到新端点（移除 indicators 依赖） | Verify: `rg -n \"api/v1/indicators\" services/consumption/telegram-service/src -S` | Gate: 无匹配
[x] P0: 迁移 sheets-service（或通过复用 TG provider 间接迁移） | Verify: `rg -n \"api/v1/indicators\" services/consumption/sheets-service/src -S` | Gate: 无匹配
[x] P0: api-service 测试补齐（契约端点单测/冒烟） | Verify: `cd services/consumption/api-service && make test` | Gate: 全绿

## P1（重要）

[x] P1: futures 路由改用 datasources 多 DSN 抽象 | Verify: `rg -n \"get_pg_pool\\(\" services/consumption/api-service/src/routers -S` | Gate: futures 路由不再调用 `get_pg_pool`
[x] P1: futures `*_last` 缺表降级策略 | Verify: 断表/空表时接口返回 4xx/可诊断错误码 | Gate: 不出现 500
[ ] P1: 输出类型/单位标准化（decimal/string） | Verify: `services/consumption/api-service/docs/API_EXAMPLES.md` 更新 | Gate: 文档与实际一致
[ ] P1: 旧端点标记 deprecated + token 保护（仅内网调试） | Verify: 未带 token 调用被拒 | Gate: 对外不可误用

## P2（优化）

[ ] P2: 服务端缓存/请求合并（降低多周期/多卡片 N+1） | Verify: 压测 p95 不劣化 | Gate: p95 ≤ 基线 * 1.2
[ ] P2: OpenAPI 文档补齐（契约端点） | Verify: 访问 `/docs` 可见新端点 | Gate: 端点描述完整

## 可并行（Parallelizable）

- P0: “契约模块” 与 “api-service 新端点” 可并行
- P0: “telegram-service 迁移” 与 “api-service 单测” 可并行（在端点可用后）
