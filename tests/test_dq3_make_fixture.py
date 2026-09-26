"""save0 から派生 savestate を作る道具（RX-A §5〜§9 / 2026-09-23）。

```text
A  ★書き戻しても他の塊は 1 バイトも変わらない
B  ⚠ HP/MP は上限を超えない。★HP は 0 にしない（＝死亡を作らない）
C  ★unequip は bit7 だけ落とす
D  ★discard は枠を空ける。⚠ 装備中・手放せない品は**断る**
E  ★give は渡し先に空きが要る
F  ⚠⚠ 元が変わっていたら**止まる**（★撮り直し / RX3-0028）
G  ⚠ RAM の長さは変えられない
H  ⚠⚠ 0 件を**通過にしない**
```

⚠ 本物の savestate は使いません（★撮り直されると赤くなる / RX3-0028）。
★`FCSX` の形をその場で組み立てて確かめます。
"""
from __future__ import annotations

import json
import pathlib
import sys
import zlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dq3_make_fixture as MK                               # noqa: E402

#: ★作り物の品（⚠ ROM が無い環境でも回る）
ITEMS = {"けんじゃのいし": 80, "ちからのたて": 58, "いなづまのけん": 26,
         "おうじゃのけん": 28, "さいごのかぎ": 90}
#: ⚠ 手放せない品（★ROM の印の代わり）
KEEP = {90}


@pytest.fixture(autouse=True)
def _rom(monkeypatch):
    monkeypatch.setattr(MK, "item_id_of", lambda name: ITEMS[str(name)])
    monkeypatch.setattr(MK, "can_discard", lambda item_id: item_id not in KEEP)


def _profile() -> dict:
    path = ROOT / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json"
    return json.loads(path.read_text(encoding="utf-8"))["runtime"]["party"]


def make_ram(members) -> bytearray:
    """★`members` = `[(hp, hp_max, mp, mp_max, [(id, 装備か), …]), …]`。"""
    p = _profile()
    ram = bytearray(2048)

    def at(key) -> int:
        return int(str(p[key]), 16)

    for i, (hp, hp_max, mp, mp_max, items) in enumerate(members):
        for key, value in (("hp_current", hp), ("hp_max", hp_max),
                           ("mp_current", mp), ("mp_max", mp_max)):
            ram[at(key) + i * 2] = value & 0xFF
            ram[at(key) + i * 2 + 1] = value >> 8
        base = at("items") + i * int(p["item_slots"])
        for s in range(int(p["item_slots"])):
            ram[base + s] = MK.EMPTY
        for s, (item_id, equipped) in enumerate(items):
            ram[base + s] = item_id | (MK.EQUIPPED if equipped else 0)
    return ram


def make_state(path: pathlib.Path, ram: bytes, *, packed: bool = True) -> pathlib.Path:
    """★`FCSX` の形をその場で作る（⚠ 本物は使わない）。"""
    body = (b"CPUS" + (4).to_bytes(4, "little") + b"\x01\x02\x03\x04"
            + b"RAM\x00" + len(ram).to_bytes(4, "little") + bytes(ram)
            + b"PPUS" + (3).to_bytes(4, "little") + b"\x09\x08\x07")
    head = MK.MAGIC + len(body).to_bytes(4, "little") + (20606).to_bytes(4, "little")
    if packed:
        blob = zlib.compress(body, 9)
        raw = head + len(blob).to_bytes(4, "little") + blob
    else:
        raw = head + MK.UNCOMPRESSED.to_bytes(4, "little") + body
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def bag(ram, slot: int) -> list:
    p = _profile()
    base = int(str(p["items"]), 16) + (slot - 1) * int(p["item_slots"])
    return [ram[base + s] for s in range(int(p["item_slots"]))]


# --- ★Case A ---------------------------------------------------------------

@pytest.mark.parametrize("packed", [True, False])
def test_A_書き戻しても他の塊は変わらない(tmp_path, packed):
    from retroux.core.bgmap import savestate as SS

    ram = make_ram([(100, 100, 10, 10, [(80, False)])])
    src = make_state(tmp_path / "src.fcs", ram, packed=packed)
    out = MK.write_with_ram(src, tmp_path / "out.fcs", bytes(ram))
    a, b = SS.load(src), SS.load(out)
    assert sorted(a.chunks) == sorted(b.chunks)
    assert all(a.chunks[k] == b.chunks[k] for k in a.chunks)


def test_A_RAMだけが変わる(tmp_path):
    from retroux.core.bgmap import savestate as SS

    ram = make_ram([(100, 100, 10, 10, [(80, False)])])
    src = make_state(tmp_path / "src.fcs", ram)
    edited = bytearray(ram)
    edited[0x123] = 0x5A
    out = MK.write_with_ram(src, tmp_path / "out.fcs", bytes(edited))
    a, b = SS.load(src), SS.load(out)
    assert a.chunks["RAM"] != b.chunks["RAM"]
    assert b.chunks["RAM"][0x123] == 0x5A
    assert a.chunks["CPUS"] == b.chunks["CPUS"] and a.chunks["PPUS"] == b.chunks["PPUS"]


# --- ★Case B ---------------------------------------------------------------

def test_B_HPは上限を超えず0にもしない():
    ram = make_ram([(300, 385, 40, 135, [])])
    MK.apply_change(ram, {"op": "hp", "slot": 1, "ratio": 0.60})
    p = _profile()
    at = int(str(p["hp_current"]), 16)
    assert ram[at] + ram[at + 1] * 256 == 231                 # ★385 の 60%

    MK.apply_change(ram, {"op": "hp", "slot": 1, "value": 9999})
    assert ram[at] + ram[at + 1] * 256 == 385                 # ⚠ 上限で止まる

    MK.apply_change(ram, {"op": "hp", "slot": 1, "value": 0})
    assert ram[at] + ram[at + 1] * 256 == 1                   # ⚠⚠ 0 = 死亡 は作らない


def test_B_MPは0にできるが上限は超えない():
    ram = make_ram([(300, 385, 40, 135, [])])
    p = _profile()
    at = int(str(p["mp_current"]), 16)
    MK.apply_change(ram, {"op": "mp", "slot": 1, "value": 0})
    assert ram[at] + ram[at + 1] * 256 == 0                   # ★MP 0 は普通にある
    MK.apply_change(ram, {"op": "mp", "slot": 1, "value": 999})
    assert ram[at] + ram[at + 1] * 256 == 135


def test_B_居ない枠は断る():
    ram = make_ram([(300, 385, 40, 135, [])])
    with pytest.raises(MK.SpecError):
        MK.apply_change(ram, {"op": "hp", "slot": 3, "ratio": 0.5})


# --- ★Case C / D / E -------------------------------------------------------

def test_C_unequipはbit7だけ落とす():
    ram = make_ram([(300, 385, 40, 135, [(28, True), (80, False)])])
    MK.apply_change(ram, {"op": "unequip", "slot": 1, "item": "おうじゃのけん"})
    assert bag(ram, 1)[:2] == [28, 80]                        # ★番号はそのまま


def test_C_装備していないものは外せない():
    ram = make_ram([(300, 385, 40, 135, [(28, False)])])
    with pytest.raises(MK.SpecError):
        MK.apply_change(ram, {"op": "unequip", "slot": 1, "item": "おうじゃのけん"})


def test_D_discardは枠を空ける():
    ram = make_ram([(300, 385, 40, 135, [(80, False), (58, False)])])
    MK.apply_change(ram, {"op": "discard", "slot": 1, "item": "けんじゃのいし"})
    assert bag(ram, 1)[0] == MK.EMPTY
    assert bag(ram, 1).count(MK.EMPTY) == 7


def test_D_装備中と手放せない品は断る():
    ram = make_ram([(300, 385, 40, 135, [(28, True), (90, False)])])
    with pytest.raises(MK.SpecError):
        MK.apply_change(ram, {"op": "discard", "slot": 1, "item": "おうじゃのけん"})
    with pytest.raises(MK.SpecError):                         # ⚠ さいごのかぎ
        MK.apply_change(ram, {"op": "discard", "slot": 1, "item": "さいごのかぎ"})


def test_E_giveは渡し先に空きが要る():
    ram = make_ram([(300, 385, 40, 135, [(80, False)]),
                    (300, 378, 40, 74, [(x, False) for x in range(1, 9)])])
    with pytest.raises(MK.SpecError):                         # ⚠ p2 は満タン
        MK.apply_change(ram, {"op": "give", "item": "けんじゃのいし", "from": 1, "to": 2})
    ram2 = make_ram([(300, 385, 40, 135, [(80, False)]),
                     (300, 378, 40, 74, [(26, False)])])
    MK.apply_change(ram2, {"op": "give", "item": "けんじゃのいし", "from": 1, "to": 2})
    assert bag(ram2, 1)[0] == MK.EMPTY
    assert 80 in bag(ram2, 2)


# --- ★Case F ---------------------------------------------------------------

def test_F_元が変わっていたら止まる(tmp_path):
    ram = make_ram([(300, 385, 40, 135, [(80, False)])])
    src = make_state(tmp_path / "src.fcs", ram)
    spec = {"fixture_id": "x", "source": str(src), "source_sha256": "0" * 64,
            "changes": [{"op": "hp", "slot": 1, "ratio": 0.5}]}
    with pytest.raises(MK.SpecError) as got:
        MK.build(spec, out_dir=tmp_path)
    assert "変わっています" in str(got.value)


def test_F_changesが空なら止まる(tmp_path):
    ram = make_ram([(300, 385, 40, 135, [(80, False)])])
    src = make_state(tmp_path / "src.fcs", ram)
    with pytest.raises(MK.SpecError):
        MK.build({"fixture_id": "x", "source": str(src), "changes": []}, out_dir=tmp_path)


# --- ★Case G ---------------------------------------------------------------

def test_G_RAMの長さは変えられない(tmp_path):
    ram = make_ram([(300, 385, 40, 135, [])])
    src = make_state(tmp_path / "src.fcs", ram)
    with pytest.raises(MK.SpecError):
        MK.write_with_ram(src, tmp_path / "out.fcs", bytes(ram) + b"\x00")


def test_G_知らないopは断る():
    ram = make_ram([(300, 385, 40, 135, [])])
    with pytest.raises(MK.SpecError):
        MK.apply_change(ram, {"op": "equip", "slot": 1, "item": "おうじゃのけん"})


# --- ★Case H ---------------------------------------------------------------

def test_H_0件を通過にしない(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(MK, "SPEC_DIR", tmp_path / "からっぽ")
    (tmp_path / "からっぽ").mkdir()
    assert MK.main(["--all"]) == 1                            # ⚠⚠ 0 を成功にしない
    assert "1 つもありません" in capsys.readouterr().out


# --- ★Case I: 元を書かない（依頼者 §5）--------------------------------------

def test_I_元のファイルは変わらない(tmp_path):
    ram = make_ram([(300, 385, 40, 135, [(80, False)])])
    src = make_state(tmp_path / "src.fcs", ram)
    before = src.read_bytes()
    spec = {"fixture_id": "x", "source": str(src),
            "source_sha256": MK.sha256_of(src),
            "changes": [{"op": "hp", "slot": 1, "ratio": 0.5}]}
    made = MK.build(spec, out_dir=tmp_path / "out")
    assert src.read_bytes() == before                         # ⚠⚠ ここが依頼者 §5
    assert made["path"] != src
    assert MK.read_ram(made["path"]) != bytes(ram)            # ★中身は変わっている


# --- ★Case J: spec は全部そろっているか（★実際に置いたもの）-------------------

def test_J_specは読めてidが重なっていない():
    specs = MK.load_specs()
    assert specs, "⚠⚠ spec が 1 つもありません"
    ids = [s["fixture_id"] for s in specs]
    assert len(ids) == len(set(ids)), "⚠ fixture_id が重なっています"
    for spec in specs:
        assert spec.get("source"), spec["fixture_id"]
        assert spec.get("source_sha256"), spec["fixture_id"]   # ⚠ 元を固定する
        assert spec.get("purpose"), spec["fixture_id"]
        assert spec.get("changes"), spec["fixture_id"]
