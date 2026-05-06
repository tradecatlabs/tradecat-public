# Repair Task Tree

This task tree decomposes the current WARN findings into executable `TP-XX`
packages. It is stored under `references/` instead of root `assets/tasks/`
because this repository's Skill root explicitly forbids root `assets/`.

Machine-readable source: `references/repair-task-tree.json`.

## Task Context

- Status: `Not Started`
- Review verdict source: repository WARN audit covering quality gates, CI,
  public/local documentation boundaries, validation side effects, and remote
  delivery.
- Debug Evidence Contract: `Not Required` for the current plan, because the
  findings are governance and validation gaps rather than an observed runtime
  bug. If GitHub Actions fails during `TP-04.03`, switch that failure into a
  debug evidence loop.

## Scope

In scope:

- Make Skill validation portable and CI-enforced.
- Script the root boundary rules that are currently documented only.
- Remove verification cache side effects.
- Improve public README, Skill quick reference, and public references.
- Push local governance commits and observe remote CI.

Out of scope:

- TradeCat business behavior changes.
- TUI rendering changes.
- Cache schema changes.
- Database, SQL, or server-side integration work.
- Creating root `assets/` or `assets/examples/`.

## Assumptions

- Current root cleanliness policy remains in force: no root `assets/`.
- Current local-only `AGENTS.md` policy remains the default unless explicitly
  changed.
- `scripts/project/` remains the only Python project root.
- CI should fail on Skill wrapper regression, not only Python package failure.

## Critical Ambiguities

- `AGENTS.md` policy has two viable paths:
  - Keep local-only `AGENTS.md` and make public `README/SKILL/references` the
    complete reusable contract.
  - Replace the current guard policy with a tracked, sanitized public
    `AGENTS.md`.

Default task tree path: keep local-only `AGENTS.md`, then strengthen public
references so public clones remain reproducible.

## Task Package Tree

```text
- ROOT
  ├─ TP-01 [branch] [P0] 关闭质量门禁缺口
  │  ├─ TP-01.01 [leaf] [P0] 新增可移植 Skill 校验脚本
  │  ├─ TP-01.02 [leaf] [P0] 把 Skill strict 校验接入 CI
  │  ├─ TP-01.03 [leaf] [P0] 扩展根目录边界守卫
  │  └─ TP-01.04 [leaf] [P0] 对齐 CI 与本地根边界门禁
  ├─ TP-02 [branch] [P1] 收敛验证副作用与本地开发体验
  │  ├─ TP-02.01 [leaf] [P1] 清理 compileall 与 pytest 缓存副作用
  │  ├─ TP-02.02 [leaf] [P1] 统一本地 lint 入口
  │  └─ TP-02.03 [leaf] [P1] 刷新验证文档与质量门禁说明
  ├─ TP-03 [branch] [P1] 修复公开文档与 Skill 可用性
  │  ├─ TP-03.01 [leaf] [P1] 明确 AGENTS 本地化策略
  │  ├─ TP-03.02 [leaf] [P1] 强化根 README 用户入口
  │  ├─ TP-03.03 [leaf] [P1] 去重 SKILL Quick Reference 并统一命令口径
  │  ├─ TP-03.04 [leaf] [P2] 公开化完整 Linear Flows
  │  └─ TP-03.05 [leaf] [P2] 更新 reference 导航与交叉引用
  └─ TP-04 [branch] [P1] 交付、回归与远端闭环
     ├─ TP-04.01 [leaf] [P1] 运行完整本地回归门禁
     ├─ TP-04.02 [leaf] [P2] 按主题提交修复
     └─ TP-04.03 [leaf] [P2] 推送 develop 并观察 CI
```

## Execution Waves

- Wave 1: `TP-01.01`, `TP-01.03`, `TP-02.01`, `TP-02.02`, `TP-03.02`, `TP-03.04`
- Wave 2: `TP-01.02`, `TP-01.04`, `TP-02.03`, `TP-03.01`, `TP-03.03`, `TP-03.05`
- Wave 3: `TP-04.01`
- Wave 4: `TP-04.02`
- Wave 5: `TP-04.03`

## Next Executable Leaves

- `TP-01.01`: no dependencies. Gate: `README`、`SKILL.md`、`quality-gate` no longer require copying `/home/lenovo/.codex`.
- `TP-01.03`: no dependencies. Gate: root boundary is enforced by script, not only documentation.
- `TP-02.01`: no dependencies. Gate: `verify` still passes all existing compile/test/syntax checks and leaves no generated cache.
- `TP-02.02`: no dependencies. Gate: local lint behavior matches CI or explicitly documents the difference.
- `TP-03.02`: no dependencies. Gate: root README exposes user installation immediately.
- `TP-03.04`: no dependencies. Gate: public references include full linear flows.

## Leaf Task Details

| ID | Priority | Depends On | Parallel | Objective | Verify | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| `TP-01.01` | P0 | - | No | 新增根脚本封装 auto-skill validator，使用 `CODEX_HOME` 或 `HOME` 推导校验器路径，消除 `/home/lenovo` 硬编码。 | 从仓库根执行新脚本 strict 模式，换用 `CODEX_HOME` 覆盖路径后仍能定位校验器。 | 文档不再要求用户复制本机绝对路径。 |
| `TP-01.02` | P0 | `TP-01.01` | No | 更新 GitHub Actions，在 verify job 中执行可移植 Skill 校验脚本。 | CI YAML 包含 Skill strict step；本地 YAML 结构检查通过。 | Skill 退化会阻断 CI。 |
| `TP-01.03` | P0 | - | No | 扩展 `guard_public_local_files.sh`，检查 root forbidden paths。 | 构造临时禁放路径时 guard 返回非零；正常仓库返回零。 | 根目录边界不再只靠文档。 |
| `TP-01.04` | P0 | `TP-01.03` | No | 对齐 CI 调用、root boundary gate 和脚本实际检查项。 | `bash scripts/project/scripts/guard_public_local_files.sh` 与 `bash scripts/verify.sh` 均通过。 | 本地与 CI 使用同一边界守卫。 |
| `TP-02.01` | P1 | - | Yes | 调整 verify，关闭或清理 `.pytest_cache`、`.ruff_cache`、`__pycache__`。 | 连续两次 `bash scripts/verify.sh` 后不残留项目缓存目录。 | verify 仍通过 compileall、pytest、shell syntax、request.py compile。 |
| `TP-02.02` | P1 | - | Yes | 统一本地 lint 入口。 | `ruff` 可用时本地 gate 能跑 `ruff check src tests`；不可用时明确降级。 | 本地质量门禁与 CI lint 口径一致或差异显式。 |
| `TP-02.03` | P1 | `TP-01.01`, `TP-02.01`, `TP-02.02` | No | 刷新质量门禁文档与验证说明。 | 文档命令可从对应目录复制执行。 | 文档反映真实脚本行为。 |
| `TP-03.01` | P1 | `TP-01.03` | No | 明确 `AGENTS.md` 本地化策略。 | guard、`.gitignore`、architecture、quality-gate 描述一致。 | 公开 clone 可从 public docs 获得完整治理规则。 |
| `TP-03.02` | P1 | - | Yes | 强化根 README 用户入口。 | 根 README 前 40 行包含用户安装入口和项目 README 链接。 | GitHub 默认首页不只呈现 Skill 外壳。 |
| `TP-03.03` | P1 | `TP-01.01` | No | 去重 `SKILL.md` Quick Reference 并统一命令口径。 | Quick Reference 不再重复 `bash scripts/verify.sh`。 | `SKILL.md` 短、直接、无重复。 |
| `TP-03.04` | P2 | - | Yes | 新增 `references/linear-flows.md`，公开六条主链路。 | 六条 flow 节点均可追溯到代码、脚本、配置或文档。 | 公开 references 不再只有压缩 Main Flow。 |
| `TP-03.05` | P2 | `TP-03.04` | No | 更新 references 导航与交叉引用。 | `references/index.md` 可定位 `architecture`、`quality-gate`、`linear-flows`、`repair-task-tree`。 | references 入口完整且不堆叠重复长文档。 |
| `TP-04.01` | P1 | `TP-01`, `TP-02`, `TP-03` | No | 运行完整本地回归门禁。 | Skill strict、项目 verify、ruff、root boundary guard、`git diff --check` 全部返回零。 | 本地证据覆盖质量、项目、边界、lint、生成物清理。 |
| `TP-04.02` | P2 | `TP-04.01` | No | 按主题提交修复。 | `git log --oneline` 和 `git show --stat` 能对应任务树范围。 | 每个提交可独立解释、可回滚。 |
| `TP-04.03` | P2 | `TP-04.02` | No | 推送 `develop` 并观察 CI。 | 本地与 `origin/develop` 对齐；最新 GitHub Actions 成功或失败原因已记录。 | 远端 CI 对治理成果形成闭环。 |

## Dependency Graph

```text
TP-01.01 -> TP-01.02
TP-01.03 -> TP-01.04
TP-01.01 -> TP-02.03
TP-02.01 -> TP-02.03
TP-02.02 -> TP-02.03
TP-01.03 -> TP-03.01
TP-01.01 -> TP-03.03
TP-03.04 -> TP-03.05
TP-01.* + TP-02.* + TP-03.* -> TP-04.01
TP-04.01 -> TP-04.02
TP-04.02 -> TP-04.03
```

## Global Acceptance

- Strict Skill validation is portable and CI-enforced.
- Root boundary rules are enforced by script and CI.
- `bash scripts/verify.sh` leaves no project cache side effects.
- Local lint expectations are explicit and aligned with CI.
- Public docs are sufficient without local-only `AGENTS.md`.
- Root README serves both Skill maintainers and normal TradeCat users.
- Full public linear flows exist under `references/`.
- Local commits are pushed and GitHub Actions provides final evidence.

## Validation Plan

Run after implementation:

```bash
bash scripts/validate-skill.sh --strict
bash scripts/project/scripts/guard_public_local_files.sh
bash scripts/verify.sh
cd scripts/project && ruff check src tests
git diff --check
git status --short --branch --ignored
```

If `ruff` is unavailable locally, record that as an explicit local limitation and
rely on CI for the definitive lint gate.
