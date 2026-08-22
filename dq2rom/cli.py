"""dq2rom のコマンドライン（指示書 §15）。

    python -m dq2rom inspect --rom work/rom/DQ2_J.nes
    python -m dq2rom inspect --rom ... --update-profile
    python -m dq2rom monsters table --rom ...
    python -m dq2rom maps table --rom ...

★終了コードは指示書 §15 のとおり:
    0 成功 / 1 一般エラー / 2 ROM不一致 / 3 解析形式未対応 / 4 検証不一致
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

from . import (
    EXIT_ERROR, EXIT_OK, EXIT_ROM_MISMATCH, EXIT_UNSUPPORTED,
    EXIT_VALIDATION_FAILED,
)
from . import ines, locator
from .rom_profile import Profile, ProfileError

DEFAULT_OUT = pathlib.Path("output/rom-analysis")


def _out(text: str = "") -> None:
    print(text)


def _load_rom(args) -> tuple[ines.Rom, Profile, int]:
    """ROM とプロファイルを読み、照合する。

    戻り値の3つ目は「ハッシュ不一致だが続行してよいか」を表す終了コード候補。
    ★不一致でも**すぐ終わらない**（指示書 2.1）。ヘッダは必ず出す。
    """
    rom = ines.load(args.rom)
    profile = (Profile.load(args.profile) if args.profile
               else Profile.builtin(args.game_id))

    mismatches = profile.hash_mismatches(rom)
    if not mismatches:
        return rom, profile, EXIT_OK

    _out("⚠ ROM のハッシュがプロファイルと一致しません。")
    for m in mismatches:
        _out(f"   - {m}")
    layout = profile.layout_mismatches(rom)
    if layout:
        _out("⚠ 構成も違います:")
        for m in layout:
            _out(f"   - {m}")
    else:
        _out("   構成（mapper / PRG / CHR）は一致しています。別版か改変版の可能性。")
    if not args.force:
        _out("   続けるには --force を付けてください。")
    return rom, profile, EXIT_ROM_MISMATCH


# --- inspect ----------------------------------------------------------


def cmd_inspect(args) -> int:
    rom, profile, status = _load_rom(args)
    if status != EXIT_OK and not args.force:
        return status

    info = ines.describe(rom)
    _out("=== iNES ===")
    _out(f"  ファイル      {info['path']}")
    _out(f"  サイズ        {info['size_bytes']:,} バイト")
    _out(f"  SHA1          {info['hashes']['sha1']}")
    _out(f"  MD5           {info['hashes']['md5']}")
    _out(f"  CRC32         {info['hashes']['crc32']}")
    _out(f"  マッパー      {info['mapper']} ({info['mapper_name']})")
    _out(f"  PRG           {info['prg_banks']} バンク / {info['prg_bytes']:,} バイト")
    _out(f"  CHR           {info['chr_banks']} バンク"
         + ("  ★CHR-RAM（絵は実行時に転送される）" if info["uses_chr_ram"] else ""))
    _out(f"  ミラーリング  {info['mirroring']}")
    _out(f"  固定バンク    {info['fixed_bank']}（$C000-$FFFF）")

    if rom.mapper != ines.MAPPER_UNROM:
        _out()
        _out("⚠ UNROM(2) 以外です。バンク↔オフセットの変換規則が違うため、"
             "この先の位置は当てになりません。")

    _out()
    _out("=== 表の位置（日本版ROM内を探索） ===")
    found: dict[str, locator.Located] = {}
    problems: list[str] = []
    for label, fn, key in (
        ("モンスターの絵の索引表", locator.locate_monster_graphics_table,
         "monster_graphics_pointer_table"),
        ("マップのヘッダ表", locator.locate_map_header_table, "map_header_table"),
    ):
        try:
            got = fn(rom)
        except locator.LocateError as exc:
            _out(f"  ✗ {label}: {exc}")
            problems.append(label)
            continue
        found[key] = got
        _out(f"  ✓ {label}  PRG 0x{got.prg_offset:05X}"
             f"（bank {got.bank} / CPU ${got.cpu_address:04X}）"
             f"  confidence={got.finding.confidence.value}")

    if args.json:
        _out()
        _out(json.dumps(
            {"ines": info,
             "symbols": {k: v.to_json() for k, v in found.items()}},
            ensure_ascii=False, indent=2))

    if args.update_profile:
        for key, got in found.items():
            profile.set_symbol(key, got.to_json())
        if "monster_graphics_pointer_table" in found:
            profile.set_confidence("monster_table", "probable")
        if "map_header_table" in found:
            profile.set_confidence("map_table", "probable")
        try:
            path = profile.save()
        except ProfileError as exc:
            _out(f"✗ プロファイルを保存できません: {exc}")
            return EXIT_ERROR
        _out()
        _out(f"プロファイルを更新しました: {path}")

    if problems:
        return EXIT_UNSUPPORTED
    # ★ここに来るのは「一致した」か「--force で続けると決めた」場合だけ。
    #   どちらも処理としては成功なので 0 を返す（ハッシュ不一致は上で警告済み）。
    return EXIT_OK


# --- monsters table ---------------------------------------------------


def cmd_monsters_table(args) -> int:
    rom, _profile, status = _load_rom(args)
    if status != EXIT_OK and not args.force:
        return status

    try:
        located = locator.locate_monster_graphics_table(rom)
        entries = locator.read_monster_graphics_table(rom, located.prg_offset)
    except locator.LocateError as exc:
        _out(f"✗ {exc}")
        return EXIT_UNSUPPORTED

    problems = locator.verify_monster_graphics_table(entries)

    _out(f"索引表 PRG 0x{located.prg_offset:05X}"
         f"（bank {located.bank} / CPU ${located.cpu_address:04X}）"
         f" / 1体 {locator.MONSTER_GFX_ENTRY_SIZE} バイト"
         f" / {locator.MONSTER_GFX_ENTRIES} エントリ")
    _out(f"ゲームが処理するのは ID $00〜${locator.MONSTER_GFX_MAX_ID:02X}"
         "（コードの `cmp #$53 / bcc` による）")
    _out()

    # ★ID $00 は `$8000` を指す null エントリ。数に入れると1枚多く見える。
    #   84 で数えると 40 枚、null 込みで 39 枚、実体は 38 枚。ここを取り違えない。
    live = [e for e in entries if e.in_range and e.monster_id != 0]
    share: dict[int, list[int]] = collections.defaultdict(list)
    for e in live:
        share[e.graphics_addr].append(e.monster_id)

    _out(f"実体のある敵  {len(live)} 体（ID $01〜${locator.MONSTER_GFX_MAX_ID:02X}"
         " / ID $00 は null エントリなので除外）")
    _out(f"別々の絵      {len(share)} 枚")
    _out(f"別々のパレット {len(set(e.palette_addr for e in live))} 種")
    multi = {k: v for k, v in share.items() if len(v) > 1}
    _out(f"絵を共有する組 {len(multi)} 組  ← ★色違いは絵を共有しパレットだけ違う")
    _out()

    if args.verbose:
        for e in entries:
            mark = "" if e.in_range else "  ← 範囲外（処理されない）"
            gfx_prg = 0x4000 + (e.graphics_addr - 0x8000)
            _out(f"  ID {e.monster_id:02X}  count={e.count:02X}"
                 f"  gfx=${e.graphics_addr:04X}(bank1 PRG 0x{gfx_prg:05X})"
                 f"  pal=${e.palette_addr:04X}{mark}")
        _out()
        _out("--- 絵を共有している組 ---")
        for addr in sorted(multi):
            ids = ",".join(f"{i:02X}" for i in multi[addr])
            _out(f"  ${addr:04X}: {ids}")
        _out()

    if args.json:
        _out(json.dumps({
            "table": located.to_json(),
            "entries": [e.to_json() for e in entries],
            "shared_graphics": {f"0x{k:04X}": v for k, v in sorted(multi.items())},
            "verification_problems": problems,
        }, ensure_ascii=False, indent=2))

    if problems:
        _out("✗ 裏取りに失敗しました（探索に使っていない列がおかしい）:")
        for p in problems:
            _out(f"   - {p}")
        return EXIT_VALIDATION_FAILED
    _out("✓ 裏取り: ポインタ列は筋が通っています"
         "（範囲・重複・単調増加。いずれも探索には使っていない列）")
    return EXIT_OK


# --- maps table -------------------------------------------------------


def cmd_maps_table(args) -> int:
    rom, _profile, status = _load_rom(args)
    if status != EXIT_OK and not args.force:
        return status

    try:
        located = locator.locate_map_header_table(rom)
        headers = locator.read_map_header_table(rom, located.prg_offset)
    except locator.LocateError as exc:
        _out(f"✗ {exc}")
        return EXIT_UNSUPPORTED

    _out(f"ヘッダ表 PRG 0x{located.prg_offset:05X}"
         f"（bank {located.bank} / CPU ${located.cpu_address:04X}）"
         f" / 1マップ {locator.MAP_HEADER_ENTRY_SIZE} バイト"
         f" / {locator.MAP_HEADER_ENTRIES} マップ")
    _out("並び: 境界タイル, 幅, 高さ, ポインタ下位, ポインタ上位, ?, ?, パレット")
    _out("⚠ 6〜7バイト目の意味は**北米版の逆アセンブルでも未解明**です。")
    _out()

    sizes = collections.Counter((h.width, h.height) for h in headers)
    _out(f"幅×高さの種類 {len(sizes)}  最大 {max(h.width for h in headers)}"
         f"×{max(h.height for h in headers)}")
    _out()

    if args.verbose:
        for h in headers:
            _out(f"  map {h.map_id:02X}  {h.width:3d}x{h.height:<3d}"
                 f"  border={h.border_tile:02X}  data=${h.data_addr:04X}"
                 f"  pal={h.palette:02X}  ?={h.unknown_5:02X},{h.unknown_6:02X}")
        _out()

    if args.json:
        _out(json.dumps({
            "table": located.to_json(),
            "maps": [h.to_json() for h in headers],
        }, ensure_ascii=False, indent=2))
    return EXIT_OK


# --- monsters extract -------------------------------------------------


def cmd_monsters_extract(args) -> int:
    from .monsters import extractor
    from .monsters.palette import PaletteError, load_nes_palette

    rom, _profile, status = _load_rom(args)
    if status != EXIT_OK and not args.force:
        return status

    try:
        nes = load_nes_palette(args.palette)
    except PaletteError as exc:
        _out(f"✗ {exc}")
        return EXIT_ERROR
    _out(f"色の表: {nes.source}")

    out_dir = pathlib.Path(args.out or DEFAULT_OUT) / rom.sha1 / "monsters"
    results = extractor.extract(rom, out_dir, nes,
                                scale=args.scale, only=args.id)
    done = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]

    _out(f"出力先: {out_dir}")
    _out(f"  出せた {len(done)} / 失敗 {len(bad)}")
    if args.verbose:
        for r in done:
            n = r.rendered
            _out(f"    ID {r.monster_id:02X}  {n.width}x{n.height}  "
                 f"格子 {n.grid_tiles} / 画素 {n.other_tiles}  "
                 f"confidence={n.confidence.value}")
    for r in bad:
        _out(f"    ✗ ID {r.monster_id:02X}: {r.reason}")

    if done and args.id is None:
        sheet = extractor.contact_sheet(
            results, out_dir.parent / "contact_sheet.png")
        _out(f"  一覧シート: {sheet}")
        groups = extractor.group_by_picture(rom)
        shared = {k: v for k, v in groups.items() if len(v) > 1}
        _out(f"  絵 {len(groups)} 枚 / 色違いで共有している組 {len(shared)}")

    if bad:
        return EXIT_UNSUPPORTED
    return EXIT_OK


# --- monsters install -------------------------------------------------


def cmd_monsters_install(args) -> int:
    """展開した絵を RetroUX が読む場所へ**明示的に**置く。

    ★★ これを `extract` の副作用にしない（Q7=A の決定）。
      解析ツールを走らせただけで本体のデータが書き換わると、
      「図鑑の絵が知らないうちに変わった」が起きる。**別コマンドにする。**

    ⚠ 撮影した絵（`work/monster-art/`）とは**別のフォルダ**に置く。
      混ぜると、どちらが出ているのか分からなくなり、
      照合（`monsters validate`）の材料も壊れる。
    """
    from .monsters import extractor
    from .monsters.palette import PaletteError, load_nes_palette

    rom, _profile, status = _load_rom(args)
    if status != EXIT_OK and not args.force:
        return status

    try:
        nes = load_nes_palette(args.palette)
    except PaletteError as exc:
        _out(f"✗ {exc}")
        return EXIT_ERROR

    into = pathlib.Path(args.into)
    if into.resolve() == pathlib.Path(args.capture).resolve():
        _out(f"✗ 撮影した絵の置き場と同じです: {into}")
        _out("  混ぜると照合の材料が壊れます。別のフォルダにしてください。")
        return EXIT_ERROR

    results = extractor.extract(rom, into, nes, scale=args.scale)
    done = [r for r in results if r.ok]
    bad = [r for r in results if not r.ok]

    # ★RetroUX は `<敵ID2桁16進>.png` で探す。`monster_NNN.png` から作り直す
    renamed = 0
    for r in done:
        target = into / f"{r.monster_id:02X}.png"
        target.write_bytes(r.png_path.read_bytes())
        r.png_path.unlink()
        renamed += 1

    _out(f"置いた場所: {into}")
    _out(f"  絵 {renamed} 枚（`<敵ID2桁16進>.png`）")
    for r in bad:
        _out(f"    ✗ ID {r.monster_id:02X}: {r.reason}")
    _out()
    _out("★RetroUX 側の設定 `monster_art.rom_dir` がこの場所を指していれば、")
    _out("  図鑑と遭遇パネルに出ます（撮影した絵より優先）。")
    return EXIT_UNSUPPORTED if bad else EXIT_OK


# --- monsters validate ------------------------------------------------


def cmd_monsters_validate(args) -> int:
    from .monsters import validator
    from .monsters.decoder import decode_monster

    rom, _profile, status = _load_rom(args)
    if status != EXIT_OK and not args.force:
        return status

    capture = pathlib.Path(args.capture)
    if not capture.is_dir():
        _out(f"✗ 撮影フォルダがありません: {capture}")
        return EXIT_ERROR

    table = locator.locate_monster_graphics_table(rom)
    entries = locator.read_monster_graphics_table(rom, table.prg_offset)
    got = validator.validate_dir(rom.prg, entries, capture, decode_monster)
    if not got:
        _out(f"✗ 照合できる撮影がありません（`<敵ID2桁>.png` という名前）: {capture}")
        return EXIT_ERROR

    _out(f"撮影 {len(got)} 枚と照合（★色ではなくパレット番号で比べる）")
    ok = 0
    for c in got:
        mark = "✓" if c.ok else "✗"
        if c.ok:
            ok += 1
        where = f" 切れ目{c.offset}" if c.offset else ""
        _out(f"  ID {c.monster_id:02X}  {mark} {c.matched}/{c.judged} マス一致 "
             f"({c.rate * 100:5.1f}%)  別レイヤーで除外 {c.skipped}{where} {c.note}")
    _out()
    _out(f"★隠れていないマスが全部一致: {ok} / {len(got)}")
    return EXIT_OK if ok == len(got) else EXIT_VALIDATION_FAILED


# --- maps export ------------------------------------------------------


def cmd_maps_export(args) -> int:
    """マップの大きさなどを RetroUX が読める JSON にする。

    ★★ 出すのは「大きさ・境界タイル・パレット・データ位置」まで ★★
      ⚠ 2026-08-21 訂正（RX-0010）: 以前「地形は日本版では未解読」が理由だったが、
      いまは解読済み（`retroux/core/bgmap/`、2026-08-09 / 08-11）。それでも
      **地形をここに入れない**のは方針: 見せるのは歩いたマスだけ（§2.2）で、
      地形は実行時に ROM から読むので、書き出す必要が無い。
      大きさが分かるだけで「自分が歩いた所だけの地図」を**正しい縮尺で**描ける。
    """
    rom, _profile, status = _load_rom(args)
    if status != EXIT_OK and not args.force:
        return status

    try:
        located = locator.locate_map_header_table(rom)
        headers = locator.read_map_header_table(rom, located.prg_offset)
    except locator.LocateError as exc:
        _out(f"✗ {exc}")
        return EXIT_UNSUPPORTED

    def kind(map_id: int, width: int) -> str:
        # ★`$1F`（map type）の作り方は逆アセンブル bank2.asm:3369 のコメント。
        #   実機のセーブステート4件で一致を確認済み。
        if width == 0xFF:
            return "overworld"
        if map_id < 0x2B:
            return "town"
        if map_id <= 0x43:
            return "dungeon_a"
        return "dungeon_b"

    maps = []
    for h in headers:
        # ★★★ 2026-08-03: **`+1` が要ります。**
        #   ROM のヘッダは `$21`/`$22` に「幅-1 / 高さ-1」を持ちます
        #   （`$DFAE: LDA $21 / STA $0C / INC $0C`）。
        #
        # ⚠⚠ ここが生値のままだったため、**108/109 マップで地図が
        #   1 マス狭く**なっていました。依頼者が実機で
        #   「7×7 マスなのに 144 マス見えている」「下にゴミが出る」と
        #   気づいて分かりました（2026-08-03）。
        #
        # ★`MapHeader.width` は**生値のまま**にしてあります
        #   （ROM の中身をそのまま表す役目なので）。直すのはここだけです。
        maps.append({
            "map_id": h.map_id,
            "type": kind(h.map_id, h.width),
            "width": None if h.width == 0xFF else h.width + 1,
            "height": None if h.height == 0xFF else h.height + 1,
            "border_tile": h.border_tile,
            "palette": h.palette,
            "data_pointer": None if h.data_addr == 0 else f"0x{h.data_addr:04X}",
            "empty": h.data_addr == 0,
        })

    out = pathlib.Path(args.out or DEFAULT_OUT) / rom.sha1
    out.mkdir(parents=True, exist_ok=True)
    path = out / "maps.json"
    path.write_text(json.dumps({
        "schema_version": "1.0",
        "game_id": "dq2_fc_jp",
        "rom_sha1": rom.sha1,
        "table": located.to_json(),
        "confidence": "probable",
        "note": "大きさ・境界タイル・パレット・データ位置まで。"
                "地形は入れない（方針: 実行時に ROM から読む）",
        "maps": maps,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    live = [m for m in maps if not m["empty"] and m["type"] != "overworld"]
    _out(f"書き出した: {path}")
    _out(f"  マップ {len(maps)}（うち中身のあるもの {len(live)}）")
    _out(f"  ★地形は入れていません（実行時に ROM から読む方針）")
    return EXIT_OK


# --- 組み立て ---------------------------------------------------------


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--rom", required=True, help="解析する ROM（iNES）")
    p.add_argument("--profile", help="プロファイル JSON のパス")
    p.add_argument("--game-id", default="dq2_fc_jp", help="内蔵プロファイル名")
    p.add_argument("--force", action="store_true",
                   help="ハッシュが一致しなくても続行する")
    p.add_argument("--json", action="store_true", help="JSON も出す")
    p.add_argument("-v", "--verbose", action="store_true", help="1件ずつ出す")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dq2rom",
        description="FC版ドラゴンクエストII の ROM 解析ツール")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="iNES 情報・ハッシュ・表の位置を出す")
    _add_common(p)
    p.add_argument("--update-profile", action="store_true",
                   help="見つかった位置をプロファイルへ書き戻す")
    p.set_defaults(func=cmd_inspect)

    monsters = sub.add_parser("monsters", help="モンスター関連")
    msub = monsters.add_subparsers(dest="subcommand", required=True)
    p = msub.add_parser("table", help="絵の索引表を読む")
    _add_common(p)
    p.set_defaults(func=cmd_monsters_table)

    p = msub.add_parser("extract", help="絵を展開して PNG と JSON を出す")
    _add_common(p)
    p.add_argument("--out", help=f"出力先の親（既定 {DEFAULT_OUT}）")
    p.add_argument("--palette", help="NES の .pal（既定 tools/fceux/palettes/FCEUX.pal）")
    p.add_argument("--scale", type=int, default=1, help="拡大倍率（最近傍）")
    p.add_argument("--id", type=lambda s: int(s, 0), help="1体だけ出す")
    p.set_defaults(func=cmd_monsters_extract)

    p = msub.add_parser("install", help="展開した絵を RetroUX が読む場所へ置く")
    _add_common(p)
    p.add_argument("--into", default="work/monster-art-rom",
                   help="置き場所（既定 work/monster-art-rom）")
    p.add_argument("--capture", default="work/monster-art",
                   help="撮影した絵の置き場（ここへは置かせない）")
    p.add_argument("--palette", help="NES の .pal")
    p.add_argument("--scale", type=int, default=1, help="拡大倍率（最近傍）")
    p.set_defaults(func=cmd_monsters_install)

    p = msub.add_parser("validate", help="実機で撮った絵と突き合わせる")
    _add_common(p)
    p.add_argument("--capture", default="work/monster-art",
                   help="`<敵ID2桁>.png` が入ったフォルダ")
    p.set_defaults(func=cmd_monsters_validate)

    maps = sub.add_parser("maps", help="マップ関連")
    psub = maps.add_subparsers(dest="subcommand", required=True)
    p = psub.add_parser("table", help="マップのヘッダ表を読む")
    _add_common(p)
    p.set_defaults(func=cmd_maps_table)

    p = psub.add_parser("export", help="マップの大きさ等を JSON にする")
    _add_common(p)
    p.add_argument("--out", help=f"出力先の親（既定 {DEFAULT_OUT}）")
    p.set_defaults(func=cmd_maps_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ines.InesError, ProfileError) as exc:
        _out(f"✗ {exc}")
        return EXIT_ERROR
    except FileNotFoundError as exc:
        _out(f"✗ ファイルがありません: {exc}")
        return EXIT_ERROR
