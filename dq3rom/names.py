"""名前辞書 — ユーザーの ROM から実行時に名前を復号する（RX3-0069 / 2026-09-03）。

★★ 原作の名称一覧は**持ちません**。ここにあるのは「どこに・どの形で」だけです ★★

  持つもの     bank / file id / 表の先頭 / 1 件の大きさ / 符号の規則 / 検算の数
  持たないもの 名前そのもの（⚠ ユーザーの ROM から**その場で**起こす）

## ★実測で確定した構造（2026-09-03 / 実機 trace + 逆アセンブル）

```text
bank 10（$0A）の「ファイル表」$8000（★北米版と同じ仕組み。JP は固定バンク $C4E0 / $C501 が引く）
  local 2  → モンスター名（前半）  file 0x181   ★FF 区切り・可変長
  local 6  → モンスター名（後半）  file 0x198   ★id 84 から（bank 14 $90D9: SBC #$54）
  local 3  → 道具の表への pointer  file 0x186   ★先頭 2 バイトが表の実体を指す
  local 4  → 呪文の表への pointer  file 0x187   ★同上
  local 5  → 次の表（★道具の終わり＝件数の検算に使う）

道具  1 件 9 バイト = 名前 7 + 濁点マスク 1 + 属性 1     bank 14 $8FE0: 位置 = 先頭 + id × (幅+2)
呪文  1 件 7 バイト = 名前 5 + 濁点マスク 1 + 属性 1     bank 14 $9043 / $8FFD: 幅ぶん複写
モンスター  FF で終わる可変長                          固定 $FF17: FF を id 本数えて飛ばす
```

## ★符号（★bank 14 $89B0 / $B1D8 / $B1DD で確定）

```text
1 バイト = 1 文字。CHR のタイル索引 0x100 + byte が字形（★profile の text 表）
固定長表  マスクの bit（先頭の字 = 最上位 bit）が立った位置に ゛（tile 0x6A）
          ⚠ その字が 0xA4-0xA8（はひふへほ）/ 0xCD-0xD0（ハヒフヘホ）で bit7 付きなら
            bit7 を落として ゜（tile 0x6B）  ★メダパニ の パ = 0xCD
FF 区切り  F7 = 次の字に ゛ / F6 = 次の字に ゜ / FF = 終わり
```

⚠ 主キーは **(kind, id)** です。★名前は ROM 由来の**表示属性**で、鍵にしません。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import unicodedata

from dq3rom import profile as P

#: ★符号の解釈を変えたら上げる（⚠ cache の鍵に入る）
DECODER_VERSION = 4

KINDS = ("monster", "item", "spell", "place")

#: ★゛と ゜（Unicode の結合文字。NFC で合成する）
DAKUTEN = "゙"
HANDAKUTEN = "゚"


class NameTableError(P.ProfileError):
    """名前表の構造が期待と違う（★版違い・壊れた ROM）。⚠ 推測で読まない。"""


@dataclasses.dataclass(frozen=True)
class Entry:
    kind: str
    entity_id: int
    raw: bytes
    mask: int | None
    attr: int | None
    name: str
    source_bank: int
    source_address: int
    unknown_bytes: tuple[int, ...] = ()

    def to_json(self) -> dict:
        return {
            "kind": self.kind, "id": self.entity_id, "name": self.name,
            "raw": self.raw.hex(), "mask": self.mask, "attr": self.attr,
            "bank": self.source_bank, "address": "0x%04X" % self.source_address,
            "unknown": list(self.unknown_bytes),
        }


# --- ★字形表 ------------------------------------------------------------------

def _charset(ident: P.Identified) -> dict[int, str]:
    """★CHR のタイル索引 → 文字（⚠ profile から。ここに文字を書かない）。"""
    spec = ident.profile.data.get("text") or {}
    out: dict[int, str] = {}
    for base, text in (spec.get("runs") or {}).items():
        for i, ch in enumerate(text):
            out[int(base) + i] = ch
    for key, ch in (spec.get("single") or {}).items():
        out[int(key)] = ch
    return out


def _compose(ch: str, mark: str) -> str:
    return unicodedata.normalize("NFC", ch + mark)


def _spec(ident: P.Identified) -> dict:
    return ident.table("names")


# --- ★表の場所（⚠ ファイル表から辿る。番地を決め打ちしない）----------------------

@dataclasses.dataclass(frozen=True)
class Layout:
    bank: int
    monster_lo: int      #: ★id 0..split-1 の先頭
    monster_hi: int      #: ★id split.. の先頭
    monster_split: int
    monster_count: int
    item_base: int
    item_width: int
    item_count: int
    spell_base: int
    spell_width: int
    spell_count: int
    #: ★地名（ルーラの行き先 / RX3-0092）。⚠ `spell_file` は呪文の**ファイル**の先頭
    place_base: int = 0
    place_width: int = 0
    place_count: int = 0
    spell_file: int = 0


def _word(ident: P.Identified, bank: int, cpu: int) -> int:
    off = ident.file_offset(bank, cpu)
    prg = ident.rom.prg
    i = off - P.HEADER
    return prg[i] | (prg[i + 1] << 8)


def layout(ident: P.Identified) -> Layout:
    """★ファイル表から 3 表の場所を出し、⚠ 検算が合わなければ断る。"""
    spec = _spec(ident)
    bank = int(spec["bank"])
    files = spec["file_table"]
    base = int(str(files["cpu"]), 16)

    def local(n: int) -> int:
        return _word(ident, bank, base + n * 2)

    monster_lo = local(int(files["monster_lo"]))
    monster_hi = local(int(files["monster_hi"]))
    item_ptr = local(int(files["item"]))
    spell_ptr = local(int(files["spell"]))
    item_end = local(int(files["item_end"]))
    # ★道具・呪文のファイルは、先頭 2 バイトが表の実体を指す（固定 $C5AA / $C5C9）
    item_base = _word(ident, bank, item_ptr)
    spell_base = _word(ident, bank, spell_ptr)

    place_ptr = local(int(files["place"]))
    place_base = _word(ident, bank, place_ptr)
    iw, sw = int(spec["item"]["width"]), int(spec["spell"]["width"])
    item_size, spell_size = iw + 2, sw + 2
    if (item_end - item_base) % item_size:
        raise NameTableError("道具の表の長さが %d バイトの倍数ではありません" % item_size)
    if (monster_lo - spell_base) % spell_size:
        raise NameTableError("呪文の表の長さが %d バイトの倍数ではありません" % spell_size)
    item_count = (item_end - item_base) // item_size
    spell_count = (monster_lo - spell_base) // spell_size
    if item_count != int(spec["item"]["count"]):
        raise NameTableError("道具の件数が違います: %d（期待 %s）" % (item_count, spec["item"]["count"]))
    if spell_count != int(spec["spell"]["count"]):
        raise NameTableError("呪文の件数が違います: %d（期待 %s）" % (spell_count, spec["spell"]["count"]))

    pw = int(spec["place"]["width"])
    place_size = pw + 2
    if (spell_ptr - place_base) % place_size:
        raise NameTableError("地名の表の長さが %d バイトの倍数ではありません" % place_size)
    place_count = (spell_ptr - place_base) // place_size
    if place_count != int(spec["place"]["count"]):
        raise NameTableError("地名の件数が違います: %d（期待 %s）" % (place_count, spec["place"]["count"]))

    split = int(spec["monster"]["split"])
    count = int(spec["monster"]["count"])
    # ★FF を split 本数えた先が後半のファイルの先頭でなければ、表が違う
    at = _skip_ff(ident, bank, monster_lo, split)
    if at != monster_hi:
        raise NameTableError("モンスター名の前半 %d 本の終わりが後半の先頭と合いません（$%04X ≠ $%04X）"
                             % (split, at, monster_hi))
    return Layout(bank, monster_lo, monster_hi, split, count,
                  item_base, iw, item_count, spell_base, sw, spell_count,
                  place_base, pw, place_count, spell_ptr)


def _skip_ff(ident: P.Identified, bank: int, cpu: int, n: int) -> int:
    """★固定 $FF17 と同じ: FF を n 本数えて飛ばした先の CPU 番地。"""
    prg = ident.rom.prg
    i = ident.prg_offset(bank, cpu)
    limit = i + 0x2000
    while n > 0:
        if i >= limit:
            raise NameTableError("FF 区切りの走査が長すぎます（表が壊れている）")
        if prg[i] == 0xFF:
            n -= 1
        i += 1
    return 0x8000 + (i - bank * P.BANK)


# --- ★復号 ---------------------------------------------------------------------

def _decode_fixed(raw: bytes, mask: int, width: int, chars: dict[int, str],
                  handaku_ranges: list[tuple[int, int]]) -> tuple[str, tuple[int, ...]]:
    out, unknown = [], []
    for i, b in enumerate(raw[:width]):
        if b == 0:
            break                      # ★詰め物（空白）で終わり
        flagged = bool(mask & (1 << (width - 1 - i)))
        if flagged and b >= 0x80 and any(lo <= b < hi for lo, hi in handaku_ranges):
            ch = chars.get(0x100 + (b & 0x7F))
            if ch is None:
                unknown.append(b); out.append("?"); continue
            out.append(_compose(ch, HANDAKUTEN))
            continue
        ch = chars.get(0x100 + b)
        if ch is None:
            unknown.append(b); out.append("?"); continue
        out.append(_compose(ch, DAKUTEN) if flagged else ch)
    return "".join(out).rstrip("␣ "), tuple(unknown)


def _decode_ff(raw: bytes, chars: dict[int, str]) -> tuple[str, tuple[int, ...]]:
    out, unknown, i = [], [], 0
    while i < len(raw):
        b = raw[i]
        if b in (0xF7, 0xF6) and i + 1 < len(raw):
            ch = chars.get(0x100 + raw[i + 1])
            if ch is None:
                unknown.append(raw[i + 1]); out.append("?")
            else:
                out.append(_compose(ch, DAKUTEN if b == 0xF7 else HANDAKUTEN))
            i += 2
            continue
        ch = chars.get(0x100 + b)
        if ch is None:
            unknown.append(b); out.append("?")
        else:
            out.append(ch)
        i += 1
    return "".join(out).rstrip("␣ "), tuple(unknown)


class NameDictionary:
    """★(kind, id) → 名前。⚠ 名前は ROM 由来の表示属性で、鍵にしない。"""

    def __init__(self, ident: P.Identified) -> None:
        self.ident = ident
        self.layout = layout(ident)
        self.chars = _charset(ident)
        spec = _spec(ident)
        self.handaku = [(int(str(a), 16), int(str(b), 16)) for a, b in spec["handakuten_byte_ranges"]]
        # ★同じ絵を 2 つの かな で使い回している分（RX3-0093）
        from dq3rom.kana import ambiguous_kana

        self.known = set(self.chars.values())
        self.ambiguous = ambiguous_kana(self.known)
        self._entries: dict[str, list[Entry]] = {}

    # --- ★1 件 ---------------------------------------------------------------

    def _display(self, name: str) -> str:
        """★画面に出す形（⚠ 同じ絵を使い回している かな を直す / RX3-0093）。"""
        from dq3rom.kana import katakana_word

        return katakana_word(name, self.known, self.ambiguous)

    def monster(self, entity_id: int) -> Entry:
        lay = self.layout
        if not 0 <= entity_id < lay.monster_count:
            raise IndexError("monster id %d" % entity_id)
        if entity_id < lay.monster_split:
            start = _skip_ff(self.ident, lay.bank, lay.monster_lo, entity_id)
        else:
            start = _skip_ff(self.ident, lay.bank, lay.monster_hi, entity_id - lay.monster_split)
        prg = self.ident.rom.prg
        i = self.ident.prg_offset(lay.bank, start)
        j = i
        while prg[j] != 0xFF:
            j += 1
            if j - i > 32:
                raise NameTableError("モンスター名 %d に終端がありません" % entity_id)
        raw = bytes(prg[i:j])
        name, unknown = _decode_ff(raw, self.chars)
        return Entry("monster", entity_id, raw, None, None, self._display(name),
                     lay.bank, start, unknown)

    def _fixed(self, kind: str, entity_id: int, base: int, width: int, count: int) -> Entry:
        if not 0 <= entity_id < count:
            raise IndexError("%s id %d" % (kind, entity_id))
        size = width + 2
        cpu = base + entity_id * size
        i = self.ident.prg_offset(self.layout.bank, cpu)
        rec = bytes(self.ident.rom.prg[i:i + size])
        name, unknown = _decode_fixed(rec[:width], rec[width], width, self.chars, self.handaku)
        return Entry(kind, entity_id, rec, rec[width], rec[width + 1], self._display(name),
                     self.layout.bank, cpu, unknown)

    def item(self, entity_id: int) -> Entry:
        lay = self.layout
        return self._fixed("item", entity_id, lay.item_base, lay.item_width, lay.item_count)

    def spell(self, entity_id: int) -> Entry:
        lay = self.layout
        return self._fixed("spell", entity_id, lay.spell_base, lay.spell_width, lay.spell_count)

    def place(self, entity_id: int) -> Entry:
        """★ルーラの行き先の名前（⚠ 並びは `rura_points` と同じ / RX3-0092）。"""
        lay = self.layout
        return self._fixed("place", entity_id, lay.place_base, lay.place_width, lay.place_count)

    def resolve(self, kind: str, entity_id: int) -> Entry:
        return {"monster": self.monster, "item": self.item, "spell": self.spell,
                "place": self.place}[kind](entity_id)

    # --- ★全部 ---------------------------------------------------------------

    def count(self, kind: str) -> int:
        return {"monster": self.layout.monster_count, "item": self.layout.item_count,
                "spell": self.layout.spell_count, "place": self.layout.place_count}[kind]

    def all(self, kind: str) -> list[Entry]:
        if kind not in self._entries:
            self._entries[kind] = [self.resolve(kind, i) for i in range(self.count(kind))]
        return self._entries[kind]

    # --- ★cache（⚠ ROM ごと / decoder の版ごと。Git の外）------------------------

    def cache_key(self) -> str:
        return "%s:%s:v%d" % (self.ident.game_id, self.ident.rom.prg_crc32, DECODER_VERSION)

    def to_cache(self) -> dict:
        return {
            "game_id": self.ident.game_id,
            "rom_payload_crc32": self.ident.rom.prg_crc32,
            "rom_payload_sha1": hashlib.sha1(self.ident.rom.prg).hexdigest(),
            "decoder_version": DECODER_VERSION,
            "layout": dataclasses.asdict(self.layout),
            "names": {kind: {str(e.entity_id): e.name for e in self.all(kind)} for kind in KINDS},
            "unknown": {kind: {str(e.entity_id): list(e.unknown_bytes) for e in self.all(kind) if e.unknown_bytes}
                        for kind in KINDS},
        }


# --- ★置き場つきの入口 -----------------------------------------------------------

DEFAULT_CACHE = pathlib.Path(__file__).resolve().parents[1] / "work" / "generated" / "dq3-names.json"


def load_cached(rom_path: str | pathlib.Path, cache_path: pathlib.Path | None = None) -> dict:
    """★cache が ROM と版に合えばそれを、⚠ 合わなければ復号し直して書く。"""
    cache_path = cache_path or DEFAULT_CACHE
    ident = P.load_and_identify(rom_path)
    book = NameDictionary(ident)
    want = book.cache_key()
    try:
        got = json.loads(cache_path.read_text(encoding="utf-8"))
        have = "%s:%s:v%s" % (got.get("game_id"), got.get("rom_payload_crc32"), got.get("decoder_version"))
        if have == want:
            return got
    except (OSError, ValueError):
        pass
    data = book.to_cache()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data
