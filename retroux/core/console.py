"""コンソールが無いときに落ちない出力（2026-07-30 / リリース調整 仕様書 4.1）。

★★ **公開用は `pythonw.exe` で動く。** ★★

  仕様書 4.1:
    > `pythonw.exe` 使用時は標準出力・標準エラーが見えないため、
    > 例外を必ずログへ記録すること。

## ⚠⚠ 「見えない」だけでは済まない

`pythonw.exe` にコンソールが無い状況では、CPython は `sys.stdout` /
`sys.stderr` を **`None` にすることがある**（親からハンドルを継承できたかで
変わる）。その状態で `print(..., file=sys.stderr)` を呼ぶと

    AttributeError: 'NoneType' object has no attribute 'write'

で落ちる。落ちると GUI が起動直後に終了し、
**利用者から見て「何も起きない」**になる（仕様書 5.1 が禁じている状態）。

⚠ この案件では**コンソール完全に無しの再現ができなかった**
  （Git Bash / PowerShell から呼ぶと親のハンドルを継承してしまう）。
  再現できないものを「大丈夫」と決めないため、**依存そのものを無くす**。

## 使い方

    from ..core.console import say

    say("起動に失敗しました: ...")            # 画面にもログにも
    say("...", stream="stdout")

★`say` は**必ずログへ書く**。画面はあれば出す、無ければ出さない。
  「画面に出したから記録しない」をやらない（あとから調べられなくなる）。
"""

from __future__ import annotations

import sys


def short_path(path, root=None) -> str:
    """★ログへ出すパスを、プロジェクト直下からの相対にする（RX-0043 / §26）。

    ## ⚠⚠ なぜ要るか

      ログは GitHub の Issue などへ貼られる前提。⚠ 絶対パスを出すと
      **利用者名が混ざる**（`C:\\Users\\<名前>\\...` に置いた場合）。

      ⚠ この開発環境では `C:\\projects\\` にあるため名前が出ておらず、
        ★**grep だけでは危険が見えない**。
        危険が「出ていない」のは置き場所のおかげであって、直ったからではない。

      実測（2026-08-14 の実機ログ / 16分のセッション）:

          C:\\Projects\\260721_RetroUX\\.venv\\Scripts\\pythonw.exe    ← launcher
          C:\\Projects\\260721_RetroUX\\tools\\fceux\\fcs              ← ここ
          C:\\Projects\\260721_RetroUX\\work\\savestate-backup         ← ここ

      ★Lua 側（`bridge.lua` の `short_path`）は先に直していたが、
      ⚠ **Python と PowerShell を直していなかった**。

    ## ⚠ 外にあるパスはそのまま返す

      ★勝手に切ると「どこの話か」が分からなくなる。
    """
    from pathlib import Path

    if path is None:
        return ""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    try:
        return Path(path).resolve().relative_to(base.resolve()).as_posix()
    except (ValueError, OSError):
        # ⚠ プロジェクトの外。★そのまま出す（★切ると意味が変わる）
        return str(path)


def usable(stream) -> bool:
    """その出力先へ書けるか。**推測せず確かめる**。

    ⚠ `None` かどうかだけでは足りない。閉じられている場合もある。
    """
    if stream is None:
        return False
    try:
        if getattr(stream, "closed", False):
            return False
        # ★`write` を持っているかまで見る（差し替えられている場合がある）
        return callable(getattr(stream, "write", None))
    except Exception:                                  # noqa: BLE001
        return False


def has_console() -> bool:
    """コンソールがありそうか（`pythonw.exe` かどうかの目安）。

    ★判定に使うのは**出力先が生きているか**だけ。
      実行ファイル名（`pythonw.exe`）で判断しない。
      名前で判断すると、`python.exe` を出力先なしで起動した場合に外す。
    """
    return usable(sys.stdout) or usable(sys.stderr)


def write(text: str, stream_name: str = "stderr") -> bool:
    """画面へ書く。書けたら True、書けなければ False（**落ちない**）。"""
    stream = getattr(sys, stream_name, None)
    if not usable(stream):
        return False
    try:
        print(text, file=stream)
        # ★流し切る。pythonw では終了時に落ちて消えることがある
        flush = getattr(stream, "flush", None)
        if callable(flush):
            flush()
        return True
    except Exception:                                  # noqa: BLE001
        # ⚠ 画面に書けないことを理由に本体を止めない
        return False


def say(text: str, stream_name: str = "stderr", *, logger=None,
        level: str = "info") -> None:
    """画面とログの両方へ。★**ログは必ず**、画面はあれば。

    `logger` を渡さなければ `get_logger("console")` を使う。
    """
    if logger is None:
        from .logging_setup import get_logger

        logger = get_logger("console")
    try:
        getattr(logger, level, logger.info)("%s", text)
    except Exception:                                  # noqa: BLE001
        # ⚠ ログにも書けない環境（権限が無い等）でも落ちない
        pass
    write(text, stream_name)
