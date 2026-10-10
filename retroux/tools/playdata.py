"""遊んだ記録を退避して、まっさらから始める（2026-08-03 / 依頼者の要望）。

    もうダンジョンが残りすくないので、次、ガンガンいこうぜを実装した
    ところで最初からやってみます。まずは、データバックアップ＆クリアの
    仕組みを作って。

★★★ **利用者のデータを消すので、明示的に実行したときだけ動きます。** ★★★
  ⚠ 既定は**数えるだけ**。消すには `--apply` が要ります。
  ⚠⚠ `clear` は**必ず先に退避してから**消します。

## ★ 消すもの / ⚠ 絶対に消さないもの

| 区分 | 中身 | 扱い |
| --- | --- | --- |
| ★遊んだ記録 | DB の訪問マス・戦闘・遭遇・遷移・メモ | ★退避して消す |
| ★遊んだ記録 | `events.jsonl` / `runtime/dq2-log/retroux.log` | ★退避して消す |
| ★作り直せる | `work/map-assets`（地図の素材） | ★退避して消す |
| ⚠⚠ **絶対に消さない** | `work/rom/`（ROM） | ⚠ **触らない** |
| ⚠⚠ **絶対に消さない** | `tools/fceux/fcs/`（**セーブステートの本物**） | ⚠ **触らない** |
| ⚠⚠ **絶対に消さない** | `work/savestate-backup/`（同・10 世代の控え） | ⚠ **触らない** |
| ⚠⚠ **絶対に消さない** | `work/map-capture/`（解析の採取） | ⚠ **触らない** |
| ⚠⚠ **絶対に消さない** | `work/tests/evidence` / `work/research/dq2-disasm`（★RX3-0494 / 0495 で移動。⚠ 直下には無いので消す対象にもならない） | ⚠ **触らない** |
| ★残す | DB の `Rom` テーブル（ROM の登録） | ★消さない |

## ⚠⚠ セーブステートは 2 か所にあります

| どれ | 場所 |
| --- | --- |
| ★**本物**（ゲームが読み書きする） | `tools/fceux/fcs/` の `DQ2_J-bak.fc0` 〜 `.fc9` |
| ★控え（10 世代） | `work/savestate-backup/` |

⚠ **どちらもここでは消しません。**「最初からやる」のはゲーム側の話で、
  ここが消すのは **RetroUX が貯めた記録**だけです。

★最初からやり直すときは、**`tools/fceux/fcs/` の `.fc*` を手で**
  消して（またはリネームして）ください。
  ⚠ 間違えると取り返しがつかないので、道具にはさせていません。
  ★消しても控えが 10 世代残っています。

## 使い方

```
# ★いま何があるか見る（★何も変えない）
.venv\\Scripts\\python.exe -m retroux.tools.playdata status

# ★退避する（★消さない）
.venv\\Scripts\\python.exe -m retroux.tools.playdata backup --apply

# ★退避してから消す（★まっさらにする）
.venv\\Scripts\\python.exe -m retroux.tools.playdata clear --apply

# 退避の一覧
.venv\\Scripts\\python.exe -m retroux.tools.playdata list

# 戻す
.venv\\Scripts\\python.exe -m retroux.tools.playdata restore 20260803-0930 --apply
```

★`--apply` を付けないと**何も変わりません**（数えて見せるだけ）。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import shutil
import sqlite3
import sys

from ..core import dq2_paths

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORK = PROJECT_ROOT / "work"
#: ★write_root 側の work/（★Lua が書く events.jsonl と DQ2 のログ / RX-0162）
WRITE_WORK = dq2_paths.work()

#: ★退避の置き場所
VAULT = WORK / "playdata-archive"

#: ★遊んだ記録が入っている DB
DB_PATH = WORK / "retroux.sqlite3"

#: ★遊ぶと増えるファイル（★退避して消す）
# ⚠⚠ **`encountered.txt` / `caution.txt` を入れ忘れていました**
#   （2026-08-08 に実際に踏んだ）。★「もう会った敵」の控えです。
#   残ったままだと、まっさらから始めたのに:
#     ⚠ 初遭遇の安全機構（等速＋手動）が**一度も働かない**
#     ⚠ 図鑑の「初」印が出ない
#     ⚠ 警戒リストが、まだ会っていない敵に効く
#   ★DB の `EncounteredMonster` は消していたので、**食い違って**いました。
# ★DQ2 のログは runtime/dq2-log/ の中（RX-0149）。⚠ 旧 `work/retroux.log` は DQ3 の控えも書くので触らない
PLAY_FILES = ("events.jsonl", "runtime/dq2-log/retroux.log", "command.json",
              "state.json", "encountered.txt", "caution.txt")
#: ★PLAY_FILES のうち write_root 側にあるもの（★Lua の書き先 / RX-0162）。他は program_root 側
WRITE_ROOT_FILES = ("events.jsonl", "runtime/dq2-log/retroux.log")


def play_file(name: str) -> pathlib.Path:
    """★遊んだ記録のファイルの場所（★events とログは write_root、他は program_root）。"""
    return (WRITE_WORK if name in WRITE_ROOT_FILES else WORK) / name

#: ★作り直せるディレクトリ（★退避して消す）
# ⚠⚠ **`generated` は消したあと必ず作り直します**（2026-08-08 に踏んだ）。
#   ★`memory_map.lua` / `config.lua` は FCEUX 側の Lua が**必ず読む**もので、
#     無いと**起動できません**。⚠ 「作り直せる」と「作り直した」は別です。
DERIVED_DIRS = ("map-assets", "generated")

#: ⚠⚠ **DQ3 のもの**（★退避・消去・戻すのどれでも触らない / RX-0148）。
#   `work/generated/` は DQ2 と DQ3 の共用フォルダで、DQ3 の生成物（`dq3_*.lua` / `dq3-names.json`）もある。
#   ⚠ 以前はフォルダを丸ごと消して DQ2 の分だけ作り直していた → DQ3 の生成物が消えた（調査 D6）。
#   ★名前で除く（⚠ DQ2 の分を名前で並べると、増えたときに漏れる / 見張る対象の足し忘れ）。
FOREIGN_PREFIXES = ("dq3_", "dq3-")


def is_foreign(name: str) -> bool:
    """★DQ3 のもの（DQ2 の playdata が触らない）か。"""
    return name.casefold().startswith(FOREIGN_PREFIXES)


def _ignore_foreign(_dir, names) -> set:
    """`shutil.copytree` の ignore（★DQ3 のものを写さない）。"""
    return {n for n in names if is_foreign(n)}


def _remove_owned(path: pathlib.Path) -> None:
    """★DQ2 のものだけ消す。⚠ DQ3 のものは残し、空になったときだけフォルダも消す。"""
    for child in path.iterdir():
        if is_foreign(child.name):
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    if not any(path.iterdir()):
        path.rmdir()

#: ⚠⚠ **絶対に触らないもの**（★消す対象に入っていないことを試験で見張る）
NEVER_TOUCH = ("rom", "savestate-backup", "savestate_backup",
               "map-capture", "map-data", "evidence", "dq2-disasm",
               "playdata-archive")

#: ★DB のうち「遊んだ記録」のテーブル（★消す）
PLAY_TABLES = ("VisitedTile", "BattleEvent", "BattleLog",
               "EncounteredMonster", "MapTransition", "MapEdge",
               "MapBlockedDirection", "MapLandmark", "MapNote",
               "NavigationSession", "IngestState")

#: ⚠ DB のうち**残す**テーブル
KEEP_TABLES = ("Rom", "MapOverride", "sqlite_sequence")


def _out(text: str = "") -> None:
    print(text)


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M")


def _size(path: pathlib.Path) -> int:
    """★中身の合計バイト数。⚠ 無ければ 0。★DQ3 のもの（`is_foreign`）は数えない。"""
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*")
               if p.is_file() and not any(is_foreign(part) for part in p.relative_to(path).parts))


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size / 1:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


# --- ★ いま何があるか -----------------------------------------------------

def table_counts(db_path: pathlib.Path) -> dict:
    """★テーブルごとの行数。⚠ 読めなければ空。"""
    if not db_path.exists():
        return {}
    out = {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for name in names:
            try:
                out[name] = conn.execute(
                    f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except sqlite3.Error:
                out[name] = None          # ⚠ 読めなかった（0 と混ぜない）
    finally:
        conn.close()
    return out


def survey() -> dict:
    """★消す対象と、消さないものを数える。**何も変えません**。"""
    counts = table_counts(DB_PATH)
    play_rows = {t: counts.get(t) for t in PLAY_TABLES if t in counts}
    return {
        "db": {"path": DB_PATH, "exists": DB_PATH.exists(),
               "size": _size(DB_PATH), "rows": play_rows,
               "keep": {t: counts.get(t) for t in KEEP_TABLES if t in counts}},
        "files": [(n, play_file(n), _size(play_file(n))) for n in PLAY_FILES],
        "dirs": [(n, WORK / n, _size(WORK / n)) for n in DERIVED_DIRS],
        "never": [(n, WORK / n, _size(WORK / n)) for n in NEVER_TOUCH
                  if (WORK / n).exists()],
    }


def cmd_status() -> int:
    """★いま何があるか。⚠ 何も変えません。"""
    info = survey()
    _out("=== ★遊んだ記録（clear で消えるもの）===")
    if not info["db"]["exists"]:
        _out(f"  ⚠ DB がありません: {DB_PATH}")
    else:
        _out(f"  {DB_PATH.name}  {_human(info['db']['size'])}")
        for table, rows in info["db"]["rows"].items():
            mark = "★" if rows else "  "
            _out(f"    {mark} {table:24s} {rows if rows is not None else '⚠ 読めない':>8}")
    for name, path, size in info["files"] + info["dirs"]:
        state = f"{_human(size):>9}" if path.exists() else "   ⚠ 無し"
        _out(f"  {name:24s} {state}")

    _out("\n=== ⚠⚠ 触らないもの（★clear でも残ります）===")
    for name, _path, size in info["never"]:
        _out(f"  {name:24s} {_human(size):>9}")
    _out("\n=== ★DB で残すテーブル ===")
    for table, rows in info["db"].get("keep", {}).items():
        _out(f"  {table:24s} {rows if rows is not None else '?':>8}")
    return 0


# --- ★ 退避 ---------------------------------------------------------------

def _new_target(label: str | None = None) -> pathlib.Path:
    """★退避先（⚠ 同じ分に 2 回押しても重ねて書かない / RX-0174）。

    ⚠ 以前は `dirs_exist_ok` で**同じフォルダへ重ねて**写していた（★名前が分まで）。
      → ★既にあれば `-2` `-3` … を足す（⚠ 名前の形は今までと同じなので、一覧・戻すは変わらない）。
    """
    base = _stamp() + (f"-{label}" if label else "")
    target = VAULT / base
    n = 2
    while target.exists():
        target = VAULT / f"{base}-{n}"
        n += 1
    return target


def backup(label: str | None = None) -> dict:
    """★退避して結果を返す（★画面とコマンドの両方から使う / RX-0174）。⚠ **何も消しません**。

    戻り値: `{"ok", "target", "saved", "error"}`。⚠ 例外を外へ出さない（★画面が落ちない）。
    ★DB は sqlite の backup API（★GUI が開いていても安全に写せる）。
    """
    info = survey()
    target = _new_target(label)
    saved: list = []
    try:
        target.mkdir(parents=True, exist_ok=False)
        if DB_PATH.exists():
            dest = target / DB_PATH.name
            try:
                src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
                dst = sqlite3.connect(dest)
                with dst:
                    src.backup(dst)
                src.close()
                dst.close()
                saved.append(DB_PATH.name)
            except sqlite3.Error as exc:
                # ⚠ 黙って続けない。★退避できていないなら clear させない
                return {"ok": False, "target": target, "saved": saved,
                        "error": f"DB を写せませんでした: {exc}"}
        for name_, path, _size_ in info["files"]:
            if path.exists():
                # ★`runtime/dq2-log/retroux.log` のようにフォルダの中のものもある（RX-0149）
                (target / name_).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target / name_)
                saved.append(name_)
        for name_, path, _size_ in info["dirs"]:
            if path.exists():
                # ★DQ3 のものは写さない（RX-0148）
                shutil.copytree(path, target / name_, dirs_exist_ok=True,
                                ignore=_ignore_foreign)
                saved.append(name_ + "/")
        (target / "manifest.json").write_bytes(json.dumps({
            "created": _dt.datetime.now().isoformat(timespec="seconds"),
            "label": label,
            "saved": saved,
            "rows": info["db"]["rows"],
            "note": "⚠ ROM・セーブステート・採取データは入っていません",
        }, ensure_ascii=False, indent=1).encode("utf-8"))
    except OSError as exc:
        return {"ok": False, "target": target, "saved": saved, "error": f"退避できませんでした: {exc}"}
    return {"ok": True, "target": target, "saved": saved, "error": None}


def latest_backup() -> dict | None:
    """★最新の退避（★名前の順 = 時刻の順）。⚠ 無ければ None。"""
    if not VAULT.is_dir():
        return None
    entries = sorted(p for p in VAULT.iterdir() if p.is_dir())
    if not entries:
        return None
    path = entries[-1]
    created = None
    try:
        created = json.loads((path / "manifest.json").read_bytes().decode("utf-8")).get("created")
    except (OSError, ValueError, AttributeError):
        created = None
    return {"path": path, "name": path.name, "created": created, "count": len(entries)}


def cmd_backup(apply: bool, label: str | None = None) -> int:
    """★退避する。⚠ **何も消しません**。"""
    info = survey()
    total = (info["db"]["size"] + sum(s for _, _, s in info["files"])
             + sum(s for _, _, s in info["dirs"]))

    _out(f"★退避先: {_new_target(label)}")
    _out(f"  合わせて {_human(total)}")
    if not apply:
        _out("\n⚠ **数えただけです。**実際に退避するには `--apply` を付けてください。")
        return 0

    got = backup(label)
    target, saved = got["target"], got["saved"]
    if not got["ok"]:
        _out(f"  ⚠ {got['error']}")
        return 1
    _out(f"\n★退避しました: {target}")
    for item in saved:
        _out(f"  ★{item}")
    return 0


# --- ★ 消す ---------------------------------------------------------------

def cmd_clear(apply: bool, label: str | None = None) -> int:
    """★遊んだ記録を消す。⚠⚠ **必ず先に退避します**。"""
    info = survey()
    rows = sum(v for v in info["db"]["rows"].values() if v)
    _out("=== ★これから消すもの ===")
    _out(f"  DB の記録 {rows} 行"
         f"（{', '.join(f'{t} {n}' for t, n in info['db']['rows'].items() if n)}）")
    for name, path, size in info["files"] + info["dirs"]:
        if path.exists():
            _out(f"  {name}  {_human(size)}")
    _out("\n=== ⚠⚠ 消さないもの ===")
    _out("  ★ROM / ★セーブステート / ★採取データ / ★解析データ")
    _out("  ★DB の Rom テーブル（ROM の登録）")

    if not apply:
        _out("\n⚠ **数えただけです。**実際に消すには `--apply` を付けてください。")
        _out("★消す前に必ず退避します（`playdata-archive/`）。")
        return 0

    # ★★ 先に退避する。⚠ 失敗したら消さない
    _out("\n★まず退避します。")
    if cmd_backup(apply=True, label=label or "before-clear") != 0:
        _out("⚠⚠ **退避できなかったので、消しません。**")
        return 1

    _out("\n★消します。")
    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        try:
            existing = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            with conn:
                for table in PLAY_TABLES:
                    if table in existing:
                        conn.execute(f'DELETE FROM "{table}"')
                        _out(f"  ★{table} を空にしました")
                # ⚠ 連番も戻す（★新しい記録が 1 から始まる）
                if "sqlite_sequence" in existing:
                    marks = ",".join("?" * len(PLAY_TABLES))
                    conn.execute(
                        f"DELETE FROM sqlite_sequence WHERE name IN ({marks})",
                        PLAY_TABLES)
            conn.execute("VACUUM")
        finally:
            conn.close()

    for name, path, _size_ in survey()["files"]:
        if path.exists():
            path.unlink()
            _out(f"  ★{name} を消しました")
    for name, path, _size_ in survey()["dirs"]:
        if path.exists():
            # ⚠ フォルダを丸ごと消さない（★DQ3 の生成物を残す / RX-0148）
            _remove_owned(path)
            _out(f"  ★{name}/ を消しました（★DQ3 のものは残します）")

    # ★★ 消したままにしない（2026-08-08 / ⚠ 実際に起動できなくなった）★★
    #   `work/generated/` は「作り直せる」ものですが、
    #   ⚠ **作り直すまでは起動できません**。★ここで作り直します。
    _regenerate()

    _out("\n★まっさらになりました。⚠ ROM とセーブステートは残っています。")
    return 0


# --- ★ 一覧・戻す ---------------------------------------------------------

def cmd_list() -> int:
    if not VAULT.exists():
        _out(f"⚠ まだ退避がありません: {VAULT}")
        return 0
    entries = sorted(p for p in VAULT.iterdir() if p.is_dir())
    if not entries:
        _out("⚠ まだ退避がありません")
        return 0
    _out(f"★退避 {len(entries)} 件  ({VAULT})")
    for path in entries:
        manifest = path / "manifest.json"
        note = ""
        if manifest.exists():
            try:
                data = json.loads(manifest.read_bytes().decode("utf-8"))
                rows = sum(v for v in (data.get("rows") or {}).values() if v)
                note = f"  記録 {rows} 行 / {len(data.get('saved') or [])} 件"
            except ValueError:
                note = "  ⚠ manifest が読めません"
        _out(f"  {path.name}{note}   {_human(_size(path))}")
    return 0


def cmd_restore(name: str, apply: bool) -> int:
    """★退避を書き戻す。⚠⚠ **いまの記録は上書きされます。**"""
    source = VAULT / name
    if not source.is_dir():
        _out(f"✗ そんな退避はありません: {name}")
        _out("★`list` で一覧を見てください。")
        return 1
    _out(f"★戻す: {source}")
    _out("⚠⚠ **いまの記録は上書きされます。**")
    if not apply:
        _out("\n⚠ **何もしていません。**戻すには `--apply` を付けてください。")
        return 0

    # ★★ 戻す前に、いまの状態も退避する（★取り返しがつくように）
    _out("\n★念のため、いまの状態を退避します。")
    if cmd_backup(apply=True, label="before-restore") != 0:
        _out("⚠⚠ **退避できなかったので、戻しません。**")
        return 1

    if (source / DB_PATH.name).exists():
        shutil.copy2(source / DB_PATH.name, DB_PATH)
        _out(f"  ★{DB_PATH.name} を戻しました")
    for name_ in PLAY_FILES:
        if (source / name_).exists():
            play_file(name_).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / name_, play_file(name_))
            _out(f"  ★{name_} を戻しました")
    for name_ in DERIVED_DIRS:
        if (source / name_).is_dir():
            target = WORK / name_
            if target.exists():
                # ⚠ 丸ごと消さない（★DQ3 の生成物を残す / RX-0148）
                _remove_owned(target)
            shutil.copytree(source / name_, target, dirs_exist_ok=True,
                            ignore=_ignore_foreign)
            _out(f"  ★{name_}/ を戻しました")
    _out("\n★戻しました。")
    return 0


def _regenerate() -> None:
    """⚠ 起動に要るものを作り直す（★`work/generated/`）。

    ⚠⚠ **失敗しても止めません**が、★何が起きたかは必ず出します
      （「作り直せなかった」を黙ると、次の起動で理由の分からない失敗になります）。
    """
    import subprocess
    import sys as _sys

    _out()
    _out("★起動に要るものを作り直します（work/generated/）")
    try:
        done = subprocess.run(
            [_sys.executable, "-m", "retroux.core.config.generate_lua"],
            cwd=str(PROJECT_ROOT), capture_output=True, timeout=120)
    except Exception as exc:                           # noqa: BLE001
        _out(f"  ⚠⚠ 作り直せませんでした: {exc}")
        _out("  ★手で `python -m retroux.core.config.generate_lua` を"
             "実行してください（⚠ でないと起動できません）")
        return
    if done.returncode != 0:
        text = ((done.stdout or b"") + (done.stderr or b"")).decode(
            "utf-8", "replace")
        _out(f"  ⚠⚠ 作り直せませんでした: {text[:300]}")
        _out("  ★手で `python -m retroux.core.config.generate_lua` を"
             "実行してください（⚠ でないと起動できません）")
        return
    for name in ("memory_map.lua", "config.lua"):
        got = WORK / "generated" / name
        _out(f"  {'★' if got.exists() else '⚠'} {name}"
             f"{'' if got.exists() else ' … できていません'}")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                   # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(
        description="遊んだ記録を退避して、まっさらから始める")
    parser.add_argument("command",
                        choices=("status", "backup", "clear", "list", "restore"))
    parser.add_argument("name", nargs="?", default=None,
                        help="restore で戻す退避の名前")
    parser.add_argument("--apply", action="store_true",
                        help="★これを付けないと何も変わりません")
    parser.add_argument("--label", default=None, help="退避に付ける名前")
    args = parser.parse_args(argv)

    if args.command == "status":
        return cmd_status()
    if args.command == "backup":
        return cmd_backup(args.apply, args.label)
    if args.command == "clear":
        return cmd_clear(args.apply, args.label)
    if args.command == "list":
        return cmd_list()
    if not args.name:
        _out("✗ 戻す退避の名前を指定してください（`list` で見られます）")
        return 1
    return cmd_restore(args.name, args.apply)


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
