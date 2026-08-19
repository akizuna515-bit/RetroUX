"""キャラクタ辞書とメタタイル辞書（2026-08-02 / マップ指示書 Phase 5）。

## 置き場所（指示書 §7.4）

    work/map-assets/
      raw_chr/<chr_hash>.bin              ★正本。CHR 16 バイトそのもの
      palettes/<palette_hash>.json        背景パレット
      characters/<character_key>.png      8×8
      characters/<character_key>.json     素性
      metatiles/<metatile_key>/           16×16 と倍率別
        1x.png  half.png  2x.png  4x.png
        meta.json
      reports/

★★ **画像は毎回作り直さない**（指示書 §10.3）★★
  1倍を正本にし、倍率別は**初回に作って置いておく**。
  ⚠ 表示のたびに拡大縮小しない。

★★ **黒観測は地形として保存しない**（指示書 §11.2）★★
  4枚とも地の色のメタタイルは、**新規に保存せず、既存も上書きしない**。
  ⚠ ただし「無視した」ことは記録に残す（黙って捨てない）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib

from .characters import SCALES, Character, Metatile, scale_nearest, write_png

#: ⚠ 鍵はファイル名になる。`:` は Windows で使えないので置き換える
_KEY_SAFE = str.maketrans({":": "_", "/": "_", "\\": "_"})


def safe_name(key: str) -> str:
    """鍵をファイル名にする。★元の鍵は json に残すので情報は失わない。"""
    return key.translate(_KEY_SAFE)


#: 素材の既定の置き場所。★採取（`bg_capture_probe.lua`）もここへ書く。
DEFAULT_ASSETS_REL = "work/map-assets"


def resolve_assets_dir(config, project_root) -> pathlib.Path:
    """素材の置き場所を設定から引く（2026-08-12 / バックログ P0-01）。

    ⚠⚠ **設定しても効かない状態でした。**
      `gui.py` は `map.assets_dir` を読んでいたのに、`config.yaml` に
      あるのは `map.rendering.assets_path` です。★落ちはしませんが、
      **書いた値が黙って無視されて**既定へ落ちていました
      （`docs/project/RETROUX_BACKLOG.md` の P0-01）。

    ★鍵の名前をここ1か所に閉じ込めます。読む側が増えても同じ場所を見ます。

    ⚠ 古い名前（`map.assets_dir`）も読みます。書いてある設定を
      **こちらの都合で無効にしない**ためです（★新しい名前を優先）。

    ⚠⚠ **採取と組み立ての側は別**です。`bg_capture_probe.lua` は
      `work/map-assets` へ書き、`scripts/build-map-assets.ps1` もそこを見ます。
      ★既定から変えるなら、素材を作り直すか、作った物を移してください。
      （`retroux.tools.dq2_map --assets <path>` で置き場所を渡せます）
    """
    m = (config or {}).get("map") or {}
    rendering = m.get("rendering") or {}
    rel = rendering.get("assets_path") or m.get("assets_dir")
    return pathlib.Path(project_root) / str(rel or DEFAULT_ASSETS_REL)


@dataclasses.dataclass
class SaveResult:
    """何を保存し、何を見送ったか。★黙って捨てない（指示書 §11.2）。"""

    characters: int = 0
    metatiles: int = 0
    #: 4枚とも地の色だったので保存しなかった数
    skipped_blank: int = 0
    #: すでにあったので作り直さなかった数
    reused: int = 0

    def merge(self, other: "SaveResult") -> None:
        self.characters += other.characters
        self.metatiles += other.metatiles
        self.skipped_blank += other.skipped_blank
        self.reused += other.reused


class AssetStore:
    """採取した背景を貯める場所。"""

    def __init__(self, root) -> None:
        self.root = pathlib.Path(root)
        self.raw_chr = self.root / "raw_chr"
        self.palettes = self.root / "palettes"
        self.characters = self.root / "characters"
        self.metatiles = self.root / "metatiles"
        self.reports = self.root / "reports"

    def prepare(self) -> None:
        for d in (self.raw_chr, self.palettes, self.characters,
                  self.metatiles, self.reports):
            d.mkdir(parents=True, exist_ok=True)

    # --- CHR の正本 ----------------------------------------------------

    def put_raw_chr(self, chr_hash: str, data: bytes) -> pathlib.Path:
        """CHR 16 バイトをそのまま置く（指示書 §7.4「正本」）。

        ★PNG は表示用。**元のバイトを残す**ので後から作り直せる。
        """
        # ⚠ `prepare()` を呼ばずに使われることがある。★ここでも作る
        self.raw_chr.mkdir(parents=True, exist_ok=True)
        # ⚠ ハッシュもファイル名になる。`:` が混ざると Windows で書けない
        #   （2026-08-02 に実際に FileNotFoundError が出た）
        path = self.raw_chr / f"{safe_name(chr_hash)}.bin"
        if not path.exists():
            path.write_bytes(data)
        return path

    def put_palette(self, colors) -> str:
        """背景パレットを置き、そのハッシュを返す。"""
        payload = json.dumps({"colors": list(colors)}, ensure_ascii=False)
        digest = hashlib.sha1(payload.encode()).hexdigest()[:12]
        path = self.palettes / f"{digest}.json"
        if not path.exists():
            path.write_text(payload, encoding="utf-8")
        return digest

    # --- 8×8 キャラクタ -------------------------------------------------

    def put_character(self, ch: Character, nes_palette,
                      chr_bytes: bytes | None = None) -> bool:
        """8×8 を1枚置く。★既にあれば作り直さない。

        戻り値は「新しく作ったか」。
        """
        name = safe_name(ch.key)
        png_path = self.characters / f"{name}.png"
        json_path = self.characters / f"{name}.json"
        if png_path.exists() and json_path.exists():
            return False
        if chr_bytes is not None:
            self.put_raw_chr(ch.chr_hash, chr_bytes)
        write_png(ch.rgba(nes_palette), png_path)
        json_path.write_text(json.dumps({
            "character_key": ch.key,
            "tile_id": ch.tile_id,
            "chr_hash": ch.chr_hash,
            "palette_signature": ch.palette_signature,
            "colors": list(ch.colors),
            # ★0..3 の番号も残す。⚠ パレットを変えて作り直せるように
            "pattern": [list(row) for row in ch.pattern],
            "is_blank": ch.is_blank,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return True

    # --- 16×16 メタタイル -----------------------------------------------

    def metatile_dir(self, key: str) -> pathlib.Path:
        return self.metatiles / safe_name(key)

    def has_metatile(self, key: str) -> bool:
        """★倍率が全部そろっているか。1枚でも欠けたら作り直す。"""
        d = self.metatile_dir(key)
        return (d / "meta.json").exists() and all(
            (d / f"{name}.png").exists() for name in SCALES)

    def put_metatile(self, mt: Metatile, nes_palette,
                     chr_data: bytes | None = None,
                     half: int = 0) -> SaveResult:
        """16×16 と倍率別を置く（指示書 §10.3）。

        ⚠⚠ **4枚とも地の色なら保存しない**（指示書 §11.2）。
          ★「マップ切替中」「暗転中」「未描画」で出てくるものなので、
            地形として残すと既存の床や壁を塗りつぶしてしまう。

        ★`chr_data` を渡すと **CHR の生バイトも残す**（指示書 §7.4「正本」）。
          ⚠ 渡さないと PNG しか残らず、後からパレットを変えて
            作り直すことができない。
        """
        result = SaveResult()
        if mt.is_blank:
            result.skipped_blank = 1
            return result
        if self.has_metatile(mt.key):
            result.reused = 1
            return result

        d = self.metatile_dir(mt.key)
        d.mkdir(parents=True, exist_ok=True)
        base = mt.rgba(nes_palette)
        # ★1倍を正本にして、そこから拡大縮小する（指示書 §10.2）
        for name, factor in SCALES.items():
            write_png(scale_nearest(base, factor), d / f"{name}.png")
        (d / "meta.json").write_text(json.dumps({
            "metatile_key": mt.key,
            "characters": {
                "top_left": mt.top_left.key,
                "top_right": mt.top_right.key,
                "bottom_left": mt.bottom_left.key,
                "bottom_right": mt.bottom_right.key,
            },
            "source": {"map_id": mt.map_id, "x": mt.x, "y": mt.y},
        }, ensure_ascii=False, indent=1), encoding="utf-8")

        result.metatiles = 1
        for ch in mt.characters:
            raw = None
            if chr_data is not None:
                base = half + ch.tile_id * 16
                raw = chr_data[base:base + 16]
            if self.put_character(ch, nes_palette, raw):
                result.characters += 1
        return result

    # --- 読み出し -------------------------------------------------------

    def image_path(self, key: str, scale: str = "1x") -> pathlib.Path | None:
        """描画に使う PNG。⚠ 無ければ None（作らない）。"""
        if scale not in SCALES:
            return None
        path = self.metatile_dir(key) / f"{scale}.png"
        return path if path.exists() else None

    def read_metatile(self, key: str) -> dict | None:
        path = self.metatile_dir(key) / "meta.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def pick_scale(zoom: float) -> str:
    """倍率の名前を選ぶ。⚠ 任意の小数倍率は作らない（指示書 §10.4）。"""
    best, diff = "1x", None
    for name, factor in SCALES.items():
        d = abs(factor - zoom)
        if diff is None or d < diff:
            best, diff = name, d
    return best


def auto_scale(cols: int, rows: int, width: int, height: int) -> str:
    """「自動」= 窓に収まる**定義済みの**最大倍率（指示書 §10.4）。

    ⚠ 収まらないときは一番小さい 0.5 倍にする（勝手に小数を作らない）。
    """
    if cols <= 0 or rows <= 0:
        return "1x"
    ordered = sorted(SCALES.items(), key=lambda kv: kv[1], reverse=True)
    for name, factor in ordered:
        cell = 16 * factor
        if cols * cell <= width and rows * cell <= height:
            return name
    return min(SCALES.items(), key=lambda kv: kv[1])[0]
