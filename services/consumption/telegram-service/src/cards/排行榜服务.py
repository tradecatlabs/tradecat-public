"""排行榜卡片共享常量与周期规范（Query Service Only）

本模块只提供：
- 各类卡片的“周期候选列表”
- `normalize_period`：把用户请求周期规范化到允许集合

硬约束：
- consumption 层禁止直连数据库
- 本模块不包含任何数据读取/回退逻辑；数据读取由 `cards.data_provider` 统一完成（HTTP 调 Query Service）
"""

from __future__ import annotations

from typing import Sequence

# 文档约定的固定周期顺序（展示层允许含 1m，但会在 normalize_period 中按规则映射）
DEFAULT_PERIODS = ["1m", "5m", "15m", "1h", "4h", "1d", "1w"]

# 各卡片可用周期（展示层约定：日线统一为 1d；禁止 legacy 24h）
VOLUME_FUTURES_PERIODS = ["5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w"]
VOLUME_SPOT_PERIODS = ["5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w"]
POSITION_PERIODS = ["5m", "15m", "30m", "1h", "4h", "1d", "1w"]
LIQUIDATION_PERIODS = ["1h", "4h", "12h", "1d", "1w"]
MONEY_FLOW_FUTURES_PERIODS = ["5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w"]
MONEY_FLOW_SPOT_PERIODS = ["5m", "15m", "30m", "1h", "4h", "12h", "1d", "1w"]
MONEY_FLOW_PERIODS = MONEY_FLOW_SPOT_PERIODS


def normalize_period(requested: str, allowed: Sequence[str], default: str = "4h") -> str:
    """将请求周期映射到实际支持的周期集合。

    规则：
    - 1m 在多数“衍生指标/聚合”场景下不可用：统一映射到 5m
    - 24h/1day 等 legacy 写法统一映射到 1d
    - 若映射后仍不在 allowed：优先 default，否则回退 allowed[0]
    """
    alias = {
        "1m": "5m",  # 聚合粒度下限
        "24h": "1d",  # 兼容旧写法，统一映射到 1d
        "1day": "1d",
        "1w": "1w",
    }
    target = alias.get((requested or "").strip(), (requested or "").strip())
    if target in allowed:
        return target
    if default in allowed:
        return default
    return allowed[0] if allowed else (default or "4h")


__all__ = [
    "DEFAULT_PERIODS",
    "VOLUME_FUTURES_PERIODS",
    "VOLUME_SPOT_PERIODS",
    "POSITION_PERIODS",
    "LIQUIDATION_PERIODS",
    "MONEY_FLOW_FUTURES_PERIODS",
    "MONEY_FLOW_SPOT_PERIODS",
    "MONEY_FLOW_PERIODS",
    "normalize_period",
]

