"""兼容包：历史路径 `libs.*`。

背景：仓库曾用顶层软链接 `libs -> assets` 维持兼容；现在移除软链接后，
通过把 `assets/` 加入 `libs` 的模块搜索路径，让 `import libs.common`、`import libs.database` 继续可用。

注意：这只解决 Python import 兼容，不解决把 `libs/` 当文件路径使用的场景（那类路径应改用 `assets/`）。
"""

from __future__ import annotations

from pathlib import Path

# 让 `libs` 成为可扩展包，并把 `assets/` 作为一个搜索根追加进去。
# 这样 `assets/common` 会以 `libs.common` 的形式被 import。

_assets_dir = (Path(__file__).resolve().parent.parent / "assets").resolve()
if _assets_dir.is_dir():
    __path__.append(str(_assets_dir))  # type: ignore[name-defined]
