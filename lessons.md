# Lessons

## 2026-05-08 First-run Cache Must Be A Product Contract

- 现象：`tradecat` 启动后显示 `cache=empty-cache`、`remote=-`、`fetched=-`，后台 probe 在弱网下超时。
- 本质：安装、缓存、TUI 三层没有把“首次公开数据快照”当成同一个产品契约；安装期允许跳过或失败，TUI 又是 cache-first，于是空缓存被用户感知成程序坏了。
- 规则：默认入口必须尽量保证默认 tap 有缓存；如果做不到，界面必须明确说清是 cold start、正在 warming、需要 sync，不能只暴露内部状态码。
- 防复发：安装脚本在 `sync-all` 失败后必须兜底同步 `event_stream`；TUI 状态栏必须区分 `warming / sync-needed / probe-failed`；doctor 必须给出 `sync-all` 和弱网 timeout 修复命令。
- 验证：每次改安装、缓存、TUI 启动逻辑，都要覆盖空缓存、首次探针失败、弱网 timeout 和默认 dataset 可用性。
