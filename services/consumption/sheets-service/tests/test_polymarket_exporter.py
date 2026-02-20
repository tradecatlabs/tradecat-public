from __future__ import annotations

from src.polymarket_exporter import _parse_sectioned_csv


def test_parse_sectioned_csv_basic() -> None:
    text = "\n".join(
        [
            "# 套利 Top15",
            "market,profit,volume",
            "A,+1.2K,3",
            "B,-4.5%,0",
            "",
            "# 类别分布",
            "category,count",
            "Crypto,10",
        ]
    )

    values, title_rows, header_rows = _parse_sectioned_csv(text)
    assert title_rows == [0, 4]
    assert header_rows == [1, 5]

    # 第一段：标题行 + 表头 + 2 行数据
    assert values[0] == ["套利 Top15"]
    assert values[1] == ["market", "profit", "volume"]
    assert values[2] == ["A", 1200, 3]
    assert values[3] == ["B", -4.5, 0]

    # 第二段：标题行 + 表头 + 1 行数据
    assert values[4] == ["类别分布"]
    assert values[5] == ["category", "count"]
    assert values[6] == ["Crypto", 10]

