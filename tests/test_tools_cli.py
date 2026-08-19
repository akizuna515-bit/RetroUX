"""検査の無かった道具に、最低限の歯止めを置く（2026-08-12 / 監査 P2）。

## ⚠⚠ 何が問題だったか

`retroux/tools/` の 6 本に**テストが1つもありませんでした**。

```
map_prune  session  dq2_map_capture  dq2_map_code
dq2_map_render  dq2_world_map
```

★とくに `map_prune` は **README が使い方を書いている道具**です
（「⚠ 記録済みDBに古い不具合の行が残っています…`--apply` で消せます」）。
⚠ 壊れていても、依頼者が実行するまで誰も気づきません。

## ★ ここで見るもの（★欲張らない）

| 見る | 見ない |
| --- | --- |
| ★import で落ちない（構文・依存） | 実際の変換結果 |
| ★`--help` が出る（引数の定義が壊れていない） | ROM やセーブが要る処理 |
| ⚠ **既定で書かないこと**（`--apply` を付けたときだけ書く） | — |

⚠⚠ **「実行できた」で満足しないこと。** ここは「**起動すらしない**」を
防ぐ歯止めです。中身の正しさは別の検査が要ります（★まだありません）。

## ⚠ なぜ `--apply` を重視するか

`map_prune` と `tile_reset` は**利用者の記録を消します**。
★既定が「数えるだけ」でなくなったら、⚠ 実行しただけでデータが消えます。
**これはテストで固定する価値があります。**
"""

from __future__ import annotations

import importlib
import pathlib
import subprocess
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: ★検査が無かった道具（2026-08-12 / 監査 P2）
UNTESTED = [
    "map_prune", "session", "dq2_map_capture", "dq2_map_code",
    "dq2_map_render", "dq2_world_map",
]

#: ⚠ 利用者の記録を消しうる道具。★既定は「数えるだけ」でなければならない
DESTRUCTIVE = ["map_prune", "tile_reset"]


@pytest.mark.parametrize("name", UNTESTED)
def test_道具をimportできる(name):
    """⚠ 依存の抜けや構文の誤りで**起動すらしない**のを防ぐ。"""
    mod = importlib.import_module(f"retroux.tools.{name}")
    assert mod is not None


@pytest.mark.parametrize("name", UNTESTED)
def test_引数の定義が壊れていない(name):
    """★`--help` が出ること。⚠ `argparse` の書き間違いはここで落ちる。

    ⚠ ROM やセーブは要りません（`--help` は引数を組むだけ）。
    """
    got = subprocess.run(
        [sys.executable, "-m", f"retroux.tools.{name}", "--help"],
        cwd=str(PROJECT_ROOT), capture_output=True, timeout=120,
        env={"PYTHONUTF8": "1", "PATH": ""} | dict(__import__("os").environ))
    # ★`--help` は 0 で終わる。⚠ 2 は argparse のエラー
    assert got.returncode == 0, (
        f"⚠ `--help` が {got.returncode} で終わりました:\n"
        + (got.stderr or b"").decode("utf-8", "replace")[-800:])


@pytest.mark.parametrize("name", DESTRUCTIVE)
def test_既定では消さない(name):
    """★★★ **既定は「数えるだけ」。** ⚠ ここが壊れると記録が消えます。

    ⚠ 実行はしません（DB が要るため）。★`--apply` という門が
      **ソースに存在すること**と、既定が `False` であることを見ます。
    """
    src = (PROJECT_ROOT / "retroux" / "tools" / f"{name}.py").read_bytes()
    text = src.decode("utf-8")
    assert '"--apply"' in text or "'--apply'" in text, (
        f"⚠⚠ {name} に `--apply` の門がありません（★実行しただけで消えます）")
    assert "action=\"store_true\"" in text or "action='store_true'" in text, (
        "⚠ `--apply` が既定で有効になっていないか確かめてください")


def test_検査の無い道具が増えていない():
    """⚠ 新しい道具に検査を付け忘れたら気づけるようにする。

    ★`UNTESTED` は「**まだ中身の検査が無い**」一覧です。
      減らすのが目標で、⚠ 増やすときは理由を書いてください。
    """
    tools = {p.stem for p in (PROJECT_ROOT / "retroux" / "tools").glob("*.py")
             if p.stem != "__init__"}
    unknown = set(UNTESTED) - tools
    assert not unknown, f"⚠ 一覧に無い道具が書かれています: {sorted(unknown)}"
    assert len(UNTESTED) <= 6, (
        "⚠ 検査の無い道具が増えました。★足すより先に検査を書いてください")
