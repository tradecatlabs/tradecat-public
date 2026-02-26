# PLAN

## 1) 方案对比与取舍

### 方案 A（推荐）：两阶段迁移 + 兼容层

Stage 1：`libs/external` → `assets/repo`（只动资源目录）  
Stage 2：`libs/` → `assets/`（引入兼容层，逐步替换引用，最后移除兼容层）

- Pros
  - 风险可控：先做低风险收益点，再进入高风险阶段
  - 易回滚：每个阶段可独立回退
  - 验证闭环：可用 `rg` gate 做“引用清零”验收
- Cons
  - 迁移期更长（存在兼容层并存阶段）

### 方案 B：一次性 big-bang 重命名

一次性执行 `git mv libs assets`，全仓库替换 import/path，并立即删除旧入口。

- Pros：一次性完成，最终结构最干净
- Cons：回归面巨大，极易出现“漏改一处导致服务全挂”的故障；排障成本高

结论：采用 **方案 A**。

## 2) 目标数据/依赖流（ASCII）

```text
Current:
  Python imports -> libs/common/*
  Scripts/config -> libs/database/*
  Docs/tools     -> libs/external/*

Target (after Stage 1):
  Python imports -> libs/common/*
  Scripts/config -> libs/database/*
  Docs/tools     -> assets/repo/*

Target (after Stage 2 + compat):
  Python imports -> assets/common/*   (new)
              or -> libs/common/*     (compat layer)
  Scripts/config -> assets/database/*
  Third-party    -> assets/repo/*
```

## 3) 原子变更清单（文件级别，不写实现细节）

### Stage 0：盘点与基线

- 生成“引用清单”：
  - `import libs.*` 的所有出现位置
  - `libs/database` 的所有路径引用
  - `libs/external` 的所有路径引用（预期为 0）
- 在迁移前创建 checkpoint commit（方便 reset）

### Stage 1：迁移第三方仓库镜像

- `git mv libs/external assets/repo`
- 更新所有 `libs/external/...` 引用（若存在）
- 更新目录树文档（README/AGENTS 中的结构描述）

### Stage 2：迁移 `libs/` 根（高风险）

兼容层二选一（推荐顺序：先 A，再 B 作为兜底）：

- A) symlink 兼容：保留 `libs -> assets` 或 `libs/common -> assets/common` 等映射
- B) Python 兼容包：保留最小 `libs/` 包，内部 re-export 指向 `assets/` 下的新模块

然后逐步把业务代码与脚本的引用迁移到新路径，并在最后删除兼容层。

## 4) 回滚协议（必须可复制执行）

- 回滚到迁移前 checkpoint（示例：`527c998` 为当前对话中已存在的 checkpoint）：
  - `git reset --hard 527c998`
- 若只回滚 Stage 1：
  - `git reset --hard <stage1_before_commit>`
- 回滚后验证：
  - `./scripts/check_env.sh`
  - `./scripts/start.sh status`

