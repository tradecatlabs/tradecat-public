# plugins/binance-skills-hub-main 开发约束

本文件作用域：`plugins/binance-skills-hub-main/**`。

## 服务定位

这是 Binance Skills Hub 外部技能仓镜像。仓内核心资产是 `skills/**/SKILL.md`，不是 TradeCat 主运行服务。

## 目录结构

```text
plugins/binance-skills-hub-main/
├── README.md
├── AGENTS.md
└── skills/          # 技能定义与说明
```

## Linear Flow

本目录真实镜像链路：

```text
Input(输入)：Binance Skill 查看、安装、结构核对或外部技能接入需求
-> 节点1：以 `README.md` 的 `npx skills add` 安装方式和 `skills/**/SKILL.md` 结构为依据
-> 节点2：只维护外部技能仓镜像边界，不把它改成 TradeCat 常驻服务或数据库链路
-> 节点3：如需 TradeCat 接入，优先新建独立 skill 或适配层
-> Output(输出)：可参考的 Binance skill 镜像、安装路径或接入边界
```

### Flow Rules

- 节点数量必须刚好覆盖真实主链路。
- 不允许省略必要节点。
- 不允许添加不存在的伪节点。
- 每个节点必须能追溯到代码、脚本、配置、数据表、接口或文档。
- 架构、目录、入口、数据流或控制流变化时，必须同步更新本流程。

## 强边界

- 默认按外部技能仓镜像处理，不要把它改成 TradeCat 服务目录
- 主要维护对象是 skill 格式与内容，不是常驻进程或数据库链路
- 若要接入 TradeCat，优先通过独立 skill / 适配层，而不是直接改上游技能规范

## 推荐命令

```bash
npx skills add https://github.com/binance/binance-skills-hub
```

## 修改约束

- 新增或修改 skill 时，先遵守 `README.md` 中定义的 `SKILL.md` frontmatter 结构
- 当前仓内未提供本地构建或测试脚本；最小验证以 `README.md` 的安装命令和 `skills/**/SKILL.md` 结构一致性为准

## 文档规则

- 本目录 `README.md + AGENTS.md` 只描述镜像边界与修改约束
