# 指标数据说明补全计划（给另一位 AI 执行）

## 目标
- 为 SQLite 指标表（market_data.db 内全部表）补全 what/why/how + fields 说明，写入 `src/utils/data_docs.py` 的 `DATA_DOCS`。
- 说明要基于真实字段与计算逻辑，不可凭空编造。

## 输入资产
- 表结构：`assets/database/services/telegram-service/market_data.db`（兼容：`libs -> assets`）
- 计算逻辑：
  - 指标注册：`services/compute/trading-service/src/indicators/__init__.py`
  - 指标实现：`services/compute/trading-service/src/indicators/batch/*.py`、`services/compute/trading-service/src/indicators/incremental/*.py`
  - 相关基座：`services/compute/trading-service/src/indicators/base.py`、`services/compute/trading-service/src/core/`

## 输出物
1) 更新文件：`src/utils/data_docs.py`，为每个表新增条目（键名=表名，如 `MACD柱状扫描器.py`）。
2) 每条条目结构：
```
"表名": {
  "what": "<是什么，含核心算法/输入/输出摘要+字段列表概括>",
  "why": "<为什么重要，交易/风控价值，适用场景>",
  "how": "<怎么用，观察顺序/阈值/共振/过滤建议>",
  "fields": {
      "字段A": "含义+单位/范围",
      ...
  }
}
```

## 任务拆解
1) **枚举表 + 字段**
   - 用 sqlite3/`PRAGMA table_info` 列出全部表、字段、类型。
   - 产出临时清单 `tmp/indicator_tables.json`（表名 -> 字段列表）。

2) **建立表名 ↔ 脚本映射**
   - 查 `utils/指标集中计算器.py` 注册表，确认表名对应的扫描器类/文件。
   - 若注册缺失，按表名匹配 `src/index` 下同名/相近文件。
   - 生成 `tmp/indicator_mapping.md`（表名、脚本路径、类名、说明来源）。

3) **逐表提炼逻辑**
   - 阅读对应扫描器脚本，抓取：输入周期/数据、核心计算（指标/阈值）、输出字段含义。
   - 若字段含义在代码中有中文注释/变量名，直接引用；否则据计算公式推导，但需标注推断。

4) **撰写说明条目**
   - 按模板生成 what/why/how/fields。
   - 对阈值或方向说明给出实际单位（如 “MACD柱状图：数值>0多头动能”）。

5) **写入 data_docs.py**
   - 使用 apply_patch 将条目插入 `DATA_DOCS`，保持按表名排序或分组。
   - 确保 UTF-8，简体中文。

6) **验证**
   - 运行轻量校验脚本：遍历 market_data.db 表名，确认 `DATA_DOCS` 覆盖率 100%；输出缺失列表。
   - `python3 - <<'PY'` 检查 `DATA_DOCS` JSON 可序列化。

7) **交付记录**
   - 更新 `AGENTS.md` 或在 `docs/indicator_docs_plan.md` 末尾添加已完成表清单。

## 优先级建议（先易后难）
1) MACD柱状扫描器.py
2) 布林带扫描器.py
3) 成交量比率扫描器.py / 主动买卖比扫描器.py
4) 量能信号扫描器.py / 流动性扫描器.py
5) 零延迟趋势信号扫描器.py / 超级精准趋势扫描器.py
6) K线形态扫描器.py / 谐波信号扫描器.py / 趋势线榜单
7) 其余表（支撑阻力、VPVR、CVD、MFI、OBV 等）

## 执行提示
- 坚持“字段真实 + 逻辑可溯源”；无法确定时标注“待确认”。
- 避免模糊词（如“等”）；字段全部点名。
- 若脚本与表字段不一致，先在说明中备注差异，再向上游报缺。
- 写入顺序：先完成优先级 1-3，提交；再批次推进。
