"""字面だけのテストを探す道具そのものの検査（RX-0011）。

## ⚠⚠ なぜ道具に検査が要るか

★この計画では**検出器が壊れる**事故が繰り返し起きた:

    ・ログ検出器が**自分を3回数えた**
    ・ログ検出器が**docstring の例**を数えた
    ・25 件の誤検知（★鳴りすぎも壊れ方）

⚠ 今回も最初は **527 件**出た。★大半が誤検知だった:

```python
assert "使えません" in d.dispatch("toggle_auto").message   # ★戻り値の検査
assert "A" not in made.keys["toggle_auto"]                 # ★一覧の検査
assert order.index("action") < order.index("focus")        # ★順序の検査
```

★**ファイルから読んだ文字列**への照合だけが「字面」。直して 90 件になった。

⚠ 「鳴らない」だけでなく「**鳴りすぎない**」ことも見る。
"""

from __future__ import annotations

import pathlib
import sys
import textwrap

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_string_tests import scan, scan_file  # noqa: E402


def _scan_source(tmp_path, body: str) -> list[dict]:
    path = tmp_path / "test_sample.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return scan_file(path)


# --- ⚠ 鳴るべきもの -----------------------------------------------------

def test_ファイルの字面だけなら鳴る(tmp_path):
    got = _scan_source(tmp_path, '''
        import pathlib
        SRC = pathlib.Path("x.lua").read_text(encoding="utf-8")

        def test_wiring():
            assert "function Bridge:_claim_defend(m)" in SRC
    ''')
    assert len(got) == 1, got
    assert got[0]["only_text"] is True


def test_関数の中で読んでも鳴る(tmp_path):
    got = _scan_source(tmp_path, '''
        import pathlib

        def test_wiring():
            text = pathlib.Path("x.lua").read_bytes().decode("utf-8")
            assert "ぼうぎょ" in text
    ''')
    assert len(got) == 1 and got[0]["only_text"] is True, got


def test_countの照合も鳴る(tmp_path):
    got = _scan_source(tmp_path, '''
        import pathlib
        SRC = pathlib.Path("x.py").read_text()

        def test_count():
            assert SRC.count("def ") == 3
    ''')
    assert len(got) == 1, got


def test_挙動も見ていれば印は付くが字面だけではない(tmp_path):
    got = _scan_source(tmp_path, '''
        import pathlib
        SRC = pathlib.Path("x.py").read_text()

        def test_both():
            assert "def go" in SRC
            assert go() == 3
    ''')
    assert len(got) == 1, got
    assert got[0]["only_text"] is False


# --- ⚠⚠ 鳴ってはいけないもの（★ここが 527 件の正体）--------------------

def test_戻り値の文字列では鳴らない(tmp_path):
    """★`d.dispatch(...).message` はファイルではない。"""
    got = _scan_source(tmp_path, '''
        def test_message():
            assert "使えません" in d.dispatch("toggle_auto").message
    ''')
    assert got == [], got


def test_一覧の要素検査では鳴らない(tmp_path):
    got = _scan_source(tmp_path, '''
        def test_keys():
            assert "A" not in made.keys["toggle_auto"]
    ''')
    assert got == [], got


def test_順序の検査では鳴らない(tmp_path):
    """⚠ `order.index(...)` を字面の照合と数えていた。"""
    got = _scan_source(tmp_path, '''
        def test_order():
            assert order.index("action") < order.index("focus")
    ''')
    assert got == [], got


def test_辞書の鍵では鳴らない(tmp_path):
    got = _scan_source(tmp_path, '''
        def test_dict():
            assert "hp" in snapshot()
    ''')
    assert got == [], got


def test_startswithでは鳴らない(tmp_path):
    """⚠ 以前はこれも数えていた。★ファイルとは限らない。"""
    got = _scan_source(tmp_path, '''
        def test_prefix():
            assert line.startswith("2026-")
    ''')
    assert got == [], got


def test_解析済みの辞書では鳴らない(tmp_path):
    """★★★ ⚠⚠ **読んだあと解析したものは字面ではない**（2026-08-18）★★★

    ```python
    got = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "four_pane" not in got        # ★辞書の鍵の検査
    ```

    ⚠ これを字面と数えて誤検知した（★鳴りすぎも壊れ方 / 5回目）。
    """
    got = _scan_source(tmp_path, '''
        import pathlib
        import yaml

        def test_keys():
            data = yaml.safe_load(pathlib.Path("x.yaml").read_text())
            assert "four_pane" not in data
    ''')
    assert got == [], got


def test_解析していなければ鳴る(tmp_path):
    """⚠ 上の逃がし方が広すぎないこと（★読んだままなら字面）。"""
    got = _scan_source(tmp_path, '''
        import pathlib

        def test_text():
            body = pathlib.Path("x.yaml").read_text()
            assert "four_pane" not in body
    ''')
    assert len(got) == 1 and got[0]["only_text"] is True, got


# --- ★ 実データで極端に増減していないこと -------------------------------

def test_実データでの件数がおかしくない():
    """⚠⚠ **「0 件」と「鳴りすぎ」の両方を見る**。

    ★2026-08-15 の実測: 字面を見ている 131 件 / うち字面だけ 90 件。
    ⚠ 直す前の壊れた版は **527 件**鳴っていた。
    """
    found = scan()
    only = [f for f in found if f["only_text"]]
    assert found, "★1件も鳴らない（⚠ 検出器が死んでいる）"
    # ⚠ 上限は「壊れた版（527）の半分」。★これを超えたら誤検知を疑う
    assert len(found) < 260, (
        f"★{len(found)} 件は多すぎる（⚠ 誤検知を疑う）")
    assert 20 <= len(only) <= 200, f"★字面だけ {len(only)} 件"


def test_道具は自分を数えない():
    """⚠ この計画で3回起きた事故。★`scripts/` は対象外。"""
    found = scan()
    assert not [f for f in found if f["file"].startswith("scripts/")], found
