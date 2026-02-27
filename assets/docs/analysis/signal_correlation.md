# 信号相关性分析说明

本文档描述 `signal_correlation_analysis.py` 的数据来源、方法口径、输出文件与限制。

---

## 1. 目标

- 评估“信号出现时”与后续价格走势的相关性强弱。
- 对 BUY/SELL 方向信号给出胜率和平均收益。
- 对 ALERT 方向信号给出波动性强弱（绝对涨跌幅均值）。

---

## 2. 数据来源

- 信号触发时间：`assets/database/services/signal-service/cooldown.db`
  - 说明：该库仅保存“每个信号键的最后一次触发时间”。
- 价格数据：PostgreSQL `market_data.candles_1m`
  - 仅使用 **已收盘** 1m K线作为入场与对比价。

---

## 3. 方法口径

1. 解析 cooldown 键值：
   - `pg:<SYMBOL>_<signal_type>` → PG 信号
   - `<rule_name>_<SYMBOL>_<timeframe>` → SQLite 信号
2. 入场价：事件时间之后 **第一根已收盘 1m K线** 的 close。
3. 前瞻周期（分钟）：`5 / 15 / 60 / 240 / 1440`
4. 指标定义：
   - BUY 胜率：前瞻收益 > 0
   - SELL 胜率：前瞻收益 < 0
   - ALERT：使用 1h 绝对涨跌幅均值衡量“波动性相关”

---

## 4. 输出文件

```
assets/artifacts/analysis/signal_correlation/
├── signal_events_snapshot.csv   # 原始事件 + 入场价 + 前瞻收益
├── buy_sell_rank.csv            # BUY/SELL 汇总与排名
├── alert_vol_rank.csv           # ALERT 波动性排名
└── report.md                    # 汇总结论
```

---

## 5. 运行方式

```bash
cd /path/to/tradecat
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/market_data \
python3 scripts/signal_correlation_analysis.py
```

常用参数：

- `--cooldown-db`: 指定 cooldown.db 路径
- `--history-db`: 指定 signal_history.db 路径
- `--database-url`: 指定 PG 连接串
- `--output-dir`: 指定输出目录
- `--start / --end`: 按日期过滤事件（UTC）
- `--min-n`: 排名最小样本数
- `--exclude-category`: 排除分类（可重复或逗号分隔）
- `--exclude-table`: 排除规则表名（可重复或逗号分隔）
- `--use-history`: 使用 signal_history.db 作为事件源（完整触发日志）

---

## 6. 关键限制（请勿忽略）

1. **cooldown 并非信号历史表**  
   只能分析“最近一次触发”的相关性，存在时间点偏置。  
   如需完整历史分析，请使用 `--use-history`。
2. **预测结果未纳入**  
   当前库中未发现预测结果表，需明确表位置才能做预测准确性分析。

---

## 7. MVP 与演进方向

- MVP：基于 cooldown + 1m K线，快速评估信号与价格相关性。
- 演进：新增 append-only 信号事件表，纳入预测结果与成交结果闭环。
