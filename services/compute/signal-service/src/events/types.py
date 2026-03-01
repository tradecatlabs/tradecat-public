"""
事件类型定义
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class SignalEvent:
    """信号事件 - 解耦的信号数据结构"""

    # 基础信息
    symbol: str
    signal_type: str
    direction: str  # BUY / SELL / ALERT
    strength: int  # 0-100

    # 消息（i18n key + 参数，由消费端翻译）
    message_key: str
    message_params: dict[str, Any] = field(default_factory=dict)

    # 元数据
    timestamp: datetime = field(default_factory=datetime.now)
    timeframe: str = "1h"
    price: float = 0.0
    source: str = "pg"  # 事件来源（默认：pg）

    # 规则信息
    rule_name: str = ""
    category: str = ""
    subcategory: str = ""
    table: str = ""

    # 扩展数据
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "strength": self.strength,
            "message_key": self.message_key,
            "message_params": self.message_params,
            "timestamp": self.timestamp.isoformat(),
            "timeframe": self.timeframe,
            "price": self.price,
            "source": self.source,
            "rule_name": self.rule_name,
            "category": self.category,
            "subcategory": self.subcategory,
            "table": self.table,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalEvent":
        """从字典创建"""
        ts = data.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif ts is None:
            ts = datetime.now()

        return cls(
            symbol=data.get("symbol", ""),
            signal_type=data.get("signal_type", ""),
            direction=data.get("direction", "ALERT"),
            strength=data.get("strength", 0),
            message_key=data.get("message_key", ""),
            message_params=data.get("message_params", {}),
            timestamp=ts,
            timeframe=data.get("timeframe", "1h"),
            price=data.get("price", 0.0),
            source=data.get("source", "pg"),
            rule_name=data.get("rule_name", ""),
            category=data.get("category", ""),
            subcategory=data.get("subcategory", ""),
            table=data.get("table", ""),
            extra=data.get("extra", {}),
        )
