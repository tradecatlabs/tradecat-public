# ACCEPTANCE

> 验收必须以“可执行命令 + 可观察输出”为证据，禁止凭感觉。

## A. Stage 1（`libs/external` → `assets/repo`）验收

- A1（结构）：`assets/repo` 存在且包含原 `libs/external` 的顶层子目录  
  - Verify: `ls -la assets/repo | head`
- A2（引用清零）：仓库中不再出现 `libs/external` 硬编码引用  
  - Verify: `rg -n "libs/external" -S services scripts config docs | wc -l` = 0  
- A3（无副作用）：核心验证脚本可执行通过  
  - Verify: `./scripts/check_env.sh 2>&1 | rg -n "libs/external|assets/repo" ; echo $?` 结果为 `1`（表示无匹配）  

## B. Stage 2（`libs/` → `assets/`，带兼容层）验收

- B1（兼容性）：旧 import 仍可用（兼容期）  
  - Verify: `python3 -c "import libs.common; print('ok')"`
- B2（新路径可用）：新路径 import 可用（若采用 re-export 方案）  
  - Verify: `python3 -c "import assets.common; print('ok')"`（仅当方案要求存在该包）
- B3（路径口径）：配置模板/脚本中的默认数据库路径已迁移且脚本仍能找到文件  
  - Verify: `rg -n "libs/database" -S config/.env.example scripts services docs | wc -l` 应显著下降且不包含运行时必需引用  
- B4（最小启动验证）：至少启动一次核心服务链路（按仓库现有启动脚本口径）  
  - Verify: `./scripts/start.sh start && ./scripts/start.sh status`

## C. Edge Cases（至少 3 个）

- C1：从子目录启动服务（`cwd` 非仓库根）仍能找到路径  
  - Verify: `cd services/consumption/api-service && ./scripts/start.sh start`
- C2：systemd service 文件中的路径不再指向旧 `libs/...`  
  - Verify: `rg -n "libs/" -S services/**/scripts/*.service`
- C3：文档/示例命令中的路径不误导（README/AGENTS/分析文档）  
  - Verify: `rg -n "libs/" -S README.md AGENTS.md docs | head`

## Anti-Goals（禁止性准则）

- 不允许通过“删除功能/跳过检查”来让命令通过。
- 不允许把问题掩盖为“只在某些环境不跑”；必须明确是否依赖 symlink，并给出无 symlink 方案。
