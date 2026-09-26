"""撮影で撮る窓の当てが古くなっていないか（RX3-0424 / 2026-09-24）。

## ⚠⚠ なぜ要るか（★実際に踏んだ）

```text
2026-09-24 の C01 / C03 は **FCEUX だけ**が映っていました。
  `⚠ 全景: 1 / 4 枚だけ見つかりました`
★題名が変わっていたのに、当て（`WIN_PANEL` 等）が古いままだったためです。
  「RetroUX DQ3（開発中）」→ いま「RetroUX DQ3」
  「見た地図」            → いま「地図、勇者メモ」
  「ログ — RetroUX DQ3」  → いま「ログ」
⚠⚠ `Stage.full()` は**見つからない枠を空けるだけで止めない**ので、
   ★3 枚とも真っ黒のまま最後まで撮れてしまいました（★「動いた」は根拠にならない）。
```

⚠ この検査は **窓を作りません**（★Qt を立てずに、`setWindowTitle` の文字列と突き合わせる）。
"""
from __future__ import annotations

import importlib
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: ★当ての名前 → その題名を書いている file（⚠ 1 つの file に複数あるときは先頭）
OWNER = {
    "WIN_PANEL": "dq3/ui/main_window.py",
    "WIN_MAP": "dq3/ui/map_window.py",
    "WIN_LOG": "dq3/ui/battle_window.py",
    "WIN_BOOK": "dq3/ui/monster_book_window.py",
    "WIN_MEMO": "dq3/ui/memo_detail.py",
    "WIN_COUNCIL": "dq3/ui/council_window.py",
    "WIN_ADMIN": "dq3/ui/admin_window.py",
    "WIN_BROWSER": "dq3/ui/map_browser.py",
}

_TITLE = re.compile(r'setWindowTitle\(\s*"([^"]+)"\s*\)')


def _capture():
    try:
        return importlib.import_module("scripts.dq3_capture_shorts")
    except Exception as exc:                                 # noqa: BLE001
        pytest.skip("⚠ dq3_capture_shorts を読めません: %s" % exc)


def _titles(rel: str) -> list[str]:
    text = (ROOT / rel).read_text(encoding="utf-8")
    return _TITLE.findall(text)


def _all_titles() -> list[str]:
    got: list[str] = []
    for path in sorted((ROOT / "dq3" / "ui").glob("*.py")):
        got += _TITLE.findall(path.read_text(encoding="utf-8"))
    return got


# --- ★★ 当てが本物の題名と一致していること ---------------------------------

@pytest.mark.parametrize("name,rel", sorted(OWNER.items()))
def test_撮る窓の当てが本物の題名と一致する(name: str, rel: str):
    """⚠⚠ 題名を変えたら、★ここが赤くなって気づけること。"""
    mod = _capture()
    needles = getattr(mod, name, None)
    assert needles, "⚠ %s がありません" % name
    exact = [n[1:] for n in needles if n.startswith("=")]
    assert exact, ("⚠⚠ %s は題名そのもの（`=` 付き）で書いてください。"
                   "★部分一致だと別の窓を拾います" % name)
    titles = _titles(rel)
    assert titles, "⚠ %s に setWindowTitle がありません" % rel
    for want in exact:
        assert want in titles, (
            "⚠⚠ %s の当て「%s」は %s の題名にありません（★題名が変わった）。"
            "\n   ★いまの題名: %s" % (name, want, rel, titles))


def test_当てが別の窓と重ならない():
    """⚠ 「RetroUX DQ3」のような部分一致は、★管理画面や図鑑まで拾います。"""
    mod = _capture()
    titles = _all_titles()
    for name in OWNER:
        for needle in getattr(mod, name):
            if not needle.startswith("="):
                continue
            want = needle[1:]
            hit = [t for t in titles if t == want]
            assert len(hit) == 1, (
                "⚠⚠ 題名「%s」が %d 個あります（★どれが撮れるか決まりません）" % (want, len(hit)))


def test_題名の切り出し():
    """★OBS の一覧は `[python.exe]: 題名` の形（⚠ 2026-09-24 実測）。"""
    mod = _capture()
    assert mod.Stage.title_of("[python.exe]: RetroUX DQ3") == "RetroUX DQ3"
    assert mod.Stage.title_of("[python.exe]: RetroUX DQ3 管理") == "RetroUX DQ3 管理"
    # ⚠ 形が違えばそのまま返す（★落とさない）
    assert mod.Stage.title_of("FCEUX 2.6.6: DQ3_J") == "FCEUX 2.6.6: DQ3_J"


def test_部分一致と題名一致を取り違えない():
    """★`find` の当て方そのものを、⚠ OBS 抜きで確かめる。"""
    mod = _capture()

    class _Fake(mod.Stage):
        def __init__(self, rows):                            # noqa: D107
            self._rows = rows

        def windows(self):
            return self._rows

    rows = [("[python.exe]: RetroUX DQ3 管理", "RetroUX DQ3 管理:Qt:python.exe"),
            ("[python.exe]: 図鑑 — RetroUX DQ3", "図鑑 — RetroUX DQ3:Qt:python.exe"),
            ("[python.exe]: RetroUX DQ3", "RetroUX DQ3:Qt:python.exe")]
    stage = _Fake(rows)
    # ⚠⚠ 一覧では**管理画面が先**。★部分一致だとそちらを拾ってしまう
    assert stage.find("RetroUX DQ3") == "RetroUX DQ3 管理:Qt:python.exe"
    assert stage.find("=RetroUX DQ3") == "RetroUX DQ3:Qt:python.exe"
    assert stage.find("=RetroUX DQ3 管理") == "RetroUX DQ3 管理:Qt:python.exe"
    assert stage.find("=居ない窓") is None
