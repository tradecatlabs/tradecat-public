# 方案：Google Sheets 看板“源信息 5 行 → 1 单元格”压缩渲染

## 0) 目标（你确认过的口径）

把每张卡片的 5 个“源信息字段”按固定顺序拼接到 **同一个单元格**（整行合并）里，紧贴在表格明细上方：

1. `📊 <标题>`
2. `⏰ 更新 <update_time>`
3. `📊 排序 <sort_desc>`
4. `💡 <hint>`
5. `⏰ 最后更新 <last_update>`

目标展示（示意）：

```text
----------------------------------------------------------------------------------+
| 📊 ATR数据 ⏰ 更新 2026-02-19 01:15:00 📊 排序 多周期 ATR%(🔽) 💡 ... ⏰ 最后更新 - |
+----------------------------------------------------------------------------------+
| 币种 | 排名@1m..1w | ATR%@1m..1w | ...                                            |
| ...                                                                          ... |
```

## 1) 当前实现现状（为什么需要改）

当前看板渲染把源信息拆成多行：

- 顶部 3 行：`title / update / sort`
- 底部 2 行：`hint / last_update`

这会导致：
- 卡片高度变大、看板更“长”，阅读跳跃明显
- 超宽列被纵向分块（chunks）时，顶部/底部信息与表格主体隔离，视线不连贯

## 2) 变更范围（In Scope / Out of Scope）

### In Scope
- **只改展示面**：`看板` 的 `_render_dashboard()` 输出结构与样式
- 同步改动高度计算：`_calc_dashboard_height()` 与相关 merge/format 范围计算
- 同步更新文档口径（PRD/README）：布局公式、验收说明

### Out of Scope
- 不改事实表（`卡片索引/卡片字段EAV/...`）结构
- 不改多周期导出（字段组/周期两行表头）口径
- 不引入新依赖、不改认证/写入通道

## 3) 具体改动点（文件级）

### 3.1 `services/consumption/sheets-service/src/sa_sheets_writer.py`

改动函数：
- `SaSheetsWriter._render_dashboard()`
- `SaSheetsWriter._calc_dashboard_height()`
-（若需要）`SaSheetsWriter.reset_dashboard()`：保持“清值 + 解除合并 + 清格式”完整覆盖范围

#### A) 源信息拼接（新增行为）

新增 `info_line`：
- 固定包含 5 段（避免字段缺失导致顺序不稳定）
- 字段缺失时用 `-` 占位（保证每张卡片都“长得一样”）

拼接规则（推荐）：
- `parts = [title, update_part, sort_part, hint_part, last_part]`
- 过滤 `None`，但不过滤 `"-"`（用户要求显示 `-`）
- 用单个空格 `" "` join

#### B) 布局重排（删除旧 5 行结构）

旧布局：
- `y+0..2`：title/update/sort
- `table_y=y+3`
- `hint_y`、`last_y` 在表格后

新布局：
- `y+0`：`info_line`（整行合并）
- `table_y=y+1`：表格主体（保持“两行表头：字段组行 + 周期行”）
- 表格末尾保留 **1 行空行**作为卡片间隔（建议保留，避免卡片贴死）
- 删除 `hint_y/last_y` 行（信息已被压缩进 `info_line`）

#### C) 合并单元格与样式范围（必须同步）

合并：
- 仅合并 `info_line` 行（全行合并）
- 表头字段组行的“字段组分段合并”保留（提高可读性）

样式：
- `info_line` 行：`bg_title` + `bold` + `wrap`
- 表头两行：维持现有 `bg_hdr_group/bg_hdr_period`
- 表体：维持灰白交替 + 字段组竖线分隔

#### D) 高度计算（必须与布局一致）

定义：
- `N=len(rows)`
- `W = col_r - col_l + 1`
- `C=len(columns)`
- `chunks = max(1, ceil(C / W))`

新高度公式（建议）：
- `height = 1 + chunks*(2 + N) + 1`
  - `1`：info 行
  - `chunks*(2+N)`：每个 chunk 两行表头 + N 行数据
  - `1`：空行分隔

> 注意：任何 merge/format 的 row range 都必须跟着这个公式调整，否则会出现“残留配色/残留边框/覆盖错位”。

### 3.2 文档同步

- `docs/analysis/tg_cards_google_sheets_dashboard_prd.md`
  - 更新 6.x “固定版式”描述：源信息单行 + 表格主体 + 空行
- `services/consumption/sheets-service/README.md`
  - 增补：源信息压缩后的布局口径（用于运维/验收）

## 4) 验收标准（你能肉眼一眼看出来的）

对任意一张卡片（如 ATR）：
- 在 `看板` 中，源信息只占 **1 行**，且该行内容按顺序包含 5 段信息
- 紧接着就是表格两行表头（字段组行 + 周期行），再接数据行
- 卡片底部不再出现独立的 `💡 ...` 与 `⏰ 最后更新 ...` 两行
- 背景色/边框不出现“上一轮残留”（配合 `dashboard` 模式 reset）

## 5) 风险与对策

| 风险 | 严重度 | 触发信号 | 对策 |
|---|---:|---|---|
| 信息过长导致单元格看起来很挤 | Medium | `info_line` 超过 1 行高度 | 开启 `wrap`；必要时改为用 ` · ` 分隔或换行符 `\\n`（仍是 1 单元格） |
| 高度公式/format range 不一致导致残留 | High | 背景色/竖线残留或覆盖错位 | 同步修改 `_calc_dashboard_height` 与 `_render_dashboard` 的 row 计算；reset 时清格式 |
| chunks>1 时表头/边框范围画错 | Medium | 第二块开始表头颜色错/分隔线断 | 以 `table_y` 推进为唯一真相源，逐 chunk 计算范围 |

