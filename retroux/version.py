"""RetroUX のバージョン（2026-07-30 / リリース調整 仕様書 14章）。

★★ **一元管理する。** ★★
  タイトル・About・診断情報・ログの起動行が別々に持つと、
  問い合わせを受けたときに**どれが本当か分からなくなる**。

★出どころは `pyproject.toml` の1か所。
  ⚠ ここに数字を書き写さない（写すと必ずずれる）。
    パッケージとして入っていない環境（リポジトリを直接動かす）でも
    読めるように、`pyproject.toml` を直接読む道も用意してある。
"""

from __future__ import annotations

import pathlib
import re

#: 読めなかったときに出す文字列。★**数字を偽らない**
UNKNOWN = "0.0.0+unknown"

_PATTERN = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _from_metadata() -> str | None:
    """インストール済みパッケージから読む（普通はこちら）。"""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("retroux")
    except Exception:                                  # noqa: BLE001
        # PackageNotFoundError 以外（importlib が無い等）もまとめて拾う
        return None


def _from_pyproject() -> str | None:
    """`pyproject.toml` から読む（リポジトリを直接動かしているとき）。

    ⚠ `tomllib` を使わず正規表現で読む理由: `[tool.*]` の中にも
      `version = "..."` が現れうるので、**先頭の1件**だけを採りたい。
      `[project]` を厳密に解釈するほどの利得が無い。
    """
    here = pathlib.Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        path = parent / "pyproject.toml"
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        found = _PATTERN.search(text)
        return found.group(1) if found else None
    return None


def get_version() -> str:
    """バージョン文字列。読めなければ `UNKNOWN`。"""
    return _from_metadata() or _from_pyproject() or UNKNOWN


#: 画面に出す形（例 `RetroUX 0.1.0`）
def title(prefix: str = "RetroUX") -> str:
    return f"{prefix} {get_version()}"


VERSION = get_version()
