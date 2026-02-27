# TradeCat 架构优化与重构计划

> 生成时间: 2026-01-29  
> 基于: architecture_analysis_report.md, module_health_analysis.md

---

## 1. 重构优先级矩阵

| 优先级 | 任务 | 影响范围 | 预估工作量 | 风险 |
|:---:|:---|:---|:---:|:---:|
| P0 | 端口标准化 (5433→5434) | 全局 | 2h | 低 |
| P1 | 统一配置管理 | 全局 | 4h | 低 |
| P2 | Cards 基类抽象 | telegram-service | 8h | 中 |
| P2 | API 数据访问层 | api-service | 6h | 低 |
| P3 | datacat/data-service 整合规划 | 数据采集层 | 需评估 | 高 |
| P3 | 日志格式统一 | 全局 | 4h | 低 |

---

## 2. Phase 1: 基础设施优化 (1-2 天)

### 2.1 任务 P0: 端口标准化

**目标**: 统一 TimescaleDB 端口为 5434

**变更文件清单**:
```
scripts/export_timescaledb.sh          # 改 5433→5434
scripts/export_timescaledb_main4.sh    # 改 5433→5434
scripts/timescaledb_compression.sh     # 改 5433→5434
README.md                              # 更新所有示例命令
README_EN.md                           # 更新所有示例命令
AGENTS.md                              # 更新第 7.8 节
```

**执行步骤**:
```bash
# 1. 备份当前脚本
cp scripts/export_timescaledb.sh scripts/export_timescaledb.sh.bak

# 2. 批量替换（使用 sed）
sed -i 's/5433/5434/g' scripts/export_timescaledb.sh
sed -i 's/5433/5434/g' scripts/export_timescaledb_main4.sh
sed -i 's/5433/5434/g' scripts/timescaledb_compression.sh

# 3. 验证
grep -r "5433" scripts/

# 4. 更新文档
# 手动编辑 README.md / README_EN.md / AGENTS.md
```

**验证命令**:
```bash
# 确认端口一致
grep -rn "5433\|5434" config/ scripts/ | sort
```

---

### 2.2 任务 P1: 统一配置管理

**目标**: 创建 `libs/common/config.py` 统一配置入口

**新建文件**: `libs/common/config.py`

```python
"""
TradeCat 统一配置管理

所有服务应从此模块导入配置，而非直接读取 os.environ。
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from functools import lru_cache

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
ENV_FILE = CONFIG_DIR / ".env"


def _load_env_file():
    """加载 config/.env 到 os.environ (仅未设置的变量)"""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env_file()


@dataclass(frozen=True)
class DatabaseConfig:
    """数据库配置"""
    timescale_url: str = field(default_factory=lambda: os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5434/market_data"
    ))
    sqlite_market_data: Path = field(default_factory=lambda: (
        PROJECT_ROOT / "assets/database/services/telegram-service/market_data.db"
    ))
    sqlite_cooldown: Path = field(default_factory=lambda: (
        PROJECT_ROOT / "assets/database/services/signal-service/cooldown.db"
    ))
    sqlite_history: Path = field(default_factory=lambda: (
        PROJECT_ROOT / "assets/database/services/signal-service/signal_history.db"
    ))


@dataclass(frozen=True)
class ServiceConfig:
    """服务配置"""
    max_workers: int = field(default_factory=lambda: int(os.getenv("MAX_WORKERS", "4")))
    compute_backend: str = field(default_factory=lambda: os.getenv("COMPUTE_BACKEND", "thread"))
    default_locale: str = field(default_factory=lambda: os.getenv("DEFAULT_LOCALE", "en"))
    http_proxy: str = field(default_factory=lambda: os.getenv("HTTP_PROXY", ""))


@dataclass(frozen=True)
class TradeCatConfig:
    """TradeCat 全局配置"""
    project_root: Path = PROJECT_ROOT
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)


@lru_cache(maxsize=1)
def get_config() -> TradeCatConfig:
    """获取全局配置（单例）"""
    return TradeCatConfig()


# 快捷访问
config = get_config()
```

**迁移示例** (trading-service):
```python
# 旧代码
from .config import config
db_url = config.db_url

# 新代码
from libs.common.config import config
db_url = config.database.timescale_url
```

---

## 3. Phase 2: 代码复用优化 (3-5 天)

### 3.1 任务 P2-A: Cards 基类抽象

**目标**: 减少 20+ 卡片的代码重复

**新建文件**: `services/consumption/telegram-service/src/cards/base_ranking_card.py`

```python
"""
排行榜卡片基类

所有排行榜卡片继承此类，只需定义配置即可。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Callable
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .data_provider import RankingDataProvider
from .i18n import t


@dataclass
class CardConfig:
    """卡片配置"""
    name: str                       # 卡片名称
    table: str                      # SQLite 表名
    title_key: str                  # i18n 标题键
    default_sort_field: str         # 默认排序字段
    default_sort_asc: bool = False  # 默认升序
    default_limit: int = 10         # 默认条数
    intervals: List[str] = None     # 可选周期
    direction_field: str = None     # 方向字段（可选）
    
    def __post_init__(self):
        if self.intervals is None:
            self.intervals = ["5m", "15m", "1h", "4h", "1d"]


class BaseRankingCard(ABC):
    """排行榜卡片基类"""
    
    @property
    @abstractmethod
    def config(self) -> CardConfig:
        """返回卡片配置"""
        pass
    
    def __init__(self):
        self.provider = RankingDataProvider()
    
    def get_data(self, interval: str, direction: str = None, 
                 sort_field: str = None, sort_asc: bool = None,
                 limit: int = None) -> list:
        """获取排行数据"""
        return self.provider.get_ranking(
            table=self.config.table,
            interval=interval,
            direction=direction,
            sort_field=sort_field or self.config.default_sort_field,
            sort_asc=sort_asc if sort_asc is not None else self.config.default_sort_asc,
            limit=limit or self.config.default_limit,
        )
    
    def format_row(self, row: dict, rank: int) -> str:
        """格式化单行数据（可覆盖）"""
        return f"{rank}. {row.get('币种', row.get('symbol', 'N/A'))}"
    
    def format_message(self, data: list, interval: str) -> str:
        """格式化完整消息"""
        title = t(self.config.title_key, interval=interval)
        lines = [f"📊 {title}", ""]
        for i, row in enumerate(data, 1):
            lines.append(self.format_row(row, i))
        return "\n".join(lines)
    
    def build_keyboard(self, current_interval: str) -> InlineKeyboardMarkup:
        """构建键盘"""
        buttons = []
        for iv in self.config.intervals:
            text = f"{'✅' if iv == current_interval else ''}{iv}"
            buttons.append(InlineKeyboardButton(
                text, callback_data=f"{self.config.name}:{iv}"
            ))
        return InlineKeyboardMarkup([buttons])


# === 使用示例 ===
class KDJRankingCard(BaseRankingCard):
    @property
    def config(self) -> CardConfig:
        return CardConfig(
            name="kdj_ranking",
            table="KDJ随机指标扫描器.py",
            title_key="cards.kdj.title",
            default_sort_field="强度",
            direction_field="方向",
        )
    
    def format_row(self, row: dict, rank: int) -> str:
        direction = "🟢" if row.get("方向") == "多" else "🔴"
        return f"{rank}. {direction} {row['币种']} J={row['J值']:.1f}"
```

**迁移计划**:
1. 创建 `BaseRankingCard` 基类
2. 从最简单的卡片开始迁移 (KDJ → RSI → MACD → ...)
3. 每迁移一个卡片，验证功能正常后再继续
4. 最终删除冗余代码

---

### 3.2 任务 P2-B: API 数据访问层

**目标**: 统一 api-service 的数据库访问

**新建目录结构**:
```
services/consumption/api-service/src/
├── repositories/
│   ├── __init__.py
│   ├── base.py
│   ├── timescale.py
│   └── sqlite.py
└── routers/
    └── ... (现有路由)
```

**新建文件**: `repositories/base.py`

```python
"""
数据访问层基类
"""
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
import psycopg2
import sqlite3


class BaseRepository(ABC):
    """Repository 基类"""
    
    @abstractmethod
    def query(self, sql: str, params: tuple = None) -> List[Dict[str, Any]]:
        """执行查询"""
        pass


class TimescaleRepository(BaseRepository):
    """TimescaleDB Repository"""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._conn = None
    
    @contextmanager
    def connection(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.database_url)
        try:
            yield self._conn
        except Exception:
            self._conn.rollback()
            raise
    
    def query(self, sql: str, params: tuple = None) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]


class SQLiteRepository(BaseRepository):
    """SQLite Repository"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def query(self, sql: str, params: tuple = None) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql, params or ())
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
```

---

## 4. Phase 3: 架构演进 (持续)

### 4.1 任务 P3-A: datacat-service 整合规划

**背景**: 
- data-service: 当前生产使用，采集逻辑简单但稳定
- datacat-service: 新架构，分层设计更清晰，但尚在开发中

**建议路线图**:

```
Q1 2026:
├── datacat-service 功能验证
│   ├── 回填功能测试 (backfill)
│   ├── 实时采集测试 (ws/metrics)
│   └── 性能基准测试
└── 并行运行对比

Q2 2026:
├── datacat-service 作为主采集器
├── data-service 降级为备用
└── 完成数据一致性验证

Q3 2026:
├── 废弃 data-service
└── 更新文档和脚本
```

**风险控制**:
- 保持双采集器并行至少 1 个月
- 设置数据一致性监控告警
- 保留 data-service 代码作为回滚方案

---

### 4.2 任务 P3-B: 日志格式统一

**目标**: 所有服务采用统一的 JSON Lines 日志格式

**新建文件**: `libs/common/logging.py`

```python
"""
统一日志配置
"""
import logging
import json
import sys
from datetime import datetime
from typing import Optional


class JSONFormatter(logging.Formatter):
    """JSON Lines 格式化器"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            log_data["exc"] = self.formatException(record.exc_info)
        # 附加自定义字段
        for key in ["symbol", "interval", "trace_id", "service"]:
            if hasattr(record, key):
                log_data[key] = getattr(record, key)
        return json.dumps(log_data, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    service: str = "tradecat",
    json_format: bool = True,
    log_file: Optional[str] = None,
):
    """配置日志"""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    
    # 清除现有 handler
    root.handlers.clear()
    
    # 格式化器
    if json_format:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        )
    
    # 控制台 handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)
    
    # 文件 handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    
    # 注入 service 名称
    old_factory = logging.getLogRecordFactory()
    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.service = service
        return record
    logging.setLogRecordFactory(record_factory)
```

---

## 5. 验收标准

### 5.1 Phase 1 验收

- [ ] 所有脚本和文档使用统一端口 5434
- [ ] `grep -r "5433" scripts/ config/` 无结果
- [ ] `libs/common/config.py` 创建并通过单元测试
- [ ] 至少 1 个服务完成配置迁移

### 5.2 Phase 2 验收

- [ ] `BaseRankingCard` 基类创建
- [ ] 至少 5 个卡片完成迁移
- [ ] api-service repositories 层创建
- [ ] 所有 API 路由使用 repository

### 5.3 Phase 3 验收

- [ ] datacat-service 通过生产验证
- [ ] 统一日志格式在所有服务生效
- [ ] 日志可被 ELK/Loki 正常解析

---

## 6. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|:---|:---:|:---:|:---|
| 端口切换导致数据丢失 | 低 | 高 | 先备份，再切换 |
| Cards 迁移破坏功能 | 中 | 中 | 逐个迁移，每步验证 |
| datacat 不稳定 | 中 | 高 | 双采集并行 1 个月 |
| 日志格式影响监控 | 低 | 低 | 先在预览服务测试 |
