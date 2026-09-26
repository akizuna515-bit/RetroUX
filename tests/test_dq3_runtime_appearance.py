"""実機の見た目は「枠の番号」を解いて出す（RX3-0304 / 2026-09-20）。

⚠⚠ 依頼者「バラモスを倒した時、王様とイベントセリフを話すが、？になっている」。

## ★何が起きていたか

```text
玉座（map 71 / save8）  current_npcs → status = UNKNOWN（★表がどれとも合わない）
→ ⚠ 相手が分からない → 話者が ？
```

★合わない理由も分かりました。⚠ **6 人の x が `0x80`** で、y は表どおり（6,6,9,9,12,12）。

```text
表 172 と  人数 9 で一致 / ★形（動く・動かない）も一致
⚠ 違い     動かない 6 人の **x だけ** 0x80
```

⚠ いまの決まりは `(0x80, 0x80)` **ちょうど**だけを「消えた人」とみなします（RX3-0230）。
★セーブ 37 本で数えたら、⚠ `x` だけ `0x80` は **この 1 場面（fc0 / fc8）の 12 件だけ**でした。
→ ⚠⚠ **1 場面で決まりを広げません**（★`y` だけ `0x80` は 0 件）。

## ★代わりに: 表が分からなくても**札は出せる**

⚠ 実機の表の 3 バイト目は「見た目」ではなく **枠の番号**で、
★解く表は WRAM `$6ABE` にあります。⚠ それを `state.json` へ送っていませんでした。

```text
slot 4 ( 9, 4) 枠 4 → 見た目 0   → 札「王」   ★これが話しかけた相手
slot 5 (10, 5) 枠 5 → 見た目 4   → 札「臣」
```
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3.knowledge import npc_master as NM

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATES = ROOT / "tools" / "fceux" / "fcs"
LABELS = ROOT / "data" / "dq3" / "npc-appearance-labels.json"


def _save(name: str):
    """★セーブを読む。⚠ 名指しは**最後の手**（★固定した fixture を先に見る / RX-0135）。

    ⚠⚠ 2026-09-20: 依頼者が遊んで `DQ3_J.fc8` が撮り直され、★この検査が赤くなりました
      （⚠ 回帰ではない）。→ ★同じ場面を fixture `throne_unknown_table` に固定しました。
    """
    from retroux.core.bgmap import savestate as ss

    p = _pinned(name) or (STATES / name)
    if not p.exists():
        pytest.skip("⚠ %s がありません" % name)
    ch = ss.load(p).chunks
    return bytes(ch["RAM"]), bytes(ch["WRAM"])


#: ★名指しのスロット → 固定した fixture（⚠ 場面が要るものだけ）
PINNED = {"DQ3_J.fc8": "throne_unknown_table"}


def _pinned(name: str):
    """★固定した写し（⚠ 無ければ `None` = 今までどおり名指しで読む）。"""
    fixture_id = PINNED.get(name)
    if fixture_id is None:
        return None
    from dq3.testing import fixtures as FX

    try:
        got = FX.get(fixture_id)
    except Exception:                                      # noqa: BLE001 ★無いだけ
        return None
    return got.path if got.path.exists() else None


def _hex(ram: bytes, wram: bytes):
    tbl = ram[0x0110:0x0110 + 0x68].hex()
    app = wram[0x6ABE - 0x6000:0x6ABE - 0x6000 + 0x10].hex()
    return tbl, app


# --- ★枠を解く -----------------------------------------------------------

def test_材料が無ければ見た目は出さない():
    """⚠ 推測しない（★送られていなければ None）。"""
    tbl = ("09040 4ae".replace(" ", "") + "ff" * 100)[:0x68 * 2]
    got = NM.runtime_slots(tbl)
    assert got and got[0].get("appearance_id") is None


def test_壊れた材料でも落ちない():
    tbl = ("0904" + "04ae") + "ff" * 100
    assert NM.runtime_slots(tbl[:0x68 * 2], "これは 16 進ではない") is not None


def test_表が無ければ空():
    assert NM.runtime_slots(None, None) == []
    assert NM.runtime_appearance(4, None, None) is None


# --- ★依頼者の save8（玉座）------------------------------------------------

def test_玉座で王様の見た目が出る():
    """★★ これが直したかったこと（⚠ 表が UNKNOWN でも札を出せる）。"""
    ram, wram = _save("DQ3_J.fc8")
    tbl, app = _hex(ram, wram)
    slots = NM.runtime_slots(tbl, app)
    if not slots or slots[0].get("x") != 9 or slots[0].get("y") != 4:
        pytest.skip("⚠ save8 が玉座の場面ではない（★撮り直された）")
    assert slots[0]["appearance_id"] == 0, slots[0]
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    assert labels.get("0") == "王", "⚠ 札の表が変わった"


def test_玉座は表がどれとも合わないまま():
    """⚠ 「表が分かった」わけではない（★そこは未解決のまま残す）。"""
    ram, wram = _save("DQ3_J.fc8")
    tbl, _app = _hex(ram, wram)
    if not NM.runtime_slots(tbl):
        pytest.skip("⚠ 表が読めない")
    slots = NM.runtime_slots(tbl)
    if len(slots) != 9:
        pytest.skip("⚠ save8 が玉座の場面ではない")
    assert NM.runtime_variant_table(71, 1, tbl) is None
    assert NM.ambiguous_variant_table(71, 1, tbl) is None


def test_消えた人の決まりは広げていない():
    """⚠⚠ `x` だけ `0x80` は**1 場面だけ**だった（★決まりを広げない）。"""
    assert NM.HIDDEN_XY == (0x80, 0x80)
    assert not NM.is_hidden({"x": 0x80, "y": 6}), "⚠⚠ 1 場面で決まりを広げている"
    assert NM.is_hidden({"x": 0x80, "y": 0x80})


# --- ★Lua が材料を送っている ---------------------------------------------

def test_devluaが見た目の枠の表を送る():
    """⚠⚠ **作っただけで送り忘れる**を防ぐ（★これが無いと画面では出ない）。"""
    body = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    code = chr(10).join(ln for ln in body.splitlines()
                        if not ln.lstrip().startswith("--"))
    assert "0x6ABE" in code, "⚠ 見た目の枠の表を読んでいない"
    assert "out.npc_appearance" in code, "⚠ state.json へ送っていない"


def test_番地は1か所に書く():
    """⚠ Lua と Python で番地がずれたら、★静かに違うものを読む。"""
    from dq3.testing import npc_rom as NR

    body = (ROOT / "dq3" / "phase0" / "dev.lua").read_text(encoding="utf-8")
    want = "0x%04x" % NR.APPEARANCE_SLOTS           # ⚠ 大文字小文字はどちらでもよい
    assert want in body.lower(), (
        "⚠⚠ Lua の番地が `npc_rom.APPEARANCE_SLOTS`（$%04X）と違う" % NR.APPEARANCE_SLOTS)


# ======================================================================
# ★話者の札まで繋ぐ（RX3-0304 / 2026-09-20）
# ======================================================================
#
# ⚠ 表が分からない以上、★`npc_id` も `talk_id` も**決めません**（推測しない）。
#   ★けれど「**どんな見た目の人か**」は実機の表から分かります。

def _service():
    from dq3.knowledge.town_service import TownService

    return TownService()


def test_表が分からなくても正面の人の札が出る():
    """★★ これが直したかったこと（⚠ 玉座で上を向くと王様）。"""
    ram, wram = _save("DQ3_J.fc8")
    tbl, app = _hex(ram, wram)
    svc = _service()
    if svc.current_npcs(71, ram[0x06DF], tbl)["status"] != "UNKNOWN":
        pytest.skip("⚠ save8 が「表が分からない」場面ではない")
    assert svc.npc_in_front(71, ram[0x06DF], tbl, (9, 5), 0) is None, (
        "⚠ 表から出てしまった（★この検査は何も見ていない）")
    got = svc.appearance_in_front(tbl, app, (9, 5), 0)
    assert got is not None and got["label"] == "王", got
    assert (got["x"], got["y"]) == (9, 4), got


def test_向きが違えば別の人():
    """⚠ いつも同じ人を返していないこと。"""
    ram, wram = _save("DQ3_J.fc8")
    tbl, app = _hex(ram, wram)
    svc = _service()
    up = svc.appearance_in_front(tbl, app, (9, 5), 0)
    right = svc.appearance_in_front(tbl, app, (9, 5), 1)
    if up is None or right is None:
        pytest.skip("⚠ save8 が玉座の場面ではない")
    assert up["label"] != right["label"], (up, right)


def test_誰も居なければ出さない():
    """⚠ 推測で札を付けない。"""
    ram, wram = _save("DQ3_J.fc8")
    tbl, app = _hex(ram, wram)
    assert _service().appearance_in_front(tbl, app, (9, 5), 2) is None


def test_材料が届いていなければ出さない():
    """⚠ 古い Lua（★見た目の表を送らない）でも落ちない・嘘をつかない。"""
    ram, wram = _save("DQ3_J.fc8")
    tbl, _app = _hex(ram, wram)
    assert _service().appearance_in_front(tbl, None, (9, 5), 0) is None


def test_画面が見た目の道を使っている():
    """⚠⚠ **作っただけで呼び忘れる**を防ぐ。"""
    body = (ROOT / "dq3" / "ui" / "view_model.py").read_text(encoding="utf-8")
    code = chr(10).join(ln for ln in body.splitlines()
                        if not ln.lstrip().startswith("#"))
    assert "def npc_appearance_hex" in code
    assert "service.appearance_in_front(" in code, "⚠ 画面から呼んでいない"
    # ⚠ 表から分かるときは、★今までどおり表を使う（順番を逆にしない）
    assert code.index("service.npc_in_front(") < code.index("service.appearance_in_front(")


def test_相手が決まらないときはnpc_idを出さない():
    """⚠⚠ 表が分からないのに `npc_id` を決めると、★別人として記録される。"""
    body = (ROOT / "dq3" / "ui" / "view_model.py").read_text(encoding="utf-8")
    assert 'return got["label"], None, map_id' in body, (
        "⚠ 見た目だけの道で npc_id を付けている")


class _Talker:
    """★`_talker_now` だけを借りた見本（⚠ 実機も本物の記録も要らない）。"""

    from dq3.ui import view_model as _VM

    _talker_now = _VM.Dq3ViewModel._talker_now

    def __init__(self, npc=None, look=None) -> None:               # noqa: D107
        class _Svc:
            def npc_in_front(self, *a, **k):
                return npc

            def appearance_in_front(self, *a, **k):
                return look

            def appearance_label(self, aid):
                return "表"

        self._town_service = _Svc()

    def position(self):
        return (1, 71, 9, 5)

    def facing(self):
        return 0

    def time_byte(self):
        return 1

    def npc_table_hex(self):
        return "00"

    def npc_appearance_hex(self):
        return "00"


def test_画面は表から分かるときに表を使う():
    """⚠⚠ 見た目だけの道を**先に**使うと、★`npc_id` と `talk_id` を落とします。

    ★字面の順番だけでは足りません（⚠ 壊す実験で緑のまま通った）
    → ★両方そろった場面を**画面の関数に通して**、⚠ 表のほうが勝つことを見ます。
    """
    both = _Talker(npc={"npc_id": 7, "appearance_id": 0},
                   look={"label": "見", "appearance_id": 0, "slot": 4})
    assert both._talker_now() == ("表", 7, 71), "⚠⚠ 見た目の道が表より先に使われている"


def test_画面は表が分からないときだけ見た目を使う():
    only_look = _Talker(npc=None, look={"label": "王", "appearance_id": 0, "slot": 4})
    assert only_look._talker_now() == ("王", None, 71)


def test_画面はどちらも無ければ空():
    assert _Talker(npc=None, look=None)._talker_now() == (None, None, None)


def test_表から分かるときは表を使う():
    """⚠⚠ 見た目だけの道を**先に**使うと、★`npc_id` と `talk_id` を落とします。

    ★字面の順番だけでは足りません（⚠ 壊す実験で緑のまま通った）。
    → ★表が分かる場面を通して、**`npc_id` が付く**ことを見ます。
    """
    ram, wram = _save("DQ3_J.fc9")
    tbl, app = _hex(ram, wram)
    svc = _service()
    from dq3.testing import fixtures as FX

    got = FX.conditions_of(STATES / "DQ3_J.fc9")
    map_id = got.get("map_id")
    if map_id is None or svc.current_npcs(map_id, ram[0x06DF], tbl)["status"] != "DEFAULT":
        pytest.skip("⚠ save9 が「表が分かる」場面ではない")
    npcs = svc.current_npcs(map_id, ram[0x06DF], tbl)["npcs"]
    target = next((n for n in npcs if n.get("appearance_id") is not None), None)
    if target is None:
        pytest.skip("⚠ 見比べられる人が居ない")
    # ★その人の 1 つ下に立って、上を向く（⚠ 向き 0 = 上）
    start = (target["x"], target["y"] + 1)
    by_table = svc.npc_in_front(map_id, ram[0x06DF], tbl, start, 0)
    if by_table is None:
        pytest.skip("⚠ その升には立てない（★別の人が居る）")
    assert by_table.get("npc_id") is not None, "⚠⚠ 表から分かるのに npc_id が無い"
    by_look = svc.appearance_in_front(tbl, app, start, 0)
    assert by_look is not None, "⚠ 見た目の道が働いていない（★この検査が空回り）"
    assert by_look["label"] == svc.appearance_label(by_table["appearance_id"]), (
        by_look, by_table)
