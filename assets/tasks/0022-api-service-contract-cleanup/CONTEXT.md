# CONTEXT - 现状证据与风险图谱

## 现状（可复核证据）

### 1) api-service 路由仍存在 `get_pg_pool()` 直连散落（未统一 datasources）

命中点（精确到行号）：

- `services/consumption/api-service/src/routers/coins.py:42`
- `services/consumption/api-service/src/routers/base_data.py:69`
- `services/consumption/api-service/src/routers/signal.py:18`
- `services/consumption/api-service/src/routers/indicator.py:243`
- `services/consumption/api-service/src/routers/indicator.py:278`

证据命令：

```bash
rg -n "get_pg_pool\\(" services/consumption/api-service/src/routers/{coins,base_data,signal,indicator}.py -S
```

### 2) 已存在 datasources 抽象，但未被上述路由复用

数据源定义（含默认回退到 `DATABASE_URL`）：

- `services/consumption/api-service/src/query/datasources.py:20-22`
  - `INDICATORS` / `MARKET` 默认回退 `DATABASE_URL`
  - `OTHER` 当前无默认（留空会 `missing_dsn:QUERY_PG_OTHER_URL`）

证据命令：

```bash
nl -ba services/consumption/api-service/src/query/datasources.py | sed -n '1,40p'
```

### 3) 错误响应 `error_response` 无扩展位，无法输出结构化诊断字段

- `services/consumption/api-service/src/utils/errors.py:28-35`

证据命令：

```bash
nl -ba services/consumption/api-service/src/utils/errors.py | sed -n '1,60p'
```

### 4) tasks 状态漂移：Index 与任务 STATUS 不一致

- `assets/tasks/INDEX.md:19` 显示 `0015` 为 `Not Started`
- `assets/tasks/0015-unify-all-storage-to-postgres/STATUS.md` 显示 `状态：In Progress`

证据命令：

```bash
rg -n "\\| 0015 \\|" assets/tasks/INDEX.md
sed -n '1,40p' assets/tasks/0015-unify-all-storage-to-postgres/STATUS.md
```

### 5) `0020` 任务：STATUS 说 P0 完成，但 TODO 未打勾（可读性与审计风险）

- `assets/tasks/0020-data-api-contract-hardening/STATUS.md`：`Status: In Progress（P0 已完成）`
- `assets/tasks/0020-data-api-contract-hardening/TODO.md`：P0 项仍是 `[ ]`

证据命令：

```bash
sed -n '1,40p' assets/tasks/0020-data-api-contract-hardening/STATUS.md
sed -n '1,40p' assets/tasks/0020-data-api-contract-hardening/TODO.md
```

## 问题本质（Root Cause）

1) **连接治理未收口**：同一服务内存在 `get_pg_pool()` 与 `datasources.get_pool()` 两套连接逻辑，导致“多 DSN/脱敏/探活/连接参数”无法全局一致。  
2) **诊断信息不可机器消费**：缺表等错误只有字符串信息，无法被监控系统/前端做结构化分类与聚合。  
3) **项目记忆漂移**：tasks 的状态不一致，会在多人协作或跨环境回滚时引发误判。

## 风险量化表

| 风险点 | 严重程度 | 触发信号 (Signal) | 缓解方案 (Mitigation) |
| :--- | :--- | :--- | :--- |
| 改 `error_response` 破坏兼容 | High | 旧调用点报 TypeError / JSON 字段变化 | 仅新增可选参数 `extra=None`，保持原返回完全不变 |
| `OTHER` DSN 无默认导致启动失败 | Medium | health/capabilities 报 `missing_dsn:QUERY_PG_OTHER_URL` | 本任务不强制使用 `OTHER`；优先复用 `INDICATORS`（默认回退 `DATABASE_URL`） |
| 旧端点变更引发外部脚本解析失败 | Medium | 外部脚本依赖 `msg` 文本 | 仅新增字段，不删除/重命名任何既有字段 |
| tasks 修改误导执行顺序 | Low | 任务状态/勾选错误 | 每次更新同步写入 `STATUS.md` 证据与时间戳 |

## 假设与证伪（最小假设）

1) **假设**：`coins/base_data/indicator` 读取的库与 `INDICATORS` 指向同一 DSN（默认 `DATABASE_URL`），不需要新增 env。  
   **证伪命令**（执行 Agent 运行）：

```bash
curl -s -m 2 http://127.0.0.1:8088/api/v1/health | head
```

2) **假设**：`/api/v1/indicators/*` 已仅作为内网调试端点（生产需配置 `QUERY_SERVICE_TOKEN` 才可用）。  
   **证伪命令**：

```bash
curl -s -m 2 "http://127.0.0.1:8088/api/v1/indicators/基础数据同步器.py?interval=15m&mode=raw&limit=1" | head
```

