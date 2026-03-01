"""
指标计算微服务

从 TimescaleDB 读取 K 线数据，计算技术指标，写入 PostgreSQL（tg_cards schema）。

用法:
    python -m indicator_service              # 计算全部指标
    python -m indicator_service --mode batch # 只计算批量指标
    python -m indicator_service --mode stream # 实时订阅模式
"""
__version__ = "1.0.0"
