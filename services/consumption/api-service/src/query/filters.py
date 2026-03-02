from __future__ import annotations

from typing import Any


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def drop_placeholder_rows(
    rows: list[dict[str, Any]],
    *,
    key_cols: tuple[str, ...],
) -> list[dict[str, Any]]:
    """删除“占位/全空行”。

    规则：
    - key_cols 任一缺失/空 → 丢弃
    - 除 key_cols 外，其余字段全部为空 → 丢弃
    """
    out: list[dict[str, Any]] = []
    for r in rows:
        if any(_is_empty(r.get(k)) for k in key_cols):
            continue
        non_null = 0
        for k, v in r.items():
            if k in key_cols:
                continue
            if _is_empty(v):
                continue
            non_null += 1
            break
        if non_null == 0:
            continue
        out.append(r)
    return out

