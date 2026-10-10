"""DQ2 の製品の版（RX-0160 / D-47「DQ2 と DQ3 で版を分ける」）。

```text
正本   pyproject.toml の [tool.retroux] dq2-version     ★開発 repo
受け皿 build-info.json（product が retroux-dq2 のとき） ★配布 Runtime（pyproject が入らない）
```

⚠ `[project].version`（`retroux/version.py`）は DQ3 の版のまま（★DQ3 も読む部品なので変えない / D-42 J1）。
⚠ データの版（`dq2_data.CURRENT_SCHEMA`）とは別物（★製品の版が上がってもデータの形が同じなら schema は変えない）。
"""

from __future__ import annotations

import pathlib
import re

from .. import version as _shared

PRODUCT = "retroux-dq2"
UNKNOWN = _shared.UNKNOWN
#: ★`[tool.retroux]` の節（★次の節の見出しまで / ⚠ 註の中の `[` で切らない）と、その中の dq2-version
_SECTION = re.compile(r"^\[tool\.retroux\][ \t]*$(.*?)(?=^\[|\Z)", re.M | re.S)
_KEY = re.compile(r'^dq2-version\s*=\s*"([^"]+)"', re.M)


def _from_pyproject() -> str | None:
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        path = parent / "pyproject.toml"
        if path.exists():
            try:
                text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
            except (OSError, UnicodeDecodeError):
                return None
            section = _SECTION.search(text)
            found = _KEY.search(section.group(1)) if section else None
            return found.group(1) if found else None
    return None


def _from_build_info() -> str | None:
    info = _shared.build_info()
    if info.get("product") != PRODUCT:
        return None                 # ⚠ DQ3 の build-info の版を DQ2 の版として出さない
    got = info.get("version")
    return str(got) if got else None


def get_version() -> str:
    return _from_pyproject() or _from_build_info() or UNKNOWN


def title(prefix: str = "RetroUX DQ2") -> str:
    return f"{prefix} {get_version()}"


def build() -> str:
    """★断面（commit の頭 7 桁 / ⚠ 分からなければ `dev`）。★共通の `build_id` をそのまま使う（RX-0172 / BP-05）。"""
    return _shared.build_id()


def stamp(prefix: str = "RetroUX DQ2") -> str:
    """★版と断面を 1 行で（例 `RetroUX DQ2 1.2.0 / build 3660965`）。⚠ DQ3 は `retroux.version.stamp`。"""
    return f"{title(prefix)} / build {build()}"


VERSION = get_version()
