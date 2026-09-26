"""書き先の 1 か所（RX3-0128 / 2026-09-08）— ★`work/` の下に書くものは、全部ここを通す。

```text
読む場所（ROM・生成物・input）      いつも repo の下           ★変わらない
書く場所（プレイデータ・記録・IPC） RETROUX_WRITE_ROOT があればそこ
```

## ⚠⚠ なぜ要るか

★実機テストが**人が遊んでいる本物**を書き換えていました（2026-09-08 実測）。

```text
tools/fceux/fcs/DQ3_J.fc*     ⚠ テストのセーブで上書き（★実際に fc5 を潰した）
work/dq3-knowledge/           ⚠ location-book の visit_order が巻き戻る
work/dq3-ui-settings.json     ⚠ 人が選んだ作戦・役割がテストの値になる
```

★Lua 側は前から `RETROUX_WRITE_ROOT` を見ています（`dev.lua`）。
⚠ Python 側だけが repo 直下に書いていたので、ここで**同じ環境変数**に合わせます。

## ★使い方

```python
from dq3 import paths
KNOWLEDGE = paths.lazy_work("dq3-knowledge")   # ★module の定数は**これ**を使う
got = paths.work("dq3-knowledge")              # ⚠ その場で使い切るならこちら
```

> ⚠⚠ **2026-09-21 訂正（RX3-0342）**: ここには「環境変数は **import より前**に立ててください」
> と書いてありましたが、★**守られませんでした**。⚠ `scripts/*_run.py` は `dq3.*` を
> module の頭で import し、`open_sandbox()` を `main()` で呼ぶので、⚠⚠ **順番が逆**です。
> → ★実際に**依頼者の `work/dq3-knowledge/` が書き換わりました**。
>
> ★いまは `lazy_work()` が**使うたびに**引き直すので、⚠ 順番に依存しません。
> ⚠ 「約束を守る」ではなく「★守らなくても壊れない」形にしました。
"""
from __future__ import annotations

import os
import pathlib

#: ★repo の場所（⚠ ここは読む専用。書き先ではない）
ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★書き先を差し替える環境変数（⚠ Lua と**同じ名前**にする）
ENV = "RETROUX_WRITE_ROOT"

#: ★隔離して動いている印（⚠ セーブスロットの扱いが変わる / `ai_state.lua`）
SANDBOX_ENV = "RETROUX_SANDBOX"


def write_root() -> pathlib.Path:
    """★いまの書き先の親。⚠ 立っていなければ repo。"""
    got = os.environ.get(ENV)
    return pathlib.Path(got) if got else ROOT


def work(*parts) -> pathlib.Path:
    """★`<書き先>/work/...`。"""
    return write_root().joinpath("work", *parts)


class LazyPath(os.PathLike):
    """★**使うたびに**書き先を引き直す置き場（RX3-0342 / 2026-09-21）。

    ## ⚠⚠ なぜ要るか

    ★`DEFAULT_PATH = paths.work(...)` は **import のときに**決まります。
    ⚠ 隔離の環境変数は `open_sandbox()` が立てるので **import より後**です。

    ```text
    ⚠ 以前  runner が dq3.* を import → 定数が本番で固まる → open_sandbox → ⚠⚠ 本番へ書く
    ★いま  定数は「道の作り方」を覚えるだけ → 使う瞬間に RETROUX_WRITE_ROOT を引く
    ```

    ★2026-09-21 に、これで**依頼者の `work/dq3-knowledge/` が書き換わりました**。
    ⚠ pytest は `conftest.py` が先に立てるので無事でしたが、
    ⚠⚠ **`scripts/*_run.py` の単体起動がすり抜けていました**。

    ## ★使い方

    ```python
    DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "chests.json")   # ★呼ぶ側は変えない
    DEFAULT_PATH.read_text(...)      # ⚠ ここで引き直す
    pathlib.Path(DEFAULT_PATH)       # ★os.fspath 経由で今の道になる
    ```

    ⚠ `pathlib.Path` の属性・メソッドはそのまま使えます（★`__getattr__` が本物へ渡す）。
    ⚠⚠ ただし **`isinstance(x, pathlib.Path)` は False** です（★必要なら `pathlib.Path(x)`）。
    """

    __slots__ = ("_parts",)

    def __init__(self, *parts) -> None:
        self._parts = parts

    def _now(self) -> pathlib.Path:
        return work(*self._parts)

    # --- ★os / open / shutil から使えるように ---
    def __fspath__(self) -> str:
        return str(self._now())

    # --- ★pathlib の顔をそのまま見せる ---
    def __getattr__(self, name):
        return getattr(self._now(), name)

    def __truediv__(self, other):
        return self._now() / other

    def __rtruediv__(self, other):
        return other / self._now()

    def __eq__(self, other) -> bool:
        if isinstance(other, LazyPath):
            return self._now() == other._now()
        if isinstance(other, (pathlib.Path, str)):
            return self._now() == pathlib.Path(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._now())

    def __str__(self) -> str:
        return str(self._now())

    def __repr__(self) -> str:
        return "LazyPath(%s)" % str(self._now())


def lazy_work(*parts) -> LazyPath:
    """★`work(...)` と同じ道を、⚠ **使うたびに**引き直す形で返す。"""
    return LazyPath(*parts)


def repo(*parts) -> pathlib.Path:
    """★repo の中（⚠ ROM・生成物・input など**読むもの**）。"""
    return ROOT.joinpath(*parts)


def as_repo(path) -> pathlib.Path:
    """★逃がした書き先を、**repo 側の同じ場所**に読み替える（RX-0141 / 2026-09-18）。

    ⚠⚠ 検査中は `RETROUX_WRITE_ROOT` が一時フォルダを指します（`conftest.py`）。
      ★そのとき「この置き場は Git の外か」を見たい検査は、⚠ 一時フォルダを見ても意味が無く、
      **repo 側の同じ道**を見る必要があります。

    ```text
    <一時>/work/dq3-knowledge/topic-state.json  →  <repo>/work/dq3-knowledge/topic-state.json
    <repo>/work/rom/DQ3_J.nes                   →  そのまま（★書き先の下でなければ触らない）
    ```
    """
    got = pathlib.Path(path).resolve()
    base = (write_root() / "work").resolve()
    if base == got:
        return ROOT / "work"
    if base in got.parents:
        return ROOT.joinpath("work", got.relative_to(base))
    return got


def in_sandbox() -> bool:
    """★隔離された場所で動いているか。"""
    return os.environ.get(SANDBOX_ENV) == "1" or write_root() != ROOT


__all__ = ["ROOT", "ENV", "SANDBOX_ENV", "LazyPath", "write_root", "work", "lazy_work",
           "repo", "as_repo", "in_sandbox"]
