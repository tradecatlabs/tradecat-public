# TradeCat 超级完整系统架构图

> 一图看懂整个系统

```mermaid
graph TB
    %% ========================================
    %% 外部数据源
    %% ========================================
    subgraph EXTERNAL["🌐 外部数据源"]
        EXT_BN_WS["Binance WebSocket<br>实时K线 1m"]
        EXT_BN_REST["Binance REST API<br>期货指标 5m<br>历史数据"]
        EXT_YFINANCE["yfinance<br>美股行情"]
        EXT_AKSHARE["AKShare<br>A股行情"]
        EXT_FRED["FRED API<br>宏观经济"]
        EXT_POLY["Polymarket<br>预测市场"]
        EXT_LLM["LLM APIs<br>Gemini/OpenAI<br>Claude/DeepSeek"]
    end

    %% ========================================
    %% 数据采集层
    %% ========================================
    subgraph COLLECT["📦 数据采集层"]
        subgraph DS["data-service 🟢稳定"]
            DS_WS["ws.py<br>WebSocket采集"]
            DS_MET["metrics.py<br>期货指标采集"]
            DS_BF["backfill.py<br>历史回填"]
            DS_ALPHA["alpha.py<br>Alpha列表"]
        end
        
        subgraph DC["datacat-service 🟡预览"]
            DC_WS["cryptofeed.py<br>WS采集"]
            DC_MET["http.py<br>指标采集"]
            DC_BF["http_zip.py<br>压缩包回填"]
        end
        
        subgraph MS["markets-service 🟡预览"]
            MS_US["美股采集"]
            MS_CN["A股采集"]
            MS_MACRO["宏观数据"]
        end
        
        subgraph PS["predict-service 🟡预览"]
            PS_POLY["Polymarket监控"]
            PS_KALSHI["Kalshi监控"]
        end
    end

    %% ========================================
    %% 持久化层
    %% ========================================
    subgraph STORAGE["🗄️ 持久化层"]
        subgraph TSDB["TimescaleDB :5434"]
            TSDB_C1M[("candles_1m<br>3.73亿条<br>99GB")]
            TSDB_F5M[("futures_metrics_5m<br>9457万条<br>5GB")]
            TSDB_MV[("物化视图<br>5m/15m/1h/4h/1d/1w")]
        end
        
        subgraph PG_STORE["PostgreSQL Schemas（统一存储）"]
            PG_TG[("tg_cards.*<br>指标表（38张）")]
            PG_SIG[("signal_state.*<br>信号状态（cooldown/subs/history）")]
            PG_SHEETS[("sheets_state.*<br>Sheets 幂等 keys")]
        end
    end

    %% ========================================
    %% 计算层 - trading-service
    %% ========================================
    subgraph COMPUTE["📊 计算层 trading-service 🟢稳定"]
        TS_SCHED["simple_scheduler.py<br>定时调度 (每分钟)"]
        
        subgraph TS_ENGINE["Engine 计算引擎"]
            TS_IO["io.py 只读<br>load_klines()<br>preload_futures_cache()"]
            TS_COMP["compute.py 纯计算<br>compute_all()<br>多进程并行"]
            TS_STORE["storage.py 只写<br>write_results()<br>update_market_share()"]
        end
        
        subgraph TS_IND["34个指标模块"]
            IND_T["趋势 (8)<br>EMA/MACD/SuperTrend<br>ADX/Ichimoku/趋势云<br>Donchian/Keltner"]
            IND_M["动量 (6)<br>RSI/KDJ/CCI<br>WilliamsR/MFI<br>RSI谐波"]
            IND_V["波动 (4)<br>布林带/ATR<br>ATR波幅/支撑阻力"]
            IND_VOL["成交量 (6)<br>OBV/CVD/VWAP<br>量比/流动性/VPVR"]
            IND_P["形态 (2)<br>61种K线形态<br>价格形态"]
            IND_F["期货 (8)<br>持仓量/多空比<br>资金费率/爆仓<br>情绪聚合"]
        end
    end

    %% ========================================
    %% 信号检测层 - signal-service
    %% ========================================
    subgraph SIGNAL["🔔 信号检测层 signal-service 🟢稳定"]
        SIG_MAIN["__main__.py<br>PG only"]
        
        subgraph SIG_ENG["PG 引擎"]
            SIG_PG["PGSignalEngine<br>读取 tg_cards + K线/期货"]
        end
        
        subgraph SIG_RULES["129条规则 (8分类)"]
            R_CORE["core 核心"]
            R_MOM["momentum 动量<br>RSI超买卖/KDJ金死叉"]
            R_TREND["trend 趋势<br>均线交叉/趋势突破"]
            R_VOL["volatility 波动<br>布林突破/ATR异常"]
            R_VOLUME["volume 成交量<br>放量突破/OBV背离"]
            R_FUT["futures 期货<br>多空比极端/OI异常"]
            R_PAT["pattern 形态<br>头肩/双顶/三角"]
            R_MISC["misc 杂项"]
        end
        
        SIG_PUB["SignalPublisher<br>事件发布总线"]
        SIG_COOL["cooldown.py<br>冷却管理"]
        SIG_FMT["formatters/<br>信号格式化"]
    end

    %% ========================================
    %% AI分析层 - ai-service
    %% ========================================
    subgraph AI["🧠 AI分析层 ai-service 🟢稳定"]
        AI_FETCH["data/fetcher.py<br>数据获取"]
        AI_PROMPT["prompt/<br>提示词管理"]
        AI_LLM["llm/<br>多模型客户端"]
        AI_WYCKOFF["Wyckoff方法论<br>市场结构分析"]
    end

    %% ========================================
    %% 用户交互层 - telegram-service
    %% ========================================
    subgraph TG["🤖 用户交互层 telegram-service 🟢稳定"]
        TG_BOT["bot/app.py<br>Bot主程序"]
        
        subgraph TG_HANDLER["handlers/ 命令处理"]
            TG_H_DATA["/data 数据面板"]
            TG_H_AI["/ai AI分析"]
            TG_H_QUERY["/query 币种查询"]
            TG_H_MSG["BTC! 单币查询<br>BTC!! TXT导出<br>BTC@ AI分析"]
        end
        
        subgraph TG_CARDS["39张排行榜卡片"]
            subgraph CARDS_B["basic/ (10张)"]
                CB_1["RSI排行"]
                CB_2["KDJ排行"]
                CB_3["MACD排行"]
                CB_4["布林带排行"]
                CB_5["OBV排行"]
                CB_6["支撑阻力排行"]
                CB_7["成交量排行"]
                CB_8["资金费率排行"]
                CB_9["成交额排行"]
                CB_10["RSI谐波排行"]
            end
            
            subgraph CARDS_A["advanced/ (11张)"]
                CA_1["EMA排行"]
                CA_2["ATR排行"]
                CA_3["CVD排行"]
                CA_4["MFI排行"]
                CA_5["VWAP排行"]
                CA_6["K线形态排行"]
                CA_7["趋势线排行"]
                CA_8["超级趋势排行"]
                CA_9["流动性排行"]
                CA_10["VPVR排行"]
                CA_11["趋势云排行"]
            end
            
            subgraph CARDS_F["futures/ (18张)"]
                CF_1["持仓量排行"]
                CF_2["多空比排行"]
                CF_3["主动买卖比排行"]
                CF_4["爆仓排行"]
                CF_5["情绪聚合"]
                CF_6["市场深度"]
                CF_7["OI异常排行"]
                CF_8["资金费率卡片"]
                CF_9["持仓价值排行"]
                CF_10["全市场情绪排行"]
                CF_11["期货持仓对比排行"]
                CF_12["反转信号排行"]
                CF_13["OI变化排行"]
                CF_14["大户多空比排行"]
                CF_15["散户多空比排行"]
                CF_16["持仓拥挤度排行"]
                CF_17["持仓成交比排行"]
                CF_18["期货基础排行"]
            end
        end
        
        TG_ADAPTER["signals/adapter.py<br>信号适配器"]
        TG_PROVIDER["data_provider.py<br>数据提供者"]
        TG_I18N["i18n.py 中/英"]
        TG_SNAPSHOT["single_token_snapshot.py<br>单币详情面板"]
    end

    %% ========================================
    %% API服务层
    %% ========================================
    subgraph API["🔌 API服务层 api-service 🟡预览 :8000"]
        API_APP["app.py FastAPI"]
        
        subgraph API_ROUTES["9个API路由"]
            API_R1["GET /api/futures/ohlc<br>K线数据"]
            API_R2["GET /api/futures/open-interest<br>持仓量"]
            API_R3["GET /api/futures/funding-rate<br>资金费率"]
            API_R4["GET /api/futures/metrics<br>期货指标"]
            API_R5["GET /api/futures/base-data<br>基础数据"]
            API_R6["GET /api/futures/coins<br>币种列表"]
            API_R7["GET /api/indicator/*<br>技术指标"]
            API_R8["GET /api/signal/*<br>信号查询"]
            API_R9["GET /api/health<br>健康检查"]
        end
    end

    %% ========================================
    %% 可视化层
    %% ========================================
    subgraph VIS["📈 可视化层 vis-service 🟡预览 :8087"]
        VIS_APP["app.py FastAPI"]
        VIS_KLINE["K线图渲染<br>mplfinance"]
        VIS_IND["指标图渲染"]
        VIS_VPVR["VPVR渲染"]
    end

    %% ========================================
    %% 交易执行层
    %% ========================================
    subgraph TRADE["💹 交易执行层"]
        subgraph ORD["order-service 🟡预览"]
            ORD_MM["market-maker/<br>Avellaneda-Stoikov做市"]
            ORD_EXEC["交易执行引擎"]
        end
        
        subgraph AWS["aws-service 🟢稳定"]
            AWS_SYNC["db_sync_service.py<br>SQLite远端同步"]
        end
    end

    %% ========================================
    %% 其他预览服务
    %% ========================================
    subgraph OTHER["🔬 其他预览服务"]
        FATE["fate-service 🟡预览 :8001<br>命理服务"]
        NOFX["nofx-dev 🟡预览<br>NOFX AI交易 (Go)"]
    end

    %% ========================================
    %% 运维支撑层
    %% ========================================
    subgraph OPS["⚙️ 运维支撑层"]
        subgraph SCRIPTS["全局脚本 scripts/"]
            SCR_INIT["init.sh 初始化"]
            SCR_START["start.sh 启动/守护"]
            SCR_VERIFY["verify.sh 代码验证"]
            SCR_CHECK["check_env.sh 环境检查"]
            SCR_EXPORT["export_timescaledb.sh 备份"]
        end
        
        subgraph LIBS["共享库 libs/common/"]
            LIB_I18N["i18n.py 国际化"]
            LIB_SYM["symbols.py 币种管理<br>main4/main6/main20/all"]
            LIB_PROXY["proxy_manager.py 代理"]
        end
        
        subgraph CONFIG["配置 config/"]
            CFG_ENV[".env 生产配置<br>DATABASE_URL<br>BOT_TOKEN<br>HTTP_PROXY<br>SYMBOLS_GROUPS<br>MAX_WORKERS<br>COOLDOWN_SECONDS"]
            CFG_EXAMPLE[".env.example 模板"]
            CFG_LOG["logrotate.conf 日志轮转"]
        end
    end

    %% ========================================
    %% 最终用户
    %% ========================================
    USER["👤 Telegram用户"]

    %% ========================================
    %% 连接关系 - 数据采集
    %% ========================================
    EXT_BN_WS --> DS_WS
    EXT_BN_WS --> DC_WS
    EXT_BN_REST --> DS_MET
    EXT_BN_REST --> DS_BF
    EXT_BN_REST --> DS_ALPHA
    EXT_BN_REST --> DC_MET
    EXT_BN_REST --> DC_BF
    EXT_YFINANCE --> MS_US
    EXT_AKSHARE --> MS_CN
    EXT_FRED --> MS_MACRO
    EXT_POLY --> PS_POLY
    EXT_LLM --> AI_LLM

    %% ========================================
    %% 连接关系 - 采集到存储
    %% ========================================
    DS_WS --> TSDB_C1M
    DS_MET --> TSDB_F5M
    DS_BF --> TSDB_C1M
    DC_WS --> TSDB_C1M
    DC_MET --> TSDB_F5M
    DC_BF --> TSDB_C1M
    MS_US --> TSDB_C1M
    MS_CN --> TSDB_C1M
    TSDB_C1M --> TSDB_MV
    TSDB_F5M --> TSDB_MV

    %% ========================================
    %% 连接关系 - 计算层
    %% ========================================
    TS_SCHED --> TS_IO
    TSDB_C1M --> TS_IO
    TSDB_F5M --> TS_IO
    TSDB_MV --> TS_IO
    TS_IO --> TS_COMP
    TS_COMP --> IND_T
    TS_COMP --> IND_M
    TS_COMP --> IND_V
    TS_COMP --> IND_VOL
    TS_COMP --> IND_P
    TS_COMP --> IND_F
    IND_T --> TS_STORE
    IND_M --> TS_STORE
    IND_V --> TS_STORE
    IND_VOL --> TS_STORE
    IND_P --> TS_STORE
    IND_F --> TS_STORE
    TS_STORE --> PG_TG

    %% ========================================
    %% 连接关系 - 信号检测
    %% ========================================
    SIG_MAIN --> SIG_PG
    PG_TG --> SIG_PG
    TSDB_C1M --> SIG_PG
    TSDB_F5M --> SIG_PG
    SIG_PG --> R_CORE
    SIG_PG --> R_MOM
    SIG_PG --> R_TREND
    SIG_PG --> R_VOL
    SIG_PG --> R_VOLUME
    SIG_PG --> R_FUT
    SIG_PG --> R_PAT
    SIG_PG --> R_MISC
    R_CORE --> SIG_PUB
    R_MOM --> SIG_PUB
    R_TREND --> SIG_PUB
    R_VOL --> SIG_PUB
    R_VOLUME --> SIG_PUB
    R_FUT --> SIG_PUB
    R_PAT --> SIG_PUB
    R_MISC --> SIG_PUB
    SIG_PUB --> SIG_COOL
    SIG_COOL --> PG_SIG
    SIG_PUB --> PG_SIG
    SIG_PUB --> SIG_FMT

    %% ========================================
    %% 连接关系 - AI分析
    %% ========================================
    TSDB_C1M --> AI_FETCH
    PG_TG --> AI_FETCH
    AI_FETCH --> AI_PROMPT
    AI_PROMPT --> AI_LLM
    AI_LLM --> AI_WYCKOFF

    %% ========================================
    %% 连接关系 - Telegram
    %% ========================================
    PG_TG --> TG_PROVIDER
    TG_PROVIDER --> TG_CARDS
    TG_CARDS --> TG_BOT
    SIG_FMT --> TG_ADAPTER
    TG_ADAPTER --> TG_BOT
    AI_WYCKOFF --> TG_BOT
    TG_HANDLER --> TG_BOT
    TG_SNAPSHOT --> TG_BOT
    TG_I18N --> TG_BOT
    TG_BOT --> USER

    %% ========================================
    %% 连接关系 - API/VIS
    %% ========================================
    PG_TG --> API_ROUTES
    TSDB_C1M --> API_ROUTES
    TSDB_F5M --> API_ROUTES
    API_ROUTES --> API_APP
    PG_TG --> VIS_APP
    TSDB_C1M --> VIS_APP

    %% ========================================
    %% 连接关系 - 交易
    %% ========================================
    TSDB_C1M --> ORD_MM
    TSDB_F5M --> ORD_MM
    PG_TG --> AWS_SYNC

    %% ========================================
    %% 连接关系 - 运维
    %% ========================================
    CFG_ENV --> DS
    CFG_ENV --> COMPUTE
    CFG_ENV --> SIGNAL
    CFG_ENV --> TG
    CFG_ENV --> AI
    CFG_ENV --> API
    LIB_SYM --> DS
    LIB_SYM --> COMPUTE
    LIB_SYM --> SIGNAL
    LIB_I18N --> TG

    %% ========================================
    %% 样式
    %% ========================================
    style TSDB_C1M fill:#4169E1,color:#fff
    style TSDB_F5M fill:#4169E1,color:#fff
    style TSDB_MV fill:#6495ED,color:#fff
    style PG_TG fill:#2E8B57,color:#fff
    style PG_SIG fill:#3CB371,color:#fff
    style PG_SHEETS fill:#3CB371,color:#fff
    style SIG_PUB fill:#FF6347,color:#fff
    style USER fill:#FFD700,color:#000
    style TG_BOT fill:#26A5E4,color:#fff
    style API_APP fill:#009688,color:#fff
    style VIS_APP fill:#9C27B0,color:#fff
    style TS_COMP fill:#FF9800,color:#fff
    style AI_WYCKOFF fill:#E91E63,color:#fff
```

---

## 系统统计速览

| 维度 | 数量 |
|:---|:---:|
| 微服务 | 14 (稳定6 + 预览8) |
| 技术指标 | 34 |
| 信号规则 | 129 |
| 排行榜卡片 | 39 |
| API路由 | 9 |
| K线数据 | 3.73亿条 |
| 期货数据 | 9457万条 |
| 支持LLM | 4 |
| 支持语言 | 2 |
