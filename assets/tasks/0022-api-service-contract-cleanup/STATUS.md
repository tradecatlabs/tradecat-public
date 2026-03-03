# STATUS - 0022 api-service-contract-cleanup

## 状态机

- Status: Not Started
- Owner: (待分配)
- Updated: 2026-03-03

## 已执行命令记录（Evidence Log）

> 按要求记录：命令 + 关键输出片段（禁止粘贴敏感 DSN/密钥）。

- `rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/{coins,base_data,signal,indicator}.py -S`
  - 仍存在路由直连散落（见 CONTEXT.md）
- `nl -ba services/consumption/api-service/src/utils/errors.py | sed -n '1,60p'`
  - `error_response` 无 extra 扩展位
- `rg -n "\\| 0015 \\|" assets/tasks/INDEX.md`
  - Index 与 0015 STATUS 存在漂移

## 当前阻塞（Blocked）

- 无。

