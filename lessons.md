# Lessons

## 2026-05-08 First-run Cache Must Be A Product Contract

- 现象：`tradecat` 启动后显示 `cache=empty-cache`、`remote=-`、`fetched=-`，后台 probe 在弱网下超时。
- 本质：安装、缓存、TUI 三层没有把“首次公开数据快照”当成同一个产品契约；安装期允许跳过或失败，TUI 又是 cache-first，于是空缓存被用户感知成程序坏了。
- 规则：默认入口必须尽量保证默认 tap 有缓存；如果做不到，界面必须明确说清是 cold start、正在 warming、需要 sync，不能只暴露内部状态码。
- 防复发：安装脚本在 `sync-all` 失败后必须兜底同步 `event_stream`；TUI 状态栏必须区分 `warming / sync-needed / probe-failed`；doctor 必须给出 `sync-all` 和弱网 timeout 修复命令。
- 验证：每次改安装、缓存、TUI 启动逻辑，都要覆盖空缓存、首次探针失败、弱网 timeout 和默认 dataset 可用性。

## 2026-05-08 Public Install Must Exercise The Real First-Run Path

- 现象：CI 的公网 raw installer smoke 曾设置 `TRADECAT_INSTALL_SKIP_SYNC=1`，只能证明脚本可下载、launcher 可执行，不能证明普通用户安装后首屏有缓存。
- 本质：测试为了稳定性绕开了产品契约，导致“安装成功”和“首次可用”被拆成两件事。
- 规则：发布通道的公网安装 smoke 必须走普通用户路径；如初次同步失败，可以显式执行 `doctor --sync` 做一次修复，但最终必须断言默认 `event_stream` 为 `ready`。
- 防复发：稳定安装默认指向 tag；开发分支自动更新必须通过 `TRADECAT_INSTALL_BRANCH=develop` 显式选择；tag 内 release 文档使用稳定工作流查询链接，避免发布后再改 tag 文档。
- 验证：每次改 installer、CI 或 release 口径，都要同时检查 raw install、cache warm、release notes、README 默认命令和本地裸环境 verify。
