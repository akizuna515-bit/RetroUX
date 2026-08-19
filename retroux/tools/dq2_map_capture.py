"""実プレイの1地点ぶんを整理して読む（2026-08-02 / 依頼者の指示）。

★★ **狙い** ★★

  ROM 解析だけでは決められない点を、少数の地点で切り分けます:

    ・`$DEDC` の行参照のしかた
    ・ランレングスの進み方
    ・下位5ビットの地形 / 上位3ビットの属性
    ・2×2 象限の選び方

⚠ 全座標の走査はしません。

## 流れ

    1. FCEUX で `map_capture_probe.lua` を走らせ、C キーで地点を採る
       → `work/map-capture/capture-NNN.txt` と `.png`
    2. この道具で `capture_id` ごとのディレクトリへまとめる
       → `work/map-capture/<capture_id>/`

## 使い方

    python -m retroux.tools.dq2_map_capture organize
    python -m retroux.tools.dq2_map_capture show --id 001
    python -m retroux.tools.dq2_map_capture compare
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import shutil
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DIR = PROJECT_ROOT / "work" / "map-capture"
ROM = PROJECT_ROOT / "work" / "rom" / "DQ2_J.nes"


def _out(text: str = "") -> None:
    print(text)


@dataclasses.dataclass
class Capture:
    """1地点ぶん。⚠ 読めなかった項目は None（0 と混ぜない）。"""

    capture_id: str
    values: dict
    cells: dict
    trace: list
    path: pathlib.Path

    @classmethod
    def load(cls, path) -> "Capture":
        path = pathlib.Path(path)
        values, cells, trace = {}, {}, []
        for line in path.read_bytes().decode("utf-8").splitlines():
            if line.startswith("--") or not line.strip():
                continue
            key, _, val = line.partition("=")
            if key == "cell":
                parts = val.split(",")
                if len(parts) == 4:
                    cells[(int(parts[0]), int(parts[1]))] = (parts[2], parts[3])
            elif key == "trace":
                trace.append(val)
            else:
                values[key] = val
        return cls(capture_id=values.get("capture_id", path.stem),
                   values=values, cells=cells, trace=trace, path=path)

    def int_of(self, key: str):
        """⚠ 10進で書いた欄。読めなければ None。"""
        try:
            return int(self.values[key])
        except (KeyError, ValueError):
            return None

    def bytes_of(self, key: str):
        """⚠ 16進の並び。読めなければ None。"""
        raw = self.values.get(key)
        if not raw:
            return None
        try:
            return [int(v, 16) for v in raw.split()]
        except ValueError:
            return None

    @property
    def has_trace(self) -> bool:
        """★トレースが取れたか。⚠ `unavailable` は取れていない。"""
        return bool(self.trace) and self.trace[0] != "unavailable"


def cmd_organize(root: pathlib.Path) -> int:
    """`capture-NNN.*` を `capture_id` ごとのディレクトリへまとめる。"""
    files = sorted(root.glob("capture-*.txt"))
    if not files:
        _out(f"✗ 採取データがありません: {root}")
        _out("  先に FCEUX で map_capture_probe.lua を走らせてください。")
        return 1
    moved = 0
    for path in files:
        cap = Capture.load(path)
        target = root / cap.capture_id
        target.mkdir(parents=True, exist_ok=True)
        for suffix in (".txt", ".png"):
            src = path.with_suffix(suffix)
            if src.exists():
                shutil.move(str(src), str(target / f"capture{suffix}"))
                moved += 1
        _out(f"  {cap.capture_id}: map ${cap.int_of('map_id') or 0:02X} "
             f"({cap.int_of('x')},{cap.int_of('y')}) -> {target.name}/")
    _out(f"\n★{len(files)} 地点 / {moved} ファイルをまとめました")
    _out("⚠ セーブステートは手で置いてください（Lua からは保存できません）:")
    _out(f"   {root}\\<capture_id>\\state.fc?")
    return 0


def _find(root: pathlib.Path, capture_id: str | None):
    """整理前・整理後のどちらでも見つける。"""
    out = []
    for path in sorted(root.glob("*/capture.txt")):
        out.append(path)
    out.extend(sorted(root.glob("capture-*.txt")))
    if capture_id:
        out = [p for p in out if Capture.load(p).capture_id == capture_id]
    return out


def cmd_show(root: pathlib.Path, capture_id: str | None) -> int:
    """1地点の中身を出す。★ROM の値とも突き合わせる。"""
    paths = _find(root, capture_id)
    if not paths:
        _out("✗ 見つかりません")
        return 1
    for path in paths:
        cap = Capture.load(path)
        map_id = cap.int_of("map_id")
        x, y = cap.int_of("x"), cap.int_of("y")
        _out(f"\n=== {cap.capture_id}: map ${map_id:02X} ({x},{y}) ===")
        _out(f"  scroll     ({cap.int_of('scroll_x')},{cap.int_of('scroll_y')})")
        _out(f"  ポインタA  ${cap.int_of('map_ptr_a') or 0:04X}")
        _out(f"  ポインタB  ${cap.int_of('map_ptr_b') or 0:04X}")
        _out(f"  $0C-$13    {cap.values.get('ram_0C_13', '?')}")
        _out(f"  $1F 種別   {cap.values.get('ram_1F', '?')}")
        _out(f"  $20-$27    {cap.values.get('ram_20_27', '?')}")
        _out(f"  バンク     {cap.values.get('prg_bank', '?')}")
        _out(f"  地形ID     {cap.values.get('terrain_id', '?')}")
        # ★主人公のマス（画面中央 (8,7)）の絵
        here = cap.cells.get((8, 7))
        if here:
            _out(f"  ★立っているマスの4枚 {here[0]} / パレット組 {here[1]}")
        _out(f"  トレース   " + ("★あり "
             f"{len(cap.trace)} 行" if cap.has_trace else "⚠ 取れていない"))
        # ⚠ ROM の値と突き合わせる（読めるときだけ）
        if ROM.exists() and map_id is not None:
            _compare_with_rom(cap, map_id, x, y)
    return 0


def _compare_with_rom(cap: Capture, map_id: int, x: int, y: int) -> None:
    """⚠ ROM のヘッダと、実機の `$20`-`$27` が合うか。"""
    from ..core.bgmap.rom_tiles import MAP_HEADER, MAP_HEADER_SIZE, load_prg

    prg = load_prg(ROM)
    off = MAP_HEADER + map_id * MAP_HEADER_SIZE
    rom_header = list(prg[off:off + 8])
    ram_header = cap.bytes_of("ram_20_27")
    if ram_header is None:
        return
    same = rom_header == ram_header
    _out("  ROM ヘッダ " + " ".join(f"{b:02X}" for b in rom_header)
         + ("   ★実機と一致" if same else "   ⚠ 食い違う"))


def cmd_compare(root: pathlib.Path) -> int:
    """採った地点を並べて、切り分けに使う形で出す。

    ★依頼者の狙い（行参照 / ランレングス / ビットの意味 / 象限）に沿って、
      **同じ行・同じ列・偶奇の組**が揃っているかも見ます。
    """
    paths = _find(root, None)
    if not paths:
        _out("✗ 採取データがありません")
        return 1
    caps = [Capture.load(p) for p in paths]
    _out("  id   map   座標    偶奇  地形  立っているマスの4枚  組")
    for cap in caps:
        x, y = cap.int_of("x"), cap.int_of("y")
        here = cap.cells.get((8, 7), ("?", "?"))
        _out(f"  {cap.capture_id}  ${cap.int_of('map_id') or 0:02X}  "
             f"({x:3d},{y:3d})  {x % 2},{y % 2}   "
             f"{cap.values.get('terrain_id', '??')}    {here[0]}         {here[1]}")
    # ★揃い具合を出す（⚠ 足りないものを黙らない）
    _out()
    xs = {(c.int_of("map_id"), c.int_of("y")) for c in caps}
    ys = {(c.int_of("map_id"), c.int_of("x")) for c in caps}
    pars = {(c.int_of("x") % 2, c.int_of("y") % 2) for c in caps
            if c.int_of("x") is not None}
    _out(f"★同じ行（map,y が同じ）の組: {len(caps) - len(xs)} 対")
    _out(f"★同じ列（map,x が同じ）の組: {len(caps) - len(ys)} 対")
    _out(f"★偶奇の組み合わせ: {sorted(pars)}"
         + ("   ★4組そろっています" if len(pars) == 4
            else f"   ⚠ {4 - len(pars)} 組足りません"))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(
        description="実プレイの1地点ぶんを整理して読む")
    parser.add_argument("command", choices=("organize", "show", "compare"))
    parser.add_argument("--dir", default=None)
    parser.add_argument("--id", default=None)
    args = parser.parse_args(argv)

    root = pathlib.Path(args.dir) if args.dir else DEFAULT_DIR
    root.mkdir(parents=True, exist_ok=True)
    if args.command == "organize":
        return cmd_organize(root)
    if args.command == "show":
        return cmd_show(root, args.id)
    return cmd_compare(root)


if __name__ == "__main__":                             # pragma: no cover
    raise SystemExit(main())
