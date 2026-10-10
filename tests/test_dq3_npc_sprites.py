"""NPC の見た目（RX3-0055）。★作った CHR / 記述子で組み方を検査し、辞書の読み方を検査する。"""
from __future__ import annotations

import json
import pathlib
import subprocess

from dq3.testing import npc_sprites as NS

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _chr(tiles: dict[int, list[str]]) -> bytes:
    """★tile 番号 → 8 行の '0123' 文字列 から CHR を作る。"""
    data = bytearray(0x1000)
    for idx, rows in tiles.items():
        for y, row in enumerate(rows):
            lo = hi = 0
            for x, ch in enumerate(row):
                c = int(ch)
                lo |= (c & 1) << (7 - x)
                hi |= ((c >> 1) & 1) << (7 - x)
            data[idx * 16 + y] = lo
            data[idx * 16 + 8 + y] = hi
    return bytes(data)


def test_tileの2枚のbitplaneを色番号に():
    chr_ = _chr({0x80: ["12300000"] + ["00000000"] * 7})
    rows = NS.tile_pixels(chr_, 0x80)
    assert rows[0][:4] == [1, 2, 3, 0] and rows[1] == [0] * 8


def test_姿勢は左上右上左下右下で反転を効かせる():
    chr_ = _chr({0x80: ["10000000"] + ["00000000"] * 7})       # ★左上の 1 画素だけ
    pal = bytes([0x0F] * 16 + [0x0F, 0x30, 0x16, 0x27] + [0x0F] * 12)
    desc = bytearray(0x400)
    slot, facing = 4, 2
    base = slot * 64 + facing * 16
    desc[base:base + 8] = bytes([0x80, 0x00, 0x80, 0x40, 0x80, 0x80, 0x80, 0xC0])   # 無し / 左右 / 上下 / 両方
    px = NS.sprite_pixels(chr_, pal, NS.pose_of(bytes(desc), slot, facing))
    assert px[0][0] == 0x30 and px[0][15] == 0x30 and px[15][0] == 0x30 and px[15][15] == 0x30
    assert sum(1 for row in px for c in row if c is not None) == 4


def test_同じidが2回出たら絵が同じか記す():
    chr_ = _chr({0x80: ["10000000"] + ["00000000"] * 7})
    desc = bytearray(0x400)
    desc[4 * 64:4 * 64 + 8] = bytes([0x80, 0, 0x80, 0, 0x80, 0, 0x80, 0])
    b = {"ids": [0x14], "slots": bytes([0] * 4 + [0x14] + [0xFF] * 11).hex(), "desc": desc.hex(), "chr": chr_.hex(),
         "pal": bytes(32).hex(), "_file": "a.json"}
    b2 = dict(b, _file="b.json")
    got = NS.sprites_from_batches([b, b2])
    assert got[0x14]["source"] == "a.json" and got[0x14]["dupes"] == [{"source": "b.json", "same": True}]


def test_見本帳はPNGで整数拡大(tmp_path):
    chr_ = _chr({0x80: ["11111111"] * 8})
    desc = bytearray(0x400)
    for f in range(4):
        desc[4 * 64 + f * 16:4 * 64 + f * 16 + 8] = bytes([0x80, 0, 0x80, 0, 0x80, 0, 0x80, 0])
    pal = bytes([0x0F] * 16 + [0x0F, 0x30, 0x16, 0x27] + [0x0F] * 12)
    sp = NS.sprites_from_batches([{"ids": [0x14], "slots": bytes([0] * 4 + [0x14] + [0xFF] * 11).hex(),
                                   "desc": desc.hex(), "chr": chr_.hex(), "pal": pal.hex(), "_file": "a.json"}])
    got = NS.contact_sheet(sp, tmp_path / "sheet.png", scale=3, columns=2)
    data = (tmp_path / "sheet.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and got["ids"] == 1 and got["scale"] == 3


def test_辞書は未定義を疑問符に(tmp_path):
    p = tmp_path / "labels.json"
    NS.write_labels_skeleton([0x14, 0x1C], p)
    assert json.loads(p.read_text(encoding="utf-8")) == {"20": None, "28": None}
    p.write_text(json.dumps({"20": "商", "28": None}), encoding="utf-8")
    # ★骨を書き直しても依頼者の字は消えない
    NS.write_labels_skeleton([0x14, 0x1C, 0x50], p)
    labels = NS.load_labels(p)
    assert labels == {0x14: "商", 0x1C: None, 0x50: None}
    assert NS.label_for(0x14, labels) == "商"
    assert NS.label_for(0x1C, labels) == NS.UNDEFINED and NS.label_for(0x99, labels) == "？"


def test_公開辞書は値が1文字かnull():
    if not NS.LABELS_PATH.exists():
        return
    body = json.loads(NS.LABELS_PATH.read_text(encoding="utf-8"))
    assert body, "⚠ 空の辞書"
    for k, v in body.items():
        assert k.isdigit() and int(k) % 4 == 0, k
        assert v is None or (isinstance(v, str) and len(v) == 1), (k, v)


def test_画像はGitに入らない():
    """⚠ 指示書 §9: contact sheet / sprite PNG は work/ に置き、Git 管理外。"""
    got = subprocess.run(["git", "check-ignore", "-q", "work/runtime/dq3-probe/appearance/contact-sheet.png"],
                         cwd=str(ROOT), capture_output=True)
    assert got.returncode == 0, "⚠ work/runtime/dq3-probe/appearance/ が .gitignore に無い"
    tracked = subprocess.run(["git", "ls-files", "--", "*.png", "*.json"], cwd=str(ROOT), capture_output=True,
                             text=True).stdout.splitlines()
    # ⚠ `artifacts/maps/contact-sheet.png` は別件（RX3-0028 の地図）。★見るのは NPC の見本帳の置き場だけ
    leaked = [p for p in tracked if "dq3-probe/appearance" in p or p.startswith("work/")]
    assert leaked == [], leaked


def test_卑弥呼の見た目は船ではない():
    """⚠⚠ RX3-0246（2026-09-13 依頼者「卑弥呼のキャラグラと会話したら、船（船長）だった。多分私の設定が間違っている」）。

    ★見た目 48・176 を使うのは、全 map・昼夜とも ジパング（map 23）の卑弥呼だけ（(18,7) の talk 979・214 / (18,92) の talk 406）。
    → ★字は「卑」（⚠ 以前は「船」= 依頼者の見立て違い / 推奨案で直した）。
    """
    import pytest

    from dq3.knowledge import npc_master as M

    try:
        lists = M._lists()
    except Exception:                                            # noqa: BLE001
        pytest.skip("DQ3 の ROM が読めない")
    if len(lists) <= 23:
        pytest.skip("DQ3 の ROM が読めない")
    users = set()
    for night in (False, True):
        for mid in range(len(lists)):
            try:
                npcs = M._rom.map_ledger(mid, lists[mid], night)["npcs"]
            except Exception:                                    # noqa: BLE001
                continue
            users |= {mid for n in npcs if n.get("appearance_id") in (48, 176)}
    assert users == {23}, "⚠ 見た目 48・176 をジパング以外でも使っている: %s" % sorted(users)
    labels = NS.load_labels()
    assert labels.get(48) == labels.get(176) == "卑", (labels.get(48), labels.get(176))
