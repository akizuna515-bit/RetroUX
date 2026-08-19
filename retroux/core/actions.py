"""★**引っ越し済み**（2026-08-01 のリファクタ指示書 §23）。

    retroux/core/actions.py  →  retroux/application/

⚠ アクション層は「アプリケーション層」に属します（指示書 §2.3）。
  `core` は Repository・ファイル入出力・エミュレータ接続の層なので、
  そこに入口の調停役が居ると**依存の向きが逆**になります。

★ここは**古い import を壊さないため**だけに残しています。
  新しく書くコードは `retroux.application` を使ってください。
"""

from __future__ import annotations

from ..application.action_dispatcher import ActionDispatcher  # noqa: F401
from ..application.models import (ACTION_BY_NAME, ACTIONS,  # noqa: F401
                                  CONTEXTS, ActionDefinition, ActionResult,
                                  action_names)

__all__ = ["ACTIONS", "ACTION_BY_NAME", "CONTEXTS", "ActionDefinition",
           "ActionDispatcher", "ActionResult", "action_names"]
