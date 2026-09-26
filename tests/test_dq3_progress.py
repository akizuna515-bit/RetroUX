"""起きたこと → Fact（RX3-0076 / progress.py）。

```text
所持品 $076C   bit7 を落とす / FF は空き / 一度持ったら消えない / 居ない枠は読まない
撃破・到達     EnemyBook.defeated / visited_locations
fact_id       安定（同じ出来事は同じ id → Topic State が二度数えない）
```
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3.knowledge import progress as PG

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_所持品はbit7を落として覚える(tmp_path):
    p = PG.Progress(path=tmp_path / "p.json")
    added = p.note_party([{"items": [0x80 | 88, 87, 0xFF, 0xFF]}, {"items": [0xFF] * 8}])
    assert added == 2 and p.items_ever == {88, 87}


def test_使って無くなっても手に入れたは消えない(tmp_path):
    p = PG.Progress(path=tmp_path / "p.json")
    p.note_party([{"items": [87]}])
    p.note_party([{"items": [0xFF]}])          # ★まほうのたま を使った
    assert 87 in p.items_ever
    assert any(f["subject"] == "item:87" and f["predicate"] == "obtain" for f in p.facts())


def test_fact_idは安定している(tmp_path):
    a = PG.Progress(path=tmp_path / "a.json")
    a.note_party([{"items": [88]}])
    b = PG.Progress(path=tmp_path / "b.json")
    b.note_party([{"items": [0x80 | 88]}])      # ★装備中でも同じ品
    assert [f["fact_id"] for f in a.facts()] == [f["fact_id"] for f in b.facts()]


def test_撃破と到達もFactになる(tmp_path):
    p = PG.Progress(path=tmp_path / "p.json")
    p.note_defeated([101, "132"])
    p.note_visited(["L9", "L0", ""])
    subjects = {(f["subject"], f["predicate"]) for f in p.facts()}
    assert ("monster:101", "defeat") in subjects and ("monster:132", "defeat") in subjects
    assert ("location:L9", "visit") in subjects and ("location:L0", "visit") in subjects
    assert all(f["confidence"] == 1.0 for f in p.facts())


def test_保存して読み直せる(tmp_path):
    p = PG.Progress(path=tmp_path / "p.json")
    p.note_party([{"items": [88]}])
    p.note_defeated([5])
    p.note_visited(["L9"])
    assert p.save()
    again = PG.Progress.load(tmp_path / "p.json")
    assert again.items_ever == {88} and again.defeated == {5} and again.visited == {"L9"}
    assert not p.save(), "⚠ 変わっていないのに書いた"


def test_壊れた値で落ちない(tmp_path):
    p = PG.Progress(path=tmp_path / "p.json")
    assert p.note_party([{"items": ["x", None, -1]}, "junk", {"items": None}]) == 0
    assert p.note_defeated(["?"]) == 0


def test_gatherはvmから取る(tmp_path):
    class _Book:
        defeated = {7}

    class _VM:
        enemy_names = _Book()
        _visited = {"L3"}

        def _raw(self):
            return {"party": [{"items": [0x80 | 3, 0xFF]}]}

    p = PG.gather(_VM(), PG.Progress(path=tmp_path / "p.json"))
    assert p.items_ever == {3} and p.defeated == {7} and p.visited == {"L3"}


def test_gatherはファイルからも取れる(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"party": [{"items": [12]}]}), encoding="utf-8")
    p = PG.gather(None, PG.Progress(path=tmp_path / "p.json"), state=PG.load_state(state),
                  visited={"L1"})
    assert p.items_ever == {12} and p.visited == {"L1"}


def test_管理画面の初期化に入っている():
    from dq3.knowledge import playdata as PD

    files = {name for _k, _l, names in PD.ITEMS for name in names}
    assert PG.DEFAULT_PATH.name in files


# --- ★本物の並び（⚠ セーブステートで確かめる）--------------------------------------

def _states():
    d = ROOT / "tools" / "fceux" / "fcs"
    return sorted(d.glob("DQ3_J.fc[0-8]")) if d.exists() else []


@pytest.mark.skipif(not _states(), reason="DQ3 のセーブステートが無い")
def test_セーブステートの所持品はROMの品名に解ける():
    """★$076C / 1 人 8 枠 / bit7 装備 / FF 空き（2026-09-05 に 18 本で確認）。"""
    from dq3.knowledge import rom_names
    from retroux.tools.ram import read_savestate

    rom_names.reset()
    if rom_names._load() is None:
        pytest.skip("⚠ 名前辞書が使えない環境")
    checked = 0
    for path in _states():
        try:
            ram = read_savestate(path)
        except Exception:                                  # noqa: BLE001
            continue
        hp_max = [ram[0x0724 + 2 * i] | (ram[0x0725 + 2 * i] << 8) for i in range(4)]
        rows = [{"items": list(ram[0x076C + 8 * i:0x076C + 8 * (i + 1)])}
                for i in range(4) if hp_max[i] > 0]
        p = PG.Progress()
        p.note_party(rows)
        assert p.items_ever, path.name
        assert all(rom_names.item(i) for i in p.items_ever), (path.name, sorted(p.items_ever))
        checked += 1
    assert checked >= 3


# ======================================================================
# ★遊んでいる間ずっと数える（RX3-0298 / 2026-09-19）
# ======================================================================
#
# ⚠⚠ 依頼者「6つのオーブを入手し、ラーミアを復活させたが、勇者メモがかわらない」。
#   ★`note_party` を呼ぶ道は `Council._progress` の**1 本だけ**だった。
#   ⚠ そのため「取ってすぐ捧げた」オーブは 1 度も記録に残らず、
#     ★依頼者の記録では 6 個のうち **3 個が `items_ever` に無かった**。

def test_画面を開かなくても数える(tmp_path):
    w = PG.Watcher(path=tmp_path / "progress.json")
    got = w.note({"party": [{"items": [119, 120, 0xFF]}]})
    assert got == 2 and w.progress.items_ever == {119, 120}


def test_増えないときは書かない(tmp_path):
    """⚠ 毎回書くと、★遊んでいる間ずっとディスクを叩く。"""
    w = PG.Watcher(path=tmp_path / "progress.json")
    w.note({"party": [{"items": [119]}]})
    assert w.saves == 1
    for _ in range(5):
        w.note({"party": [{"items": [119]}]})
    assert w.saves == 1, "⚠⚠ 同じ中身で書き直している"


def test_旗も数える(tmp_path):
    """★オーブを捧げた印も、勇者会議を開かずに拾う（RX3-0297）。"""
    w = PG.Watcher(path=tmp_path / "progress.json")
    w.note({"story_60cf": 0x3F})
    assert len(w.progress.story) == 6


def test_届いていなければ何もしない(tmp_path):
    w = PG.Watcher(path=tmp_path / "progress.json")
    assert w.note(None) == 0 and w.note({}) == 0 and w.saves == 0


def test_品が消えても記録は残る(tmp_path):
    """★これが `items_ever`（⚠ 捧げると持ち物からは消える）。"""
    w = PG.Watcher(path=tmp_path / "progress.json")
    w.note({"party": [{"items": [119]}]})
    w.note({"party": [{"items": [0xFF]}]})
    assert 119 in w.progress.items_ever


def test_2人が別々に書いても消し合わない(tmp_path):
    """⚠⚠ 勇者会議と画面の更新は**別の Progress** を持つ。

    ★自分の集合だけを書くと、⚠ 相手が足したぶんが消える。
    """
    path = tmp_path / "progress.json"
    a = PG.Progress(path=path)
    b = PG.Progress(path=path)
    a.note_party([{"items": [119]}])
    a.save()
    b.note_party([{"items": [120]}])
    b.save()
    got = PG.Progress.load(path)
    assert got.items_ever == {119, 120}, "⚠⚠ 片方の記録が消えた: %s" % sorted(got.items_ever)


def test_ほかの欄も消し合わない(tmp_path):
    path = tmp_path / "progress.json"
    a = PG.Progress(path=path)
    a.note_visited(["L1"])
    a.note_defeated([5])
    a.note_story({"story_60cf": 0b000001})
    a.save()
    b = PG.Progress(path=path)
    b.note_visited(["L2"])
    b.note_defeated([6])
    b.note_story({"story_60cf": 0b000010})
    b.save()
    got = PG.Progress.load(path)
    assert got.visited == {"L1", "L2"} and got.defeated == {5, 6}
    assert len(got.story) == 2, sorted(got.story)


def test_画面が数える人を呼んでいる():
    """⚠⚠ **作っただけで呼び忘れる**を防ぐ（★この計画で何度も踏んだ形）。"""
    import pathlib as _p

    root = _p.Path(__file__).resolve().parents[1]
    body = (root / "dq3" / "ui" / "main_window.py").read_text(encoding="utf-8")
    code = chr(10).join(ln for ln in body.splitlines()
                        if not ln.lstrip().startswith("#"))
    assert "def _progress_watch" in code
    assert "self._progress_watch().note(raw)" in code, (
        "⚠⚠ 画面の更新から数えていない（★勇者会議を開いたときだけに戻っている）")


def test_数える人は1回だけ作る():
    """⚠ 窓を更新するたびに `progress.json` を読まない。"""
    from PySide6.QtWidgets import QApplication

    from dq3.ui import main_window as MW

    QApplication.instance() or QApplication([])
    win = MW.Dq3MainWindow.__new__(MW.Dq3MainWindow)
    first = win._progress_watch()
    assert isinstance(first, PG.Watcher)
    assert win._progress_watch() is first, "⚠ 毎回作り直している"
