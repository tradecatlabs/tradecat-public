"""
格式化器测试
"""


def test_strength_bar():
    """测试强度条生成"""
    from src.formatters.base import strength_bar
    
    assert strength_bar(100) == "██████████"
    assert strength_bar(50) == "█████░░░░░"
    assert strength_bar(0) == "░░░░░░░░░░"
    assert strength_bar(None) == "░░░░░░░░░░"


def test_fmt_price():
    """测试价格格式化"""
    from src.formatters.base import fmt_price
    
    assert fmt_price(50000) == "$50,000"
    assert fmt_price(3.5) == "$3.50"
    assert fmt_price(0.00015) == "$0.0001"  # 4位小数
    assert fmt_price(None) == "-"


def test_fmt_pct():
    """测试百分比格式化"""
    from src.formatters.base import fmt_pct
    
    assert fmt_pct(5.5) == "+5.50%"
    assert fmt_pct(-3.2) == "-3.20%"
    assert fmt_pct(0) == "0.00%"
    assert fmt_pct(None) == "-"


def test_fmt_vol():
    """测试成交额格式化"""
    from src.formatters.base import fmt_vol
    
    assert fmt_vol(1_500_000_000) == "$1.50B"
    assert fmt_vol(50_000_000) == "$50.0M"
    assert fmt_vol(5000) == "$5K"
    assert fmt_vol(None) == "-"


def test_base_formatter():
    """测试基础格式化器"""
    from src.formatters.base import BaseFormatter
    
    formatter = BaseFormatter()
    
    result = formatter.format_basic(
        symbol="BTCUSDT",
        direction="BUY",
        signal_type="price_surge",
        strength=75,
        price=50000,
        timeframe="5m",
        message="价格急涨 3.5%",
    )
    
    assert "BTCUSDT" in result
    assert "BUY" in result
    assert "🟢" in result
    assert "75%" in result
