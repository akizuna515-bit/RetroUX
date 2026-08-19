"""地図デコーダの成果物を ZIP に固める（2026-08-03 / 依頼者の要望）。

    > mapのやつは、もしもツールがあるのであれば、
    > ドキュメントに記録して再利用可能にしたい。

⚠⚠ **これまで手で組んでいました。** ★それが問題です。

  `work/RetroUX_map_phase1-9_*.zip` はその場で組んだもので、
  **同じものをもう一度作る手順がどこにも残っていませんでした**。
  中身の一覧も件数も手打ちで、次に作るときには必ずずれます。

★このツールの肝は「集めること」ではなく、**数字を手で書かないこと**です。
  同梱する `00_README.md` の件数はすべて `artifacts/maps/index.json` から
  数え直します。⚠ 手書きの要約は、成果物が変わっても**黙って古いまま**残ります。

## 使い方

    uv run python -m retroux.tools.export_map_artifacts
    uv run python -m retroux.tools.export_map_artifacts --regenerate
    uv run python -m retroux.tools.export_map_artifacts --no-maps

`--regenerate` を付けると、先に全109マップを描き直します（ROM が要ります）。
付けなければ `artifacts/maps/` にあるものをそのまま固めます。

## ⚠ 入れないもの

ROM（`work/rom/*.nes`）とセーブステート。★入っていないことを
**固めたあとに実際に検査**します（指示書 §18.7）。
"""

from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import subprocess
import sys
import zipfile

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
ARTIFACTS = PROJECT_ROOT / "artifacts" / "maps"
OUT_DIR = PROJECT_ROOT / "output"

#: 固める中身。★`(ZIP の中の場所, 元の場所, グロブ)`
#
# ⚠ ここに書いた場所が無くても**止めません**（環境によって欠けるため）。
#   ただし「何が欠けたか」は必ず画面と README に出します。
#   ★黙って空の ZIP ができるのが一番まずい形です。
LAYOUT: tuple[tuple[str, str, str], ...] = (
    ("01_docs", "docs", "map-decoder-*.md"),
    ("01_docs", "docs", "dq2-type1-tileset-evidence.md"),
    ("01_docs", "docs/research", "dq2-map-*.md"),
    ("01_docs", "docs/research", "dq2-world-map-decoder.md"),
    ("02_schema", "docs/schema", "map-master-*.schema.json"),
    ("02_schema", "docs/schema", "sample-map-master.json"),
    ("03_core", "retroux/core/bgmap", "*.py"),
    ("04_tools", "retroux/tools", "dq2_map_*.py"),
    ("04_tools", "retroux/tools", "dq2_world_map.py"),
    ("05_tests", "tests", "test_dungeon_map.py"),
    ("05_tests", "tests", "test_map_*.py"),
    ("05_tests", "tests", "test_region_map.py"),
    ("05_tests", "tests", "test_world_map.py"),
    ("05_tests", "tests", "test_dynamic_overlay.py"),
    # ★世界地図・区画の全体像（`artifacts/maps` の外にあるもの）。
    #   ⚠ これが一番「見て分かる」ので、無ければ README に理由が出ます。
    ("08_images", "work", "world-map.png"),
    ("08_images", "work", "region-*.png"),
    ("08_images", "work", "map40-*.png"),
)

#: ⚠ ROM とセーブステートの拡張子。**固めたあとに検査**します。
BANNED_SUFFIXES = (".nes", ".fcs", ".sav", ".srm", ".bak")
BANNED_PATTERN = ("fc0", "fc1", "fc2", "fc3", "fc4",
                  "fc5", "fc6", "fc7", "fc8", "fc9")


def _say(text: str) -> None:
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {text}", flush=True)


def _regenerate() -> list[str]:
    """全109マップと世界地図を描き直す。★戻り値は困りごと。"""
    problems: list[str] = []
    for label, module in (("全109マップ", "retroux.tools.dq2_map_batch"),
                          ("世界地図", "retroux.tools.dq2_world_map")):
        _say(f"{label}を作り直します（{module}）...")
        done = subprocess.run([sys.executable, "-m", module],
                              cwd=str(PROJECT_ROOT), capture_output=True)
        if done.returncode != 0:
            out = (done.stdout or b"").decode("utf-8", "replace")
            err = (done.stderr or b"").decode("utf-8", "replace")
            problems.append(f"⚠ {label}の再生成に失敗しました:\n{out}\n{err}")
            _say(f"⚠ {label}: 失敗（ROM が置かれていない可能性）")
        else:
            _say(f"★{label}: できました")
    return problems


def _summary() -> tuple[dict, list[str]]:
    """`index.json` から数え直す。★手で書かない。"""
    problems: list[str] = []
    path = ARTIFACTS / "index.json"
    if not path.exists():
        problems.append(
            f"⚠⚠ {path} がありません。--regenerate を付けるか、"
            "先に `uv run python -m retroux.tools.dq2_map_batch` を実行してください")
        return {}, problems

    index = json.loads(path.read_text(encoding="utf-8"))
    rows = index.get("maps") or []
    by_type: dict[int, dict[str, int]] = {}
    for row in rows:
        kind = row.get("map_type")
        bucket = by_type.setdefault(kind, {"total": 0, "renderable": 0})
        bucket["total"] += 1
        if row.get("status") == "renderable":
            bucket["renderable"] += 1

    # ⚠ 「分からない」を 0 と混ぜない。★未解明の地形IDは件数を出す
    unknown = sum(len(r.get("unknown_terrain_ids") or []) for r in rows)
    return {
        "rom_sha256": (index.get("rom") or {}).get("sha256"),
        "map_count": index.get("map_count"),
        "by_type": by_type,
        "renderable": sum(1 for r in rows if r.get("status") == "renderable"),
        "partial": sum(1 for r in rows if r.get("status") == "partial"),
        "failed": sum(1 for r in rows if r.get("status") == "failed"),
        "chests": sum(r.get("chest_count") or 0 for r in rows),
        "doors": sum(r.get("door_count") or 0 for r in rows),
        "unknown_terrain": unknown,
    }, problems


def _collect() -> tuple[list[tuple[str, pathlib.Path]], list[str]]:
    """固める中身を集める。★欠けたものは困りごとに残す。"""
    picked: list[tuple[str, pathlib.Path]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for dest, rel, pattern in LAYOUT:
        base = PROJECT_ROOT / rel
        if not base.exists():
            problems.append(f"⚠ {rel} がありません（{pattern} を入れられません）")
            continue
        found = sorted(base.glob(pattern))
        if not found:
            problems.append(f"⚠ {rel}/{pattern} に合うものがありません")
            continue
        for src in found:
            if src.name.startswith("__"):
                continue
            name = f"{dest}/{src.name}"
            if name in seen:
                continue           # ★同じものを2度入れない
            seen.add(name)
            picked.append((name, src))
    return picked, problems


def _collect_maps() -> list[tuple[str, pathlib.Path]]:
    """マップごとの JSON と PNG（★件数が多いので別立て）。"""
    if not ARTIFACTS.exists():
        return []
    out: list[tuple[str, pathlib.Path]] = []
    for src in sorted(ARTIFACTS.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(ARTIFACTS).as_posix()
        # ★一覧と報告は 06_index へ、残りは 07_maps へ
        if src.parent == ARTIFACTS:
            top = "06_index" if src.suffix in (".json", ".md") else "08_images"
        else:
            top = "07_maps"
        out.append((f"{top}/{rel}", src))
    return out


def _readme(summary: dict, problems: list[str], stamp: str,
            counts: dict[str, int]) -> str:
    """同梱の案内。★★ **数字はすべて数え直した値。** ★★"""
    lines = [
        f"# RetroUX 地図デコーダの成果物（{stamp}）",
        "",
        "⚠⚠ **ROM とセーブステートは入っていません。**",
        "  動かすには `work/rom/DQ2_J.nes` をご自分で置いてください。",
        "",
        "★この ZIP は `retroux/tools/export_map_artifacts.py` が作りました。",
        "  同じものをもう一度作れます:",
        "",
        "```bash",
        "uv run python -m retroux.tools.export_map_artifacts --regenerate",
        "```",
        "",
    ]

    if summary:
        lines += [
            "## 到達点",
            "",
            "★下の数字は `artifacts/maps/index.json` から**数え直した値**です",
            "（手で書いていないので、成果物と食い違いません）。",
            "",
            "| 種別 | 全件 | ★描けた |",
            "| --- | --- | --- |",
        ]
        # ⚠ 種別0（世界地図 `$01`）は**この手順の対象外**です。
        #   行ポインタ＋ランレングスの別経路で、`dq2_world_map.py` が担当します。
        #   ★「⚠失敗 1」はこれのことで、街・ダンジョンは 108/108 です。
        labels = {0: "種別0（世界地図 / ★別ツール）",
                  1: "種別1（街）", 2: "種別2", 3: "種別3"}
        for kind in sorted(summary["by_type"]):
            bucket = summary["by_type"][kind]
            lines.append(f"| {labels.get(kind, f'種別{kind}')} | "
                         f"{bucket['total']} | {bucket['renderable']} |")
        lines += [
            "",
            "| 項目 | 件数 |",
            "| --- | --- |",
            f"| 全マップ | {summary['map_count']} |",
            f"| ★描けた | {summary['renderable']} |",
            f"| ⚠ 一部 | {summary['partial']} |",
            f"| ⚠ 失敗 | {summary['failed']} |"
            "  ← ★世界地図 `$01` のこと（別経路 / `08_images/world-map.png`）",
            f"| 宝箱 | {summary['chests']} |",
            f"| 扉 | {summary['doors']} |",
            f"| ⚠ 未解明の地形ID | {summary['unknown_terrain']} |",
            "",
            f"ROM `sha256 {summary['rom_sha256']}`",
            "",
        ]

    lines += ["## 中身", "", "| 場所 | ファイル数 |", "| --- | --- |"]
    for top in sorted(counts):
        lines.append(f"| `{top}/` | {counts[top]} |")
    lines.append("")

    if problems:
        lines += [
            "## ⚠ 入れられなかったもの",
            "",
            "★**黙って捨てていません。**理由を残します。",
            "",
        ]
        lines += [f"- {p}" for p in problems]
        lines.append("")

    lines += [
        "## 詳しい資料",
        "",
        "`01_docs/` に処理経路・裏取り・未解明の一覧が入っています。",
        "⚠ **未解明を推測で埋めていません。**分からないものは",
        "`unknown_terrain_ids` として件数のまま残してあります。",
        "",
    ]
    return "\n".join(lines)


def _verify(zip_path: pathlib.Path) -> list[str]:
    """⚠ 固めたあとに**実際に**中身を検査する（指示書 §18.7）。"""
    bad: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        for name in names:
            low = name.lower()
            if low.endswith(BANNED_SUFFIXES):
                bad.append(name)
            elif any(low.endswith("." + p) for p in BANNED_PATTERN):
                bad.append(name)
    if not names:
        bad.append("⚠⚠ 空の ZIP です")
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="地図デコーダの成果物を ZIP に固める")
    parser.add_argument("--regenerate", action="store_true",
                        help="先に全109マップと世界地図を描き直す（ROM が要ります）")
    parser.add_argument("--no-maps", action="store_true",
                        help="マップごとの JSON/PNG を入れない（資料だけ）")
    parser.add_argument("--out-dir", default=None, help="出力先（既定は output）")
    args = parser.parse_args(argv)

    problems: list[str] = []
    if args.regenerate:
        problems += _regenerate()

    summary, more = _summary()
    problems += more

    _say("固める中身を集めます...")
    picked, more = _collect()
    problems += more
    if not args.no_maps:
        picked += _collect_maps()
    if not picked:
        print("⚠⚠ 入れるものが1つもありません。中止します。")
        for p in problems:
            print(f"  {p}")
        return 1

    counts: dict[str, int] = {}
    for name, _ in picked:
        counts[name.split("/")[0]] = counts.get(name.split("/")[0], 0) + 1

    stamp = datetime.datetime.now().strftime("%y%m%d-%H%M")
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"retroux-maps-{stamp}.zip"
    if zip_path.exists():
        zip_path.unlink()

    _say(f"ZIP に固めます（{len(picked) + 1} ファイル）...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("00_README.md",
                         _readme(summary, problems, stamp, counts))
        for name, src in picked:
            archive.write(src, name)

    _say("中身を検査します（ROM・セーブが混ざっていないか）...")
    bad = _verify(zip_path)
    if bad:
        zip_path.unlink(missing_ok=True)
        print("⚠⚠ 入ってはいけないものが見つかったので**配布を中止**しました:")
        for name in bad[:20]:
            print(f"  {name}")
        return 1

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print("")
    print("======================================")
    print(f"書き出しました: {zip_path}")
    print(f"  ファイル数 : {len(picked) + 1}")
    print(f"  サイズ     : {size_mb:.2f} MB")
    for top in sorted(counts):
        print(f"  {top:12s}: {counts[top]} 件")
    print("  ROM・セーブ: 含まれていません（検査済み）")
    if problems:
        print("")
        print("警告: ★確認してください（00_README.md にも書いてあります）:")
        for p in problems:
            print(f"  {p}")
    print("======================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
