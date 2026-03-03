"""稳定数据契约（Contract）模块。

此目录用于存放跨服务共享的“稳定接口契约”定义：
- api-service 作为对外/对内统一 Data API（Query Service），只暴露稳定契约字段
- telegram/sheets/vis 等消费侧只依赖契约，不直接耦合底层表名/列名/实现细节
"""

from .cards_contract import (  # noqa: F401
    ALL_CARD_CONTRACTS,
    CARD_ID_TO_CONTRACT,
    resolve_card_id,
)

