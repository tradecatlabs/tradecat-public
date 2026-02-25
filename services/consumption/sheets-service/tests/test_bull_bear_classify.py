from __future__ import annotations

from src.sa_sheets_writer import _classify_bull_bear


def test_classify_bull_bear_basic_words() -> None:
    assert _classify_bull_bear("多") == 1
    assert _classify_bull_bear("空") == -1
    assert _classify_bull_bear("空转多") == 1
    assert _classify_bull_bear("多转空") == -1

    assert _classify_bull_bear("金叉") == 1
    assert _classify_bull_bear("死叉") == -1
    assert _classify_bull_bear("放量") == 1
    assert _classify_bull_bear("缩量") == -1

    assert _classify_bull_bear("支撑") == 1
    assert _classify_bull_bear("阻力") == -1


def test_classify_bull_bear_discrete_numbers_only() -> None:
    # strict: only -1/0/+1 are treated as direction
    assert _classify_bull_bear("1") == 1
    assert _classify_bull_bear("+1") == 1
    assert _classify_bull_bear("-1") == -1
    assert _classify_bull_bear("0") == 0

    # continuous numbers must NOT be colored (avoid misleading 成交额/净流/涨跌幅)
    assert _classify_bull_bear("0.7") == 0
    assert _classify_bull_bear("-0.7") == 0
    assert _classify_bull_bear("+472.08K") == 0
    assert _classify_bull_bear("-2.3%") == 0
    assert _classify_bull_bear("1453") == 0

