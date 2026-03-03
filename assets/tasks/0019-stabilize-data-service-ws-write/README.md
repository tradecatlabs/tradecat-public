# 0019 - stabilize-data-service-ws-write

## Why（价值）

`data-service` 的 WS K 线采集曾出现“DB 新鲜度持续陈旧 → daemon 周期性自愈重启 ws → 只能靠 REST 补齐”的不稳定状态，导致：

- WS 失去“低成本持续收流”的意义，反而依赖 REST（更容易触发 ban / 配额问题）
- daemon 自愈重启风暴影响整体观测与稳定性
- WS 与 backfill 对同一 candle 的写入互相覆盖，丢失来源与字段

本任务将 WS 写入恢复为“按分钟稳定落库”，并收敛依赖漂移带来的 WS 不可用风险。

## In Scope（范围）

- 修复 WSCollector 批量刷新逻辑：确保同一分钟多币种推送后会触发 flush，而不是“永远等不到窗口空闲”。
- 调整 cryptofeed 回调桥接：支持 async 回调，避免事件循环/任务调度导致的写入不落库。
- backfill/zip 导入写入改为“仅插入不覆盖”：避免 REST/ZIP 覆盖 WS 行（WS 优先）。
- 初始化/安装依赖优先使用 `requirements.lock.txt`，避免依赖漂移（尤其是 `websockets` 版本）导致 WS 链路再次崩坏。

## Out of Scope（不做）

- 不改动数据库 schema / 表结构。
- 不对全仓库做 ruff 类型提示升级/格式化（仅做必要代码修复）。
- 不引入新的第三方依赖。

## 阅读/执行顺序

1. `CONTEXT.md`：问题现象与根因证据
2. `PLAN.md`：方案与权衡
3. `TODO.md`：可执行步骤
4. `ACCEPTANCE.md`：验收口径
5. `STATUS.md`：执行记录与结果

