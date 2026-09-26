"""dq3rom のコマンドライン（指示書 §16 / 2026-08-23）。

    python -m dq3rom inspect  --rom work/rom/DQ3_J.nes
    python -m dq3rom enemies  --rom work/rom/DQ3_J.nes [--out output/dq3-analysis]
    python -m dq3rom world    --rom ...   [--scale 2]
    python -m dq3rom areas    --rom ...   [--png] [--scale 4]
    python -m dq3rom world-model --rom ... [--out work/dq3-world-model]

★終了コードは dq2rom と同じ:
    0 成功 / 1 一般エラー / 2 ROM 不一致 / 3 解析形式未対応 / 4 検証不一致

⚠ 生成物は `output/dq3-analysis/`（Git 管理外）。ROM 由来の byte 列はそこだけ。
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys

from dq2rom import EXIT_ERROR, EXIT_OK, EXIT_ROM_MISMATCH, EXIT_VALIDATION_FAILED

from dq2rom.monsters import png

from . import area_maps, enemies
from . import profile as dq3
from . import world_map

DEFAULT_OUT = pathlib.Path("output/dq3-analysis")
#: ⚠ heredoc で潰れるので定数にする（playbook の教訓）
TAB = chr(9)
NEWLINE = chr(10)


def _out(text: str = "") -> None:
    print(text)


def _identify(args) -> tuple[dq3.Identified | None, int]:
    try:
        return dq3.load_and_identify(args.rom), EXIT_OK
    except dq3.UnsupportedRom as exc:
        # ⚠ 「たぶん動く」で進めない（指示書 §2.3）。何が合わなかったかを出す
        print(f"✗ 対応していない ROM: {exc}", file=sys.stderr)
        return None, EXIT_ROM_MISMATCH
    except Exception as exc:                           # noqa: BLE001
        print(f"✗ ROM を読めません: {exc}", file=sys.stderr)
        return None, EXIT_ERROR


def _write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def cmd_inspect(args) -> int:
    ident, code = _identify(args)
    if ident is None:
        return code
    info = dq3.describe(ident)
    _out(json.dumps(info, ensure_ascii=False, indent=2))
    if args.out:
        _write_json(pathlib.Path(args.out) / "rom-info.json", info)
    return EXIT_OK


def cmd_enemies(args) -> int:
    ident, code = _identify(args)
    if ident is None:
        return code
    table = enemies.read_all(ident)
    if not enemies.round_trip_ok(ident, table):
        print("✗ round-trip 不一致（model が byte を落としている）", file=sys.stderr)
        return EXIT_VALIDATION_FAILED

    _out(f"敵 {len(table)} 体 / {len(table) * enemies.ENTRY_SIZE} bytes / round-trip OK")
    _out(f"confidence: {ident.confidence('enemies')}")
    for e in table[:3]:
        _out(f"  #{e.enemy_id:3d} lv{e.level:3d} exp{e.exp:5d} hp_raw{e.hp_raw:3d} mp{e.mp:3d}")

    out = pathlib.Path(args.out) if args.out else None
    if out:
        _write_json(out / "enemies.json", {
            "game_id": ident.game_id,
            "source": {"rom_payload_crc32": ident.rom.prg_crc32,
                       "table": ident.table("enemies")},
            "confidence": ident.confidence("enemies"),
            "_note": "gold/attack/defense/hp は下位 8 bit。+18〜+22 は未確定のため raw",
            "enemies": [e.to_json() for e in table],
        })
        with (out / "enemies.csv").open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerows(enemies.to_csv_rows(table))
        _out(f"→ {out / 'enemies.json'} / {out / 'enemies.csv'}")
    return EXIT_OK


def cmd_names(args) -> int:
    """★名前辞書（RX3-0069）。⚠ 名前は**ユーザーの ROM から**その場で起こす。"""
    from dq3rom import names as N

    ident, code = _identify(args)
    if ident is None:
        return code
    try:
        book = N.NameDictionary(ident)
    except N.NameTableError as exc:
        print("✗ 名前表の構造が期待と違います: %s" % exc, file=sys.stderr)
        return EXIT_VALIDATION_FAILED
    lay = book.layout
    _out("名前辞書 confidence: %s / decoder v%d / cache key %s"
         % (ident.confidence("names"), N.DECODER_VERSION, book.cache_key()))
    _out("  monster %3d 件  bank %d $%04X（id<%d）/ $%04X" % (lay.monster_count, lay.bank, lay.monster_lo, lay.monster_split, lay.monster_hi))
    _out("  item    %3d 件  bank %d $%04X  1 件 %d バイト" % (lay.item_count, lay.bank, lay.item_base, lay.item_width + 2))
    _out("  spell   %3d 件  bank %d $%04X  1 件 %d バイト" % (lay.spell_count, lay.bank, lay.spell_base, lay.spell_width + 2))
    kinds = [args.kind] if args.kind else list(N.KINDS)
    for kind in kinds:
        entries = book.all(kind)
        unknown = [e.entity_id for e in entries if e.unknown_bytes]
        _out("★%s: %d 件 / 復号できないバイトを含む %d 件" % (kind, len(entries), len(unknown)))
        if args.id is not None:
            e = book.resolve(kind, int(args.id))
            _out("  %s %d = %s  raw %s mask %s attr %s @ $%04X" % (
                kind, e.entity_id, e.name, e.raw.hex(" "),
                "-" if e.mask is None else "%02X" % e.mask,
                "-" if e.attr is None else "%02X" % e.attr, e.source_address))
        elif args.show:
            for e in entries:
                _out("  %3d %s" % (e.entity_id, e.name))
    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(book.to_cache(), ensure_ascii=False, indent=1), encoding="utf-8")
        _out("→ %s（⚠ Git の外に置くこと）" % out)
    return EXIT_OK


def cmd_world(args) -> int:
    ident, code = _identify(args)
    if ident is None:
        return code
    out = pathlib.Path(args.out) if args.out else None
    pal = world_map.logical_palette()
    for name, fname in (("world_main", "world-main"),
                        ("world_alefgard", "world-alefgard")):
        try:
            m = world_map.decode(ident, name)
        except world_map.WorldMapError as exc:
            print(f"✗ {name}: {exc}", file=sys.stderr)
            return EXIT_VALIDATION_FAILED
        j = m.to_json()
        _out(f"{name}: {m.width}x{m.height} / 次ポインタ検証 "
             f"{j['rows_verified_by_next_pointer']}/{m.height} / special {j['specials_total']}"
             f" / confidence {ident.confidence(name)}")
        if out:
            _write_json(out / f"{fname}.json", {
                "game_id": ident.game_id, "confidence": ident.confidence(name),
                "source": ident.table(name), **j})
            with (out / f"{fname}.csv").open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(m.tiles)
            # ★仮色の PNG（地形 ID の識別用。実ゲームの色ではない）
            rows = [[(*pal[t], 255) for t in r] for r in m.tiles]     # RGBA
            png.write(out / f"{fname}.png", rows, factor=args.scale)
            _out(f"→ {out / fname}.json / .csv / .png（仮色 ×{args.scale}）")
    return EXIT_OK


def _area_palette() -> dict:
    """エリアマップの仮色（tile 0..31 を識別できる 32 色）。⚠ 実ゲームの色ではない。"""
    pal = {}
    for i in range(32):
        h = (i * 37) % 360
        # 簡易 HSV→RGB（彩度・明度は固定）
        c, x = 200, int(200 * (1 - abs((h / 60) % 2 - 1)))
        r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][h // 60]
        pal[i] = (r + 40, g + 40, b + 40)
    return pal


def cmd_areas(args) -> int:
    ident, code = _identify(args)
    if ident is None:
        return code
    maps = area_maps.decode_all(ident)
    s = area_maps.summary(maps)
    _out(f"decoded = {s['decoded']} / failed = {s['failed']} / unused = {s['unused']}"
         f" / max {s['max_cells']} cells / confidence {ident.confidence('area_directory')}")
    if s["failed"]:
        for m in maps:
            if m.entry.used and not m.ok:
                print(f"  ✗ map {m.entry.map_id}: {m.error}", file=sys.stderr)
    out = pathlib.Path(args.out) if args.out else None
    if out:
        _write_json(out / "area-map-index.json", {
            "game_id": ident.game_id, "confidence": ident.confidence("area_directory"),
            "source": ident.table("area_directory"), "summary": s,
            "_semantics_note": "⚠ background=ヘッダ下位5bit / 第2パス=OR は北米版公開コード由来。実機の見え方は未確認",
            "maps": [m.to_meta() for m in maps],
        })
        pal = _area_palette()
        folder = out / "area-maps"
        folder.mkdir(parents=True, exist_ok=True)
        for m in maps:
            if not m.ok:
                continue
            d = m.decoded
            _write_json(folder / f"map{m.entry.map_id:03d}.json",
                        {"map_id": m.entry.map_id, **d.to_json()})
            if args.png:
                rows = [[(*pal[t], 255) for t in r] for r in d.tiles]
                png.write(folder / f"map{m.entry.map_id:03d}.png", rows, factor=args.scale)
        _out(f"→ {out / 'area-map-index.json'} / {folder}/map*.json"
             + (f" / .png（仮色 ×{args.scale}）" if args.png else ""))
    return EXIT_OK if s["failed"] == 0 else EXIT_VALIDATION_FAILED


def cmd_world_model(args) -> int:
    """World Model を組んで JSON と、実機確認用の TSV を出す。"""
    from . import world_model as wm

    ident, code = _identify(args)
    if ident is None:
        return code
    model = wm.build(ident)
    problems = wm.check(model)
    _out(f"summary: {wm.summary(model)}")
    if problems:
        print(f"✗ 整合性に問題 {len(problems)} 件:", file=sys.stderr)
        for p in problems[:10]:
            print("  " + p, file=sys.stderr)
        return EXIT_VALIDATION_FAILED
    _out("整合性: ★問題なし")

    out = pathlib.Path(args.out)
    _write_json(out / "world-model.json", model)
    # ★実機確認用の TSV（⚠ FCEUX の Lua には JSON パーサが無い）
    lines = ["# map" + TAB + "x" + TAB + "y" + TAB + "kind" + TAB + "value"]
    for o in model["objects"]:
        if o["type"] != "chest" or o["x"] is None:
            continue
        r = o["reward"]
        val = (str(r.get("item_id")) if r["type"] == "item"
               else str(r.get("amount")) if r["type"] == "gold" else "")
        lines.append(TAB.join([str(o["map_id"]), str(o["x"]), str(o["y"]),
                               r["type"], val]))
    (out / "chests.tsv").write_text(NEWLINE.join(lines) + NEWLINE, encoding="utf-8")

    # ★扉も同じ形で出す（依頼者の実機確認: 鍵 3 種 × 扉 3 種）
    dlines = ["# map" + TAB + "x" + TAB + "y" + TAB + "kind" + TAB + "min_rank"]
    for o in model["objects"]:
        if o["type"] != "door":
            continue
        dlines.append(TAB.join([str(o["map_id"]), str(o["x"]), str(o["y"]),
                                o["kind"], str(o["min_key_rank"])]))
    (out / "doors.tsv").write_text(NEWLINE.join(dlines) + NEWLINE, encoding="utf-8")
    _out(f"→ {out / 'world-model.json'} / {out / 'chests.tsv'} / {out / 'doors.tsv'}")
    return EXIT_OK


def cmd_screenshot(args) -> int:
    """セーブステートや probe の書き出しから、実機の画面を PNG に起こす。

    ★★ 行き詰まったら、まずこれ。 ★★
      2026-08-25、Auto 戦闘 v0 が 9,000 フレーム動かない件は、
      ⚠ ログをいくら眺めても分からず、★画面 1 枚で 1 分で分かった。
    """
    from retroux.core.bgmap import savestate as ss

    from . import render

    out = pathlib.Path(args.out)
    made = []
    if args.state:
        state = ss.load(pathlib.Path(args.state))
        px, w, h = render.from_savestate(state, second_screen=args.second)
        made.append(render.write_png(out, px, w, h))
    else:
        text = pathlib.Path(args.dump).read_text(encoding='utf-8')
        snaps = render.parse_probe_dump(text)
        if not snaps:
            print('⚠ 書き出しの中に画面が見つかりません', file=sys.stderr)
            return EXIT_VALIDATION_FAILED
        for i, snap in enumerate(snaps):
            px, w, h = render.render(bytes.fromhex(snap['NT']),
                                     bytes.fromhex(snap['CHR']),
                                     bytes.fromhex(snap['PAL']),
                                     second_screen=args.second)
            name = out if len(snaps) == 1 else out.with_name(
                f'{out.stem}_{i}{out.suffix}')
            made.append(render.write_png(name, px, w, h))
    for m in made:
        _out(f'→ {m}')
    return EXIT_OK

def cmd_text_log(args) -> int:
    """貯めた raw タイルを文字にして出す（★指示書 §7 の「あとから変換」）。"""
    import json as _json

    from retroux.core.text import Charset

    from . import text_log

    profile = _json.loads(
        (pathlib.Path(__file__).parent / "profiles"
         / "dq3_fc_jp_rev0a.json").read_text(encoding="utf-8"))
    charset = Charset(profile.get("text"))
    path = pathlib.Path(args.log)
    if not path.exists():
        print(f"⚠ 記録がありません: {path}", file=sys.stderr)
        return EXIT_VALIDATION_FAILED
    events = text_log.load(path)
    texts = text_log.unique_texts(events, charset)
    _out(f"★イベント {len(events)} 件 / 一意な表示 {len(texts)} 件")
    partial = sum(1 for v in texts.values() if v["conversion_status"] != "complete")
    if partial:
        _out(f"⚠ うち {partial} 件は読めないタイルを含む（★raw は残っています）")
    for v in sorted(texts.values(), key=lambda x: x["first_frame"]):
        _out("")
        _out(f"  [{v['window_id']}] map={v['map_id']} ×{v['count']} "
             f"{v['conversion_status']}")
        for line in v["text"].splitlines():
            if line.strip():
                _out(f"      | {line}")
    if args.out:
        p = pathlib.Path(args.out)
        _write_json(p, texts)
        _out(f"→ {p}")
    return EXIT_OK

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dq3rom", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("inspect", help="iNES 情報・hash・profile の判定を出す")
    p.add_argument("--rom", required=True)
    p.add_argument("--out", default=None, help="rom-info.json の出力先フォルダ")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("enemies", help="敵 139 体を JSON / CSV に出す")
    p.add_argument("--rom", required=True)
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.set_defaults(func=cmd_enemies)

    p = sub.add_parser("names", help="名前辞書（monster / item / spell）を ROM からその場で起こす")
    p.add_argument("--rom", required=True)
    p.add_argument("--kind", choices=["monster", "item", "spell"], default=None)
    p.add_argument("--id", type=int, default=None, help="★1 件だけ見る")
    p.add_argument("--show", action="store_true", help="⚠ 全件を画面に出す（★保存はしない）")
    p.add_argument("--out", default=None, help="cache の JSON を書く先（⚠ work/ 配下に）")
    p.set_defaults(func=cmd_names)

    p = sub.add_parser("world", help="世界地図（メイン / アレフガルド）を JSON / CSV / PNG に出す")
    p.add_argument("--rom", required=True)
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--scale", type=int, default=2, help="PNG の拡大率（既定 2）")
    p.set_defaults(func=cmd_world)

    p = sub.add_parser("areas", help="エリアマップ 243 件の一覧と 204 件の tilemap を出す")
    p.add_argument("--rom", required=True)
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--png", action="store_true", help="仮色の PNG も出す")
    p.add_argument("--scale", type=int, default=4)
    p.set_defaults(func=cmd_areas)

    p = sub.add_parser("world-model", help="World Model を組んで JSON / TSV を出す")
    p.add_argument("--rom", required=True)
    p.add_argument("--out", default="work/dq3-world-model")
    p.set_defaults(func=cmd_world_model)
    p = sub.add_parser("screenshot",
                       help="実機の画面を PNG に起こす（★行き詰まったらまずこれ）")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--state", help="セーブステート（tools/fceux/fcs/*.fc?）")
    g.add_argument("--dump", help="probe が書いた 16 進の並び")
    p.add_argument("--out", default="work/dq3-probe/screen.png")
    p.add_argument("--second", action="store_true",
                   help="⚠ もう 1 面のネームテーブルを描く")
    p.set_defaults(func=cmd_screenshot)

    p = sub.add_parser("text-log",
                       help="貯めた raw タイルを文字にして出す")
    p.add_argument("--log", default="work/dq3-probe/text_events.jsonl")
    p.add_argument("--out", help="一意な表示を JSON で出す")
    p.set_defaults(func=cmd_text_log)

    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)
