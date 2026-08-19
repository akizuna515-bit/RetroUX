"""背景キャラクタ方式の地図をこしらえる道具（2026-08-02 / マップ指示書 §17）。

## なぜ「遊びながら」ではなく道具なのか

⚠⚠ 1回の採取に CHR 8KB ＋ ネームテーブル 2KB が要ります。
  これを 0.5 秒ごとの受け渡し（`state.json`）へ毎回流すのは重すぎます。
★ 指示書 §17 が挙げている CLI の形にしました。
  **セーブステートを読んで、まとめて素材を作る**流れです。

## 使い方

    # 1. FCEUX でセーブステートから素材を吸い出す（Lua 側）
    tools\\fceux\\fceux64.exe -lua ^
        research\\probes\\active\\bg_capture_probe.lua work\\rom\\DQ2_J.nes

    # 2. 吸い出したものを PNG と辞書にする（この道具）
    .venv\\Scripts\\python.exe -m retroux.tools.dq2_map build-assets

    # 3. 地図DBへ「このマスはこのメタタイル」を書く
    .venv\\Scripts\\python.exe -m retroux.tools.dq2_map link-cells

⚠ 2 と 3 は**利用者のデータを増やす**ので、既定は数えるだけです。
  `--apply` を付けたときだけ書きます。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
PLUGIN_CONFIG = PROJECT_ROOT / "retroux" / "plugins" / "dq2" / "config.yaml"


def default_assets() -> pathlib.Path:
    """素材の置き場所を設定から引く（2026-08-12 / バックログ P0-01）。

    ⚠ ここは `work/map-assets` を直に書いていました。GUI 側が設定を
      読むようにしたので、**同じ場所を見るように**します。片方だけが
      設定に従うと、★作った素材を GUI が見つけられません。

    ⚠ 設定が読めないときは既定へ落とします（★道具が起動しないほうが困る）。
    """
    from retroux.core.bgmap.catalog import DEFAULT_ASSETS_REL, resolve_assets_dir

    try:
        from retroux.core.config.generate_lua import load_yaml

        return resolve_assets_dir(load_yaml(PLUGIN_CONFIG), PROJECT_ROOT)
    except Exception as exc:                           # noqa: BLE001
        _out(f"⚠ 設定を読めないので既定を使います（{exc}）")
        return PROJECT_ROOT / DEFAULT_ASSETS_REL
PALETTE = PROJECT_ROOT / "tools" / "fceux" / "palettes" / "FCEUX.pal"

#: ★ステータス窓は地形ではない。上から何マス行を採るか（2026-08-02 実測）
#: ⚠ 窓は 16px マス行 10 から始まる。
MAP_CELL_ROWS = 10
MAP_CELL_COLS = 16


def _out(text: str = "") -> None:
    print(text)


def _load_palette(path=None):
    from dq2rom.monsters.palette import load_nes_palette

    return load_nes_palette(path or PALETTE)


def build_assets(assets_dir: pathlib.Path, apply: bool) -> int:
    """採取結果から 8×8 と 16×16 と倍率別の PNG を作る（指示書 Phase 4・5）。"""
    from retroux.core.bgmap import (
        Capture, choose_pattern_half, load_screen, metatile_at,
    )
    from retroux.core.bgmap.catalog import AssetStore, SaveResult

    captures = sorted(assets_dir.glob("capture-*.txt"))
    if not captures:
        _out(f"✗ 採取データがありません: {assets_dir}")
        _out("  先に bg_capture_probe.lua を FCEUX で走らせてください。")
        return 1

    palette = _load_palette()
    store = AssetStore(assets_dir)
    if apply:
        store.prepare()

    total = SaveResult()
    for path in captures:
        cap = Capture.load(path)
        # ⚠ FIELD_IDLE 以外は採らない（指示書 §6.2）
        if cap.state != "FIELD_IDLE":
            _out(f"  {path.name}: 状態が {cap.state} なので飛ばします")
            continue
        slot = path.stem.split("-")[1]
        screen_path = assets_dir / f"screen-{slot}.txt"
        # ★どちらの CHR 半分かは画面と照らして決める（Lua から読めない）
        half, rate = 0, None
        if screen_path.exists():
            half, rate, other = choose_pattern_half(
                cap, load_screen(screen_path), palette)
            if rate - other < 0.2:
                _out(f"  ⚠ {path.name}: どちらの CHR 半分か決めきれません"
                     f"（{rate:.1%} vs {other:.1%}）。飛ばします")
                continue

        result = SaveResult()
        for cy in range(MAP_CELL_ROWS):
            for cx in range(MAP_CELL_COLS):
                mt = metatile_at(cap, cx, cy, half)
                if apply:
                    result.merge(store.put_metatile(
                        mt, palette, chr_data=cap.chr_data, half=half))
                elif mt.is_blank:
                    result.skipped_blank += 1
                else:
                    result.metatiles += 1
        rate_text = f" / 再構成 {rate:.1%}" if rate is not None else ""
        _out(f"  {path.name} map ${cap.map_id:02X}{rate_text}: "
             f"メタタイル {result.metatiles} / 再利用 {result.reused} / "
             f"⚠ 黒で見送り {result.skipped_blank}")
        total.merge(result)

    _out()
    _out(f"メタタイル {total.metatiles} / キャラクタ {total.characters} / "
         f"⚠ 黒で見送り {total.skipped_blank}")
    if not apply:
        _out("★数えただけです。作るには --apply を付けてください。")
    return 0


def link_cells(assets_dir: pathlib.Path, apply: bool,
               config_path=None) -> int:
    """採取した場所のマスに「このメタタイル」を結びつける（指示書 §12）。

    ⚠⚠ 書けるのは **FIELD_IDLE で採ったぶんだけ**。
      `Database.record_metatile` が状態を見て弾きます。
    """
    from retroux.core.bgmap import (
        Capture, choose_pattern_half, load_screen, metatile_at,
    )
    from retroux.core.config import user_config as user_config_mod
    from retroux.core.db.database import Database

    captures = sorted(assets_dir.glob("capture-*.txt"))
    if not captures:
        _out(f"✗ 採取データがありません: {assets_dir}")
        return 1

    user_cfg, _warn = user_config_mod.load(config_path)
    db_path = user_cfg.path("db")
    if not db_path.exists():
        _out(f"✗ DB がありません: {db_path}")
        return 1
    _out(f"DB: {db_path}")

    palette = _load_palette()
    db = Database(db_path)
    try:
        roms = db._conn.execute("SELECT rom_hash FROM Rom").fetchall()
        if not roms:
            _out("✗ ROM が登録されていません")
            return 1
        rom_hash = roms[0]["rom_hash"]

        written = skipped = 0
        for path in captures:
            cap = Capture.load(path)
            if cap.state != "FIELD_IDLE":
                continue
            slot = path.stem.split("-")[1]
            screen_path = assets_dir / f"screen-{slot}.txt"
            half = 0
            if screen_path.exists():
                half, _b, _o = choose_pattern_half(
                    cap, load_screen(screen_path), palette)

            # ★画面の中央のマスが主人公の位置（map_x, map_y）
            centre_x, centre_y = MAP_CELL_COLS // 2, 7
            for cy in range(MAP_CELL_ROWS):
                for cx in range(MAP_CELL_COLS):
                    mt = metatile_at(cap, cx, cy, half)
                    # ⚠ 黒は地形にしない（指示書 §11.2）
                    if mt.is_blank:
                        skipped += 1
                        continue
                    x = cap.map_x + (cx - centre_x)
                    y = cap.map_y + (cy - centre_y)
                    if x < 0 or y < 0:
                        continue      # ★枠の外は記録しない
                    if apply:
                        db.record_metatile(rom_hash, cap.map_id, 0, x, y,
                                           mt.key, source_state=cap.state)
                    written += 1
            _out(f"  {path.name} map ${cap.map_id:02X}: {written} マスまで")
        _out()
        _out(f"結びつけ {written} マス / ⚠ 黒で見送り {skipped}")
        if not apply:
            _out("★数えただけです。書くには --apply を付けてください。")
    finally:
        db.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(
        description="背景キャラクタ方式の地図をこしらえる（マップ指示書）")
    parser.add_argument("command",
                        choices=("build-assets", "link-cells"),
                        help="build-assets: PNG と辞書を作る / "
                             "link-cells: マスとメタタイルを結びつける")
    default_dir = default_assets()
    parser.add_argument("--assets", default=None,
                        help=f"素材の置き場所（既定 {default_dir}）")
    parser.add_argument("--apply", action="store_true",
                        help="実際に作る・書く（付けないと数えるだけ）")
    parser.add_argument("--config", default=None, help="user_config.yaml")
    args = parser.parse_args(argv)

    assets = pathlib.Path(args.assets) if args.assets else default_dir
    if args.command == "build-assets":
        return build_assets(assets, args.apply)
    return link_cells(assets, args.apply, args.config)


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
