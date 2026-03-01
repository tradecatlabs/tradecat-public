"""
指标基类

所有指标继承 Indicator 类，使用 @register 装饰器自动注册。

输出规范:
    - 必须包含: 交易对, 周期, 数据时间
    - 数据时间: ISO8601 格式
    - 结果写入 PostgreSQL（tg_cards schema），表名 = meta.name
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any
import pandas as pd


# 默认最小数据量
DEFAULT_MIN_DATA = 5


@dataclass
class IndicatorMeta:
    """指标元信息"""
    name: str                    # 指标名称（表名）
    lookback: int = 300          # 所需 K 线窗口
    is_incremental: bool = True  # True=增量计算, False=批量计算
    min_data: int = 5            # 最小数据量要求


class Indicator(ABC):
    """指标基类"""

    meta: IndicatorMeta

    @abstractmethod
    def compute(self, df: pd.DataFrame, symbol: str, interval: str) -> pd.DataFrame:
        """
        计算指标
        
        Args:
            df: K 线数据 (columns: open, high, low, close, volume, ...)
            symbol: 交易对
            interval: 周期
            
        Returns:
            DataFrame，必须包含: 交易对, 周期, 数据时间, ...指标字段
        """
        pass

    def _check_data(self, df: pd.DataFrame, min_required: int = None) -> bool:
        """检查数据是否充足"""
        min_req = min_required or getattr(self.meta, 'min_data', DEFAULT_MIN_DATA)
        return len(df) >= min_req

    def _make_insufficient_result(self, df: pd.DataFrame, symbol: str, interval: str,
                                   fields: Dict[str, Any]) -> pd.DataFrame:
        """生成数据不足时的结果（所有值为None，状态标记为数据不足）"""
        data = {k: None for k in fields}
        if "信号" in fields or "信号概述" in fields:
            key = "信号" if "信号" in fields else "信号概述"
            data[key] = "数据不足"
        return self._make_result(df, symbol, interval, data)

    def _make_result(self, df: pd.DataFrame, symbol: str, interval: str, data: dict, timestamp=None) -> pd.DataFrame:
        """构建标准输出格式，前3列固定为: 交易对, 周期, 数据时间"""
        if timestamp is None:
            timestamp = df.index[-1] if not df.empty else None
        ts_str = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp)

        # 固定前3列顺序
        row = {"交易对": symbol, "周期": interval, "数据时间": ts_str, **data}
        result = pd.DataFrame([row])
        # 确保列顺序
        cols = ["交易对", "周期", "数据时间"] + [c for c in result.columns if c not in ("交易对", "周期", "数据时间")]
        return result[cols]


# 指标注册表
_registry: dict[str, type[Indicator]] = {}


def register(cls: type[Indicator]) -> type[Indicator]:
    """装饰器：注册指标到全局注册表"""
    _registry[cls.meta.name] = cls
    return cls


def _filter_indicators(indicators: dict) -> dict:
    """根据环境变量过滤指标"""
    import os
    enabled = [i.strip().lower() for i in os.environ.get("INDICATORS_ENABLED", "").split(",") if i.strip()]
    disabled = [i.strip().lower() for i in os.environ.get("INDICATORS_DISABLED", "").split(",") if i.strip()]

    def match(name: str) -> bool:
        name_lower = name.lower()
        # 检查是否匹配（支持部分匹配）
        for d in disabled:
            if d in name_lower:
                return False
        if enabled:
            for e in enabled:
                if e in name_lower:
                    return True
            return False
        return True

    return {k: v for k, v in indicators.items() if match(k)}


def get_indicator(name: str) -> Optional[type[Indicator]]:
    return _registry.get(name)


def get_all_indicators() -> dict[str, type[Indicator]]:
    return _filter_indicators(_registry.copy())


def get_batch_indicators() -> dict[str, type[Indicator]]:
    """获取批量计算指标 (is_incremental=False)"""
    return _filter_indicators({k: v for k, v in _registry.items() if not v.meta.is_incremental})


def get_incremental_indicators() -> dict[str, type[Indicator]]:
    """获取增量计算指标 (is_incremental=True)"""
    return _filter_indicators({k: v for k, v in _registry.items() if v.meta.is_incremental})
