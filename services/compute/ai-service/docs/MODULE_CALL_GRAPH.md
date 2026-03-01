# 模块调用关系图

> 生成时间: 2025-11-30
> 文件位置: `services/compute/ai-service/src/`（历史上曾位于 `services/telegram-service/src/ai/src/`）

## 一、调用关系总览

```
┌─────────────────────────────────────────────────┐
│            模块调用层次结构                      │
├─────────────────┬─────────────────┬─────────────┤
│  层级           │ 模块            │ 主要类      │
├─────────────────┼─────────────────┼─────────────┤
│ L1 (入口层)     │ bot.py          │ AITelegramHandler│
├─────────────────┼─────────────────┼─────────────┤
│ L2 (业务层)     │ ai.py           │ AICoinQueryManager│
│                 │                 │ AIAnalysisEngine│
├─────────────────┼─────────────────┼─────────────┤
│ L3 (计算层)     │ ai.py           │ TechnicalIndicatorCalculator│
│                 │                 │ MultiTimeframeCalculator│
├─────────────────┼─────────────────┼─────────────┤
│ L4 (数据层)     │ data.py         │ BinanceMarketDataManager│
│                 │                 │ UnifiedDataSaver│
├─────────────────┼─────────────────┼─────────────┤
│ L5 (工具层)     │ utils.py        │ ProgressDisplay│
│                 │                 │ MarkdownImageRenderer│
└─────────────────┴─────────────────┴─────────────┘

总调用深度: 10-15层
```

---

## 二、核心调用链

### 调用链 1: 用户AI分析请求

```
┌──────────────────────────────────────────────────────────────┐
│ 调用链: text_message() → 结果发送 (10步)                     │
└────────────────────┬─────────────────────────────────────────┘
                     │
 1. bot.py:text_message()                              [40]
    └─ 接收用户消息: "BTC@15m"

 2. _ensure_ai_handler()                               [32]
    └─ 初始化 AITelegramHandler

 3. AITelegramHandler.handle_coin_selection()          [14003]
    └─ 处理币种选择

 4. AICoinQueryManager.query()                         [12089]
    └─ 统一查询入口

 5. AICoinQueryManager._build_analysis_data()          [12248]
    └─ 构建分析数据

 6. TechnicalIndicatorCalculator.calculate_all()      [944]
    └─ 计算技术指标 (多线程8线程)

 7. MultiTimeframeCalculator.analyze()                [2340]
    └─ 多周期共振分析

 8. AIAnalysisEngine.generate_analysis()              [5080]
    └─ 调用LLM生成分析

 9. AnalysisReportGenerator.create_report()           [5744]
    └─ 生成Markdown报告

10. MarkdownImageRenderer.render_markdown_to_image() [878]
    └─ 渲染PNG图片 (Playwright)

11. AITelegramHandler.send_results()                  [14602]
    └─ 发送Telegram消息

调用耗时: 15-30秒
并发控制: Semaphore(5)
```

### 调用链 2: 技术指标计算

```
┌──────────────────────────────────────────────────────────────┐
│ 调用链: calculate_all() → 指标结果 (7步)                     │
└────────────────────┬─────────────────────────────────────────┘
                     │
 1. TechnicalIndicatorCalculator.calculate_all()    [944]
    └─ 批量计算入口

 2. async_calc_indicators()                          [1655]
    └─ 异步计算调度

 3. _calculate_indicator_data()                       [1735]
    └─ 具体指标计算

 4. calc_MACD() / calc_RSI() / calc_KDJ()           [1055, 1185, 1315]
    └─ 并行计算 (ThreadPoolExecutor)

 5. _compute_signal_from_indicators()                [1830]
    └─ 信号生成

 6. _format_indicator_results()                      [1890]
    └─ 结果格式化

 7. cache_manager.put()                              [641]
    └─ 写入缓存

性能: 1000根K线 × 10指标 ≈ 0.5-1秒
```

### 调用链 3: 市场数据获取

```
┌──────────────────────────────────────────────────────────────┐
│ 调用链: get_kline_data() → 数据返回 (6步)                    │
└────────────────────┬─────────────────────────────────────────┘
                     │
 1. BinanceMarketDataManager.get_kline_data()      [670]
    └─ 统一数据入口

 2. AICacheManager.get()                             [120]
    └─ 查缓存

 3. BinanceCoinDataCollector.fetch_kline()         [885]
    └─ 调用API

 4. UnifiedDataSaver.save()                          [23]
    └─ 保存数据

 5. cache_manager.put()                              [180]
    └─ 写缓存

 6. 返回 DataFrame                                   [890]

缓存命中率: 80-90%
```

### 调用链 4: 图片渲染

```
┌──────────────────────────────────────────────────────────────┐
│ 调用链: render_markdown_to_image() → PNG (8步)               │
└────────────────────┬─────────────────────────────────────────┘
                     │
 1. render_markdown_to_image()                      [878]
    └─ 入口函数

 2. MarkdownImageRenderer.initialize()             [707]
    └─ 初始化Playwright

 3. _markdown_to_html()                            [1018]
    └─ Markdown转HTML

 4. playwright.chromium.launch()                  [750]
    └─ 启动浏览器

 5. page.set_content()                             [945]
    └─ 加载内容

 5. asyncio.sleep(2)                               [946]
    └─ 等待渲染

 6. page.screenshot()                               [949]
    └─ 截图

 7. 返回文件路径                                    [975]

耗时: 2-5秒
分辨率: 1920x1080
```

### 调用链 5: 缓存查询

```
┌──────────────────────────────────────────────────────────────┐
│ 调用链: get() → 缓存结果 (4步)                               │
└────────────────────┬─────────────────────────────────────────┘
                     │
 1. AICacheManager.get()                            [120]
    └─ 入口

 2. get_cache() (memory)                            [240]
    └─ 查内存

 3. get_cache() (Redis)                            [260]
    └─ 查Redis

 4. get_cache() (PG)                               [280]
    └─ 查PG

复杂度: O(1) - O(log n)
```

---

## 三、模块间依赖关系

### 3.1 正向依赖 (从上到下)

```
┌─────────────────────────────────────────────────┐
│ 依赖流向: 上层 → 下层 (调用关系)                 │
└────────────────────┬────────────────────────────┘
                     │
                    bot.py
                      ↓ (import)
                     ai.py
                      ↓ (import)
                    data.py
                      ↓ (import)
                    utils.py
                      ↓ (import)
                prompt_registry.py

依赖数量:
- bot.py → ai.py: 2个类 (AITelegramHandler, AICoinQueryManager)
- ai.py → data.py: 3个类 (BinanceMarketDataManager, UnifiedDataSaver, ...)
- ai.py → utils.py: 2个类 (ProgressDisplay, MarkdownImageRenderer)
- 所有 → prompt_registry.py: PromptRegistry
```

### 3.2 反向依赖 (回调/数据流)

```
┌─────────────────────────────────────────────────┐
│ 反向依赖: 下层 → 上层 (数据流动)                │
└────────────────────┬────────────────────────────┘
                     │
                prompt_registry.py
                      ↑ (提供配置)
                    utils.py
                      ↑ (提供工具)
                    data.py
                      ↑ (提供数据)
                     ai.py
                      ↑ (提供分析)
                    bot.py
                      ↑ (提供交互)

数据流向:
- 结果数据流: data.py → ai.py → bot.py
- 配置数据流: prompt_registry.py → ai.py → bot.py
```

### 3.3 循环依赖 (已解决)

```
┌─────────────────────────────────────────────────┐
│ 已解决的依赖问题                                │
└────────────────────┬────────────────────────────┘

问题1: bot.py ←→ ai.py
    bot.py 需要 AITelegramHandler
    ai.py 需要 ProgressManager
→ 解决方案: 使用延迟初始化

    def _ensure_ai_handler():
        if _ai_handler is None:
            _ai_handler = AITelegramHandler()
        return _ai_handler

问题2: ai.py ←→ data.py
    ai.py 需要 BinanceMarketDataManager
    data.py 需要 AICacheManager
→ 解决方案: 使用初始化注入

    manager = AICoinQueryManager()
    manager.cache_manager = AICacheManager()

问题3: 多模块共享
    PromptRegistry 被所有模块使用
→ 解决方案: 单例模式

    _prompt_registry = None
    def get_prompt_registry():
        global _prompt_registry
        if not _prompt_registry:
            _prompt_registry = PromptRegistry()
        return _prompt_registry
```

---

## 四、调用频率统计

### 高频调用 (>100次/分钟)

```
┌────────────────────────────────────────────┐
│         高频调用函数 (核心路径)             │
└──────────────────┬─────────────────────────┘
                   │
 1. AICacheManager.get()                         [120]
    └─ 缓存查询 (每次请求)
    频率: ~500次/分钟

 2. TechnicalIndicatorCalculator.calculate_all()[944]
    └─ 批量计算 (实时分析)
    频率: ~100-200次/分钟

 3. AICoinQueryManager.query()                  [12089]
    └─ AI查询入口
    频率: ~100次/分钟

 4. ProgressDisplay.show_progress()             [197]
    └─ 进度显示 (每个阶段)
    频率: ~200次/分钟

 5. get_beijing_time()                         [16]
    └─ 时间格式化 (日志+显示)
    频率: ~1000次/分钟
```

### 中频调用 (10-100次/分钟)

```
 1. BinanceCoinDataCollector.fetch_kline()     [885]
    └─ API调用 (缓存未命中)
    频率: ~10-30次/分钟

 2. MultiTimeframeCalculator.analyze()         [2340]
    └─ 多周期分析 (完整分析)
    频率: ~20次/分钟

 3. MarkdownImageRenderer.render_markdown_to_image() [878]
    └─ 图片渲染
    频率: ~10次/分钟
```

### 低频调用 (<10次/分钟)

```
 1. AIAnalysisEngine.generate_analysis()       [5080]
    └─ LLM调用 (成本高)
    频率: ~1-5次/分钟

 2. BinanceMarketDataManager.refresh_cache()   [790]
    └─ 缓存刷新 (1分钟周期)
    频率: ~1次/分钟

 3. UnifiedDataSaver.save_to_s3()              [195]
    └─ S3备份 (每小时)
    频率: ~0.01次/分钟

 4. PromptRegistry.reload()                   [67]
    └─ 热重载 (手动触发)
    频率: ~0次/分钟 (按需)
```

---

## 五、关键路径分析

### 5.1 关键路径 (Critical Path)

```
┌──────────────────────────────────────────────────────────────┐
│           性能关键路径 (Critical Path)                      │
└────────────────────┬─────────────────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    │ 步骤           │ 耗时           │ 占比
    ├────────────────┼────────────────┼──────
    │ 数据获取       │ 0.5-1秒        │ 3-5%
    ├────────────────┼────────────────┼──────
    │ 技术指标计算   │ 0.5-1秒        │ 3-5%
    ├────────────────┼────────────────┼──────
    │ 多周期分析     │ 0.5-1秒        │ 3-5%
    ├────────────────┼────────────────┼──────
    │ LLM调用        │ 10-20秒        │ 70-80%
    ├────────────────┼────────────────┼──────
    │ 报告生成       │ 0.1-0.2秒      │ <1%
    ├────────────────┼────────────────┼──────
    │ 图片渲染       │ 2-5秒          │ 10-15%
    ├────────────────┼────────────────┼──────
    │ Telegram发送   │ 0.5-1秒        │ 3-5%
    ├────────────────┼────────────────┼──────
    │ 总计           │ 15-30秒        │ 100%
    └────────────────┴────────────────┴──────

性能瓶颈: LLM API调用 (无可优化)
优化重点: 缓存命中率 (减少重复计算)
          └─ 目标: 90%+ (当前85%)
```

### 5.2 并发热点

```
┌──────────────────────────────────────────────────────────────┐
│              并发热点分析                                    │
└────────────────────┬─────────────────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    │ 资源竞争点     │ 并发数         │ 上限
    ├────────────────┼────────────────┼──────
    │ AI API (LLM)   │ semaphore=5    │ 5
    ├────────────────┼────────────────┼──────
    │ 币安API        │ 1200 RPM       │ 20/秒
    ├────────────────┼────────────────┼──────
    │ 数据库连接     │ pool_size=20   │ 20
    ├────────────────┼────────────────┼──────
    │ 图片渲染       │ semaphore=3    │ 3 (并行)
    ├────────────────┼────────────────┼──────
    │ 线程池         │ max_workers=8  │ 8 (并行)
    └────────────────┴────────────────┴──────

优化策略:
- AI API: 无法提高 (供应商限制)
- 币安API: 批量请求 (已优化)
- 数据库: 使用连接池
- 图片渲染: 并行限制3 (系统资源限制)
```

---

## 六、异常调用路径

### 6.1 错误重试路径

```
┌──────────────────────────────────────────────────────────────┐
│            错误重试调用路径                                  │
└────────────────────┬─────────────────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    │ 正常路径       │ 错误发生       │ 重试路径
    ▼                ▼                ▼
┌─────────┐      ┌─────────┐      ┌─────────┐
│ fetch() │ ──X→ │ Timeout │ ──→  │ retry() │
│         │      │         │      │         │
│         │      │         │      │         │
└─────────┘      └────┬────┘      └─────┬───┘
                      │                 │
    ┌─────────────────┴─────────────────┴────────┐
    │ 重试策略:                                  │
    │ - 次数: 3次                                │
    │ - 退避: 指数增长 (2, 4, 8秒)              │
    │ - 最终失败: 记录日志 + 用户通知             │
    └────────────────────────────────────────────┘

涉及函数:
1. BinanceCoinDataCollector.fetch_kline() [885]
   └─ 最多重试3次

2. AIAnalysisEngine._call_ai_api() [5500]
   └─ 最多重试3次

3. UnifiedDataSaver.save() [23]
   └─ 自动降级 (CSV/PG/S3)
```

### 6.2 缓存未命中路径

```
┌──────────────────────────────────────────────────────────────┐
│            缓存未命中调用路径                                │
└────────────────────┬─────────────────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    │ L1 (内存)      │ L2 (Redis)     │ L3 (PG)
    ▼                ▼                ▼
┌─────────┐      ┌─────────┐      ┌─────────┐
│ Query   │ ──X→ │ Query   │ ──X→ │ Query   │
│ Cache   │      │ Cache   │      │ Cache   │
│         │      │         │      │         │
└────┬────┘      └────┬────┘      └────┬────┘
     │                │                │
     │                │                └─→ API调用
     │                │
     │                └─→ 写入L2
     │
     └─→ 写入L1

调用次数:
- L1查询: 1次
- L2查询: 0.1次 (命中率90%)
- L3查询: 0.01次 (命中率99%)
- API调用: 0.01次 (无缓存时)

性能对比:
- L1: 1ms
- L2: 5ms
- L3: 20ms
- API: 500ms
未命中率优化至1% → 平均响应1ms
```

---

## 七、模块初始化顺序

```
┌──────────────────────────────────────────────────────────────┐
│               模块初始化顺序                                 │
└────────────────────┬─────────────────────────────────────────┘
                     │
    1. prompt_registry.py (PromptRegistry)
       └─ 扫描prompts/目录
       └─ 加载所有.txt文件
       └─ 构建缓存
       耗时: <100ms

    2. utils.py (ProgressDisplay, MarkdownImageRenderer)
       └─ 初始化Playwright
       └─ 加载知识库
       耗时: <1秒

    3. data.py (BinanceMarketDataManager, ...)
       └─ 连接数据库 (PG, TimescaleDB)
       └─ 连接Redis
       耗时: <1秒

    4. ai.py (所有AI类)
       └─ 初始化缓存管理器
       └─ 初始化计算器
       └─ 加载模型配置
       耗时: <2秒

    5. bot.py (AITelegramHandler)
       └─ 注册命令处理器
       └─ 设置菜单按钮
       └─ 启动定时任务
       耗时: <1秒

总启动时间: 3-5秒
依赖检查: Redis, PG, TimescaleDB, Playwright
```

---

## 八、调用链路追踪示例

### 完整追踪: BTC@15m分析

```
┌──────────────────────────────────────────────────────────────┐
│ 追踪ID: trace-btc-15m-001                                    │
│ 时间戳: 2025-11-30 12:00:00                                  │
│ 用户: user_12345                                             │
└────────────────────┬─────────────────────────────────────────┘
                     │
[00:00:00.000] 1. bot.py:40 text_message()
               └─ 接收消息: "BTC@15m"

[00:00:00.010] 2. bot.py:32 _ensure_ai_handler()
               └─ 初始化AI处理器

[00:00:00.020] 3. ai.py:14003 handle_coin_selection()
               └─ 解析币种: BTCUSDT

[00:00:00.030] 4. ai.py:12089 AICoinQueryManager.query()
               └─ 开始AI分析

[00:00:00.040] 5. ai.py:12248 _build_analysis_data()
               ├─开始构建数据

[00:00:00.050] 6. data.py:670 get_kline_data()
               ├─查找缓存... 未命中

[00:00:00.060] 7. data.py:885 fetch_kline()
               ├─调用Binance API

[00:00:00.520] 8. data.py:905 返回数据
               ├─写入缓存 (Redis/PG)

[00:00:00.530] 9. ai.py:12450 calculate_all()
               ├─批量计算指标 (8线程)

[00:00:01.200] 10. ai.py:944 calculate_all()完成
               ├─MACD: 金叉, RSI: 65, KDJ: 80

[00:00:01.210] 11. ai.py:2340 MultiTimeframeCalculator.analyze()
               ├─多周期共振 (5m/15m/1h)

[00:00:02.500] 12. ai.py:5080 generate_analysis()
               ├─调用LLM API (Gemini)

[00:00:18.000] 13. ai.py:5500 LLM返回结果
               ├─多头信号, 信心度85%

[00:00:18.010] 14. ai.py:5744 create_report()
               ├─生成Markdown报告

[00:00:18.050] 15. utils.py:878 render_markdown_to_image()
               ├─渲染PNG图片

[00:00:21.500] 16. utils.py:975 图片生成完成

[00:00:21.510] 17. ai.py:14602 send_results()
               └─发送Telegram消息

[00:00:22.000] 18. 完成 (总耗时: 22秒)

关键路径: 12-16步 (LLM调用 + 渲染)
                        18秒 (82%)
```

---

## 九、最佳调用实践

### 9.1 推荐调用方式

```python
# ✅ 推荐: 使用集中管理器 (批量优化)
from ai.src.ai import AICoinQueryManager

manager = AICoinQueryManager()
result = await manager.query(
    symbol="BTCUSDT",
    interval="15m",
    analysis_type="fast"
)
# 优势: 批量计算 + 缓存 + 并发控制

# ✅ 推荐: 缓存优先
from ai.src.ai import AICacheManager

cache = AICacheManager()
data = await cache.get("BTCUSDT_15m_Kline")
if not data:
    data = await fetch_data()
    await cache.put("BTCUSDT_15m_Kline", data)
# 优势: 减少重复计算

# ✅ 推荐: 异步调用
import asyncio

tasks = [
    manager.query("BTCUSDT", "15m"),
    manager.query("ETHUSDT", "15m"),
    manager.query("BNBUSDT", "15m")
]
results = await asyncio.gather(*tasks)
# 优势: 并发执行, 3x速度
```

### 9.2 不推荐调用方式

```python
# ❌ 不推荐: 单独调用指标 (重复IO)
calc_macd(df)
calc_rsi(df)
calc_kdj(df)
# 问题: 3次读取数据

# ❌ 不推荐: 绕过缓存
data = await BinanceAPI.fetch()
# 问题: 重复调用, 无缓存

# ❌ 不推荐: 同步阻塞
def query():
    return await manager.query()  # 同步等待
# 问题: 阻塞事件循环

# ❌ 不推荐: 循环调用
for symbol in symbols:
    await manager.query(symbol)  # 串行
# 问题: N倍时间耗时
```

---

## 十、调用优化建议

```
┌──────────────────────────────────────────────────┐
│           调用优化建议                            │
├─────────────────┬──────────────────────────────┤
│ 问题            │ 解决方案                      │
├─────────────────┼──────────────────────────────┤
│ AI调用慢        │ - 提高缓存命中率             │
│                 │ - 批处理多个币种               │
│                 │ - 异步并发                     │
├─────────────────┼──────────────────────────────┤
│ 数据库IO多      │ - 批量读写                     │
│                 │ - 多级缓存                     │
│                 │ - 索引优化                     │
├─────────────────┼──────────────────────────────┤
│ 渲染图片慢      │ - 限制并发数 (3)              │
│                 │ - 复用浏览器实例               │
│                 │ - 预加载样式                   │
├─────────────────┼──────────────────────────────┤
│ API限流         │ - 批量调用                     │
│                 │ - 智能重试                     │
│                 │ - 优先级队列                   │
├─────────────────┼──────────────────────────────┤
│ 内存占用高      │ - 数据分块                     │
│                 │ - 减少缓存窗口 (1000根)        │
│                 │ - 及时释放资源                 │
└─────────────────┴──────────────────────────────┘

性能目标:
- 响应时间: <15秒 (当前18秒)
- 缓存命中率: >90% (当前85%)
- 并发用户数: 100+ (当前支持50)
- 可用性: 99.9%
```

---

## 附录: 完整类索引

```
文件: ai/ai.py (744KB, 18,000行)
├── AICacheManager (34)
├── TechnicalIndicatorCalculator (944)
├── MultiTimeframeCalculator (2340)
├── DataProcessingPipeline (4690)
├── AIAnalysisEngine (5080)
├── AIPromptBuilder (9028)
├── AICoinQueryManager (12089)
├── AITelegramHandler (13868)
├── SimplifiedAIAnalyzer (15741)
├── ComprehensiveSystemTest (16255)
├── AdvancedFeaturesTestSuite (16802)
├── test_kdj_functionality (17255)
└── test_orderbook_functionality (17295)

文件: data/data.py (444KB, 2,800行)
├── UnifiedDataSaver (23)
├── BinanceRateLimiter (462)
├── SafeRequestManager (620)
├── BinanceMarketDataManager (670)
├── BinanceCoinDataCollector (885)
├── QuickBinanceCollector (1611)
├── FlexibleBinanceCollector (1879)
├── DataIntegrityValidator (2492)
└── NetworkDetector (2766)

文件: utils/utils.py (47KB, 1,100行)
├── get_beijing_time (16)
├── ProgressDisplay (87)
├── MarkdownImageRenderer (403)
└── render_ai_analysis_to_image (1123)

文件: prompt_registry.py (10KB, 154行)
└── PromptRegistry (19)
```

---

**文档结束**

生成时间: 2025-11-30
文档版本: v1.0
维护者: AI Service Team
