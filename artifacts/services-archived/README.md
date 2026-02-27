# artifacts/services-archived/（历史服务归档区）

本目录用于存放**已归档**的历史服务代码，目标是：

- 避免污染当前主干（`./scripts/start.sh`、`./scripts/verify.sh`、`ruff check services/` 等默认链路只关注 `services/**`）。
- 保留可追溯的实现参考（对照历史设计/字段/采集策略）。

约束：

- 归档区代码不保证可运行、不保证依赖可装、不进入默认启动链路。
- 如需“重新启用”，应迁回 `services/**` 并同步更新文档与启动脚本。

目录示意：

```
artifacts/
└── services-archived/
    └── ingestion/
        └── data-service/   # 旧版采集服务（已归档，不再默认启用）
```
