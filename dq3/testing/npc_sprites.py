"""NPC の見た目（appearance id）を絵にする（RX3-0055 / probe_only）。

## ★どこから絵を取るか

```text
$F334（map 読み込みの終わり）が $6ABE[slot] の見た目 id ごとに
  CHR（sprite の pattern table $0000-$0FFF / ★$2000 の bit3 = 0）と
  記述子（WRAM $6E00 + 64*slot: 向き 4 × [止まり 8 バイト, 足 8 バイト] / 1 姿勢 = (tile, attr) × 4 枚）
を読み込む。★`dq3_appearance_probe.lua` が $F334 に hook して id を差し替え、両方を写す。
```

⚠ RAM の byte2 の上位 4 bit は歩きの段で、見た目ではない。★ここで使う id は ROM [1] & $FC（= $6ABE の値）。

## ★絵の組み方（$E8CC / $EE50 の写し）

```text
姿勢 = 記述子[向き*16 + (足 ? 8 : 0) : +8]  →  (tile, attr) を 左上・右上・左下・右下 の順に 4 枚
attr  bit6 = 左右反転 / bit7 = 上下反転 / bit1,0 = sprite パレット（$3F10 + n*4 / 色 0 は透明）
```

★ローカル生成物（PNG）は `work/dq3-probe/appearance/` だけ。⚠ Git に入れるのは 1 文字辞書 `data/dq3/npc-appearance-labels.json` だけ。
"""
from __future__ import annotations

import collections
import hashlib
import json
import pathlib

from dq3rom.render import NES_PALETTE, write_png

FACINGS = ("up", "right", "down", "left")
DESC_BASE = 0x6E00
DESC_PER_SLOT = 64
SPRITE_PAL = 0x10
CELL = 16
#: ★見本帳の背景（⚠ 透明の色 0 をこれで塗る。NES に無い色で見分けやすく）
BG = (0x30, 0x30, 0x30)
FRAME = (0x60, 0x60, 0x60)
TEXT = (0xF0, 0xF0, 0xF0)

#: ★3x5 の小さな字（0-9 A-F）。★整数拡大で読めればよい
GLYPHS = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "001", "001", "001"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    "A": ("111", "101", "111", "101", "101"), "B": ("110", "101", "110", "101", "110"),
    "C": ("111", "100", "100", "100", "111"), "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "111", "100", "111"), "F": ("111", "100", "111", "100", "100"),
    " ": ("000", "000", "000", "000", "000"),
}


def tile_pixels(chr_data: bytes, index: int) -> list[list[int]]:
    """★8x8 の色番号（0〜3）。"""
    o = index * 16
    rows = []
    for y in range(8):
        lo, hi = chr_data[o + y], chr_data[o + 8 + y]
        rows.append([((lo >> (7 - x)) & 1) | (((hi >> (7 - x)) & 1) << 1) for x in range(8)])
    return rows


def pose_of(desc: bytes, slot: int, facing: int, step: bool = False) -> list[tuple[int, int]]:
    """★記述子から 1 姿勢の (tile, attr) × 4。★順は 左上・右上・左下・右下。"""
    base = slot * DESC_PER_SLOT + facing * 16 + (8 if step else 0)
    return [(desc[base + i * 2], desc[base + i * 2 + 1]) for i in range(4)]


def sprite_pixels(chr_data: bytes, pal: bytes, pose) -> list[list[int | None]]:
    """★16x16 の NES 色番号（None = 透明）。"""
    out: list[list[int | None]] = [[None] * CELL for _ in range(CELL)]
    for q, (tile, attr) in enumerate(pose):
        ox, oy = (q & 1) * 8, (q >> 1) * 8
        rows = tile_pixels(chr_data, tile)
        p = attr & 3
        for y in range(8):
            for x in range(8):
                sx = 7 - x if attr & 0x40 else x
                sy = 7 - y if attr & 0x80 else y
                c = rows[sy][sx]
                if c:
                    out[oy + y][ox + x] = pal[SPRITE_PAL + p * 4 + c] & 0x3F
    return out


def load_batches(dir_path) -> list[dict]:
    out = []
    # ★extra_*（少ない id で撮り直したもの）を先に。⚠ 1 map の sprite の tile は $80-$FF の 128 枚しか無く、
    #   8 体まとめて読むと 7 体目以降が壊れる（2026-09-02: 18 / 1C が足だけになった）。★先に読んだ方が正になる
    files = sorted(pathlib.Path(dir_path).glob("extra_*.json")) + sorted(pathlib.Path(dir_path).glob("batch_*.json"))
    for p in files:
        body = json.loads(p.read_text(encoding="utf-8"))
        body["_file"] = p.name
        out.append(body)
    return out


def sprites_from_batches(batches: list[dict]) -> dict[int, dict]:
    """★appearance id → {facing: 16x16 色番号, ...}。⚠ 同じ id が 2 回出たら絵が同じか比べる。"""
    out: dict[int, dict] = {}
    for b in batches:
        desc, chr_data, pal = bytes.fromhex(b["desc"]), bytes.fromhex(b["chr"]), bytes.fromhex(b["pal"])
        slots = bytes.fromhex(b["slots"])
        for i, app in enumerate(b["ids"]):
            slot = 4 + i
            if slots[slot] != app:
                continue          # ⚠ 読み込まれていない
            faces = {f: sprite_pixels(chr_data, pal, pose_of(desc, slot, fi)) for fi, f in enumerate(FACINGS)}
            step = sprite_pixels(chr_data, pal, pose_of(desc, slot, 2, step=True))
            digest = _digest(faces)
            row = {"appearance_id": app, "faces": faces, "step_down": step, "digest": digest, "source": b["_file"],
                   "desc": desc[slot * DESC_PER_SLOT:(slot + 1) * DESC_PER_SLOT].hex(" ")}
            if app in out:
                out[app].setdefault("dupes", []).append({"source": b["_file"], "same": out[app]["digest"] == digest})
            else:
                out[app] = row
    return out


def sprite_from_savestate(state, slot: int) -> dict:
    """★セーブステートの WRAM 記述子 + CHR から同じ絵を組む（⚠ 実機の絵との突合に使う）。"""
    wram, chrr, pram = state.chunks["WRAM"], state.chunks["CHRR"], state.chunks["PRAM"]
    desc = wram[DESC_BASE - 0x6000:DESC_BASE - 0x6000 + 0x400]
    app = wram[0x6ABE - 0x6000 + slot]
    faces = {f: sprite_pixels(chrr, pram, pose_of(desc, slot, fi)) for fi, f in enumerate(FACINGS)}
    return {"appearance_id": app, "faces": faces, "digest": _digest(faces)}


def _digest(faces: dict) -> str:
    h = hashlib.sha1()
    for f in FACINGS:
        for row in faces[f]:
            h.update(bytes(0xFF if c is None else c for c in row))
    return h.hexdigest()[:12]


# ---------------------------------------------------------------------------
# ★見本帳
# ---------------------------------------------------------------------------

class Canvas:
    def __init__(self, w: int, h: int, bg=BG):
        self.w, self.h = w, h
        self.px = bytearray(bg * (w * h))

    def put(self, x: int, y: int, rgb) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            q = (y * self.w + x) * 3
            self.px[q], self.px[q + 1], self.px[q + 2] = rgb

    def rect(self, x: int, y: int, w: int, h: int, rgb) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.put(xx, yy, rgb)

    def sprite(self, x: int, y: int, pixels, scale: int) -> None:
        """★整数拡大（nearest neighbor / 補間なし）。"""
        for sy, row in enumerate(pixels):
            for sx, c in enumerate(row):
                if c is None:
                    continue
                self.rect(x + sx * scale, y + sy * scale, scale, scale, NES_PALETTE[c])

    def text(self, x: int, y: int, s: str, scale: int, rgb=TEXT) -> None:
        for i, ch in enumerate(s.upper()):
            g = GLYPHS.get(ch, GLYPHS[" "])
            for gy, row in enumerate(g):
                for gx, bit in enumerate(row):
                    if bit == "1":
                        self.rect(x + (i * 4 + gx) * scale, y + gy * scale, scale, scale, rgb)


def contact_sheet(sprites: dict[int, dict], path, scale: int = 4, columns: int = 6,
                  faces=("down", "left", "up")) -> dict:
    """★見本帳 PNG。★1 升 = id の字 + 向き 3 つ（正面 / 横 / 背面）。同じ id は 1 度だけ。"""
    ids = sorted(sprites)
    pad = 2 * scale
    cell_w = len(faces) * CELL * scale + (len(faces) + 1) * pad
    cell_h = 5 * scale + pad + CELL * scale + pad * 2
    rows = (len(ids) + columns - 1) // columns
    cv = Canvas(columns * cell_w + pad, rows * cell_h + pad)
    for i, app in enumerate(ids):
        cx, cy = pad + (i % columns) * cell_w, pad + (i // columns) * cell_h
        cv.rect(cx, cy, cell_w - pad, cell_h - pad, FRAME)
        cv.rect(cx + 1, cy + 1, cell_w - pad - 2, cell_h - pad - 2, BG)
        cv.text(cx + pad, cy + pad, "%02X" % app, scale)
        for k, f in enumerate(faces):
            cv.sprite(cx + pad + k * (CELL * scale + pad), cy + pad + 5 * scale + pad, sprites[app]["faces"][f], scale)
    write_png(pathlib.Path(path), cv.px, cv.w, cv.h)
    return {"path": str(path), "ids": len(ids), "columns": columns, "scale": scale, "faces": list(faces),
            "width": cv.w, "height": cv.h}


def index_rows(sprites: dict[int, dict], day: dict, night: dict) -> list[dict]:
    """★index.json（指示書 §5）: 使う NPC 数 / map / 昼夜。"""
    used = collections.Counter()
    maps = collections.defaultdict(set)
    when = collections.defaultdict(set)
    for lab, d in (("day", day), ("night", night)):
        for m in d["maps"]:
            for n in m["npcs"]:
                used[n["appearance_id"]] += 1
                maps[n["appearance_id"]].add(m["map_id"])
                when[n["appearance_id"]].add(lab)
    out = []
    for app in sorted(set(used) | set(sprites)):
        sp = sprites.get(app)
        out.append({"appearance_id": app, "hex": "%02X" % app, "used_by_npcs": used.get(app, 0),
                    "used_in_maps": sorted(maps.get(app, ())),
                    "time": "both" if when.get(app) == {"day", "night"} else "/".join(sorted(when.get(app, ()))),
                    "rendered": sp is not None, "digest": sp["digest"] if sp else None,
                    "source": sp["source"] if sp else None})
    return out


# ---------------------------------------------------------------------------
# ★公開する辞書（★値は依頼者が決める）
# ---------------------------------------------------------------------------

LABELS_PATH = pathlib.Path(__file__).resolve().parents[2] / "data" / "dq3" / "npc-appearance-labels.json"
UNDEFINED = "？"


def write_labels_skeleton(ids, path=LABELS_PATH, keep=None) -> pathlib.Path:
    """★id → null の辞書を書く。⚠ 既に値が入っている id はそのまま残す（★依頼者の決めた字を消さない）。"""
    path = pathlib.Path(path)
    keep = dict(keep or {})
    if path.exists():
        try:
            keep.update(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            pass
    body = {str(app): keep.get(str(app)) for app in sorted(ids)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_labels(path=LABELS_PATH) -> dict[int, str | None]:
    path = pathlib.Path(path)
    if not path.exists():
        return {}
    body = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in body.items()}


def label_for(appearance_id: int, labels: dict | None = None) -> str:
    """★1 文字。⚠ 未定義 / 無い id は「？」。"""
    labels = load_labels() if labels is None else labels
    v = labels.get(appearance_id)
    return v if isinstance(v, str) and v else UNDEFINED


def build(root) -> dict:
    """★成果物を全部書く: contact-sheet.png / index.json / 辞書の骨（null）。"""
    root = pathlib.Path(root)
    app_dir = root / "work" / "dq3-probe" / "appearance"
    day = json.loads((root / "work/dq3-probe/npcs/all-maps-day.json").read_text(encoding="utf-8"))
    night = json.loads((root / "work/dq3-probe/npcs/all-maps-night.json").read_text(encoding="utf-8"))
    sprites = sprites_from_batches(load_batches(app_dir))
    sheet = contact_sheet(sprites, app_dir / "contact-sheet.png")
    rows = index_rows(sprites, day, night)
    (app_dir / "index.json").write_text(json.dumps({
        "sheet": sheet, "appearance_count": len(rows), "rendered": sum(1 for r in rows if r["rendered"]),
        "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    labels = write_labels_skeleton([r["appearance_id"] for r in rows])
    return {"sheet": sheet, "appearance_count": len(rows), "rendered": sum(1 for r in rows if r["rendered"]),
            "labels": str(labels), "dupes": {app: s["dupes"] for app, s in sprites.items() if s.get("dupes")}}
