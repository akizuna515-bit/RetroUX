"""旧名 `retroux.manten` の入口（2026-08-02）。

★★ **中身はありません。`retroux.mantan` へ渡すだけです。** ★★

## なぜ残すのか

「まんたん」のローマ字を `manten` から `mantan` へ直しました（依頼者の決定）。
⚠ ただし指示書 §14 は **`python -m retroux.manten` の維持**を受入条件に
挙げています。手が覚えている打ち方を、名前の都合で壊しません。

## 使い方（どちらも同じように動きます）

    python -m retroux.mantan          # ★これから
    python -m retroux.manten          # 旧名。動きます

⚠ 新しく書くコードでは `retroux.mantan` を使ってください。
"""

from __future__ import annotations

import sys
import warnings

from .mantan import *          # noqa: F401,F403  ★旧名で import しても使える
from .mantan import main

__all__ = ["main"]


def _warn() -> None:
    """★消さずに、気づけるようにする。"""
    warnings.warn(
        "retroux.manten は旧い名前です。retroux.mantan を使ってください"
        "（当面は動きます）",
        DeprecationWarning, stacklevel=2)


if __name__ == "__main__":                             # pragma: no cover
    _warn()
    sys.exit(main())
