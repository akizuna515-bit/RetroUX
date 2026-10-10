"""移行 step `0001_legacy_to_portable`: 旧 DQ2 フォルダ（schema 0）→ Portable DQ2（schema 1）。

★RX-0158 / D-45 / 依頼 §9〜§14。

## ★何を写すかは ownership の表から決める（依頼 §8）

旧フォルダのファイルを 1 件ずつ `dq2_ownership.classify` に当て、方針（`policy`）で分ける:

```text
MIGRATE          写す（★DB だけは専用処理: 下）
CONVERT          形を変えて写す（★HANDLERS に専用処理が必須）
OPTIONAL         Options で選んだものだけ（★既定は default_on = map-assets）
REGENERATE       写さない（★移行のあとで新しい版が作る）
DO_NOT_MIGRATE   写さない（★DQ3 のもの・実行時のもの・ログ・開発用）
表に無い         写さない（★「分類されていない」として報告に出す）
```

## 専用処理（HANDLERS）

```text
work/retroux.sqlite3*        ★backup API。旧の DB・-wal・-shm を一度写してから開く（⚠ 旧には触らない）
                             → Database で列を足す → IngestState.source を論理 ID dq2:events:main へ（★末尾の署名も）→ user_version = 1
user_config.yaml             → dq2_user_config.yaml（★dq2_user_config.yaml が無いときだけ / fceux・dq3_rom を落とす）
config/{keybindings,mantan,mission}.yaml → work/dq2-settings/（★新の置き場に無いときだけ）
fcs/* sav/*                  ★DQ2 の ROM の stem だけ → <移行先>/tools/fceux/{fcs,sav}/
work/savestate-backup/*      ★DQ2 の stem の下位フォルダだけ → work/runtime/dq2-backup/savestate-backup/
work/rom/*                   ★選んだときだけ・paths.rom の 1 本・同じ名前・SHA を DB の Rom と照合
work/playdata-archive/*      ★DQ3 のもの・seen-*.json を除く
```
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import yaml

from ..core import dq2_data as D
from ..core import dq2_ownership as O
from .runner import Context, MigrationStop, Step

ID = "0001_legacy_to_portable"
#: ★旧版で DQ2 のフォルダだと分かる目印（★DQ3 Portable も retroux/ の一部を持つので両方を見る）
DQ2_SIGNS = ("retroux/core/db/database.py", "retroux/plugins/dq2")
#: ⚠ playdata-archive から写さないもの（★DQ3 のもの / DQ3 の既読）
ARCHIVE_SKIP = ("seen-*.json",)
#: ★設定のうち旧フォルダの中を指しうる場所（★書き換えずに警告する）
PATH_KEYS = ("rom", "fceux", "db", "log")


# --- 移行元 -----------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise MigrationStop(f"{path} を読めません（{exc}）") from exc
    return data if isinstance(data, dict) else {}


def source_config(source: Path) -> tuple[dict, str]:
    """★旧フォルダの DQ2 の設定（★dq2_user_config.yaml → user_config.yaml → 既定）と、その出どころ。"""
    for name in ("dq2_user_config.yaml", "user_config.yaml"):
        if (source / name).exists():
            data = _load_yaml(source / name)
            if name == "user_config.yaml":
                paths = dict(data.get("paths") or {})
                for key in ("fceux", "dq3_rom"):        # ★DQ3 の値（RX-0147）
                    paths.pop(key, None)
                data = {**data, "paths": paths}
            return data, name
    return {}, ""


def _path_value(cfg: dict, key: str, default: str) -> str:
    value = (cfg.get("paths") or {}).get(key)
    return str(value) if value else default


def _under(source: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else source / p


def source_fceux_dir(source: Path, cfg: dict) -> Path:
    given = _path_value(cfg, "fceux", "")
    if given:
        return _under(source, given).parent
    return source / "tools" / "fceux"


def source_places(source: Path) -> D.Places:
    cfg, _name = source_config(source)
    rom = _under(source, _path_value(cfg, "rom", "work/rom/DQ2_J.nes"))
    return D.Places(write_root=source,
                    db=_under(source, _path_value(cfg, "db", "work/retroux.sqlite3")),
                    events=source / "work" / "events.jsonl",    # ★旧版の Lua も write_root（= source）に書いた
                    fcs_dir=source_fceux_dir(source, cfg) / "fcs",
                    rom_stem=rom.stem)


def source_detection(source: Path) -> D.Detection:
    """★移行元の判定（⚠ 旧の DB は写しを開く = 旧フォルダに -wal / -shm を作らない）。"""
    import dataclasses
    import tempfile

    places = source_places(source)
    if not places.db.exists():
        return D.detect(places)
    with tempfile.TemporaryDirectory(prefix="dq2-src-") as tmp:
        for f in _db_files(places.db):
            if f.exists():
                shutil.copy2(f, Path(tmp) / f.name)
        return D.detect(dataclasses.replace(places, db=Path(tmp) / places.db.name))


def check_source_is_dq2(source: Path) -> None:
    info = source / "build-info.json"
    if info.exists():
        try:
            product = json.loads(info.read_bytes().decode("utf-8")).get("product")
        except (OSError, ValueError):
            product = None
        if product and product != D.PRODUCT:
            raise MigrationStop(f"移行元は {product} のフォルダです（DQ2 ではありません）")
    missing = [s for s in DQ2_SIGNS if not (source / s).exists()]
    if missing:
        raise MigrationStop(f"移行元は DQ2 のフォルダに見えません（無いもの: {missing}）")
    try:
        if D.read_marker(source) is not None:
            raise MigrationStop("移行元は既に新しい版のデータです（schema 0 ではありません）")
    except D.MarkerError as exc:
        raise MigrationStop(f"移行元の印が読めません（{exc}）") from exc


def _inside(path: Path, root: Path) -> bool:
    try:
        Path(os.path.normcase(path.resolve())).relative_to(Path(os.path.normcase(root.resolve())))
        return True
    except ValueError:
        return False


# --- 候補を集める（★ownership で分ける）-------------------------------------

def _has_carried_inside(rel_dir: str) -> bool:
    return any(e.pattern.startswith(rel_dir + "/") and O.policy(e) not in (O.DO_NOT_MIGRATE, O.REGENERATE)
               for e in O.TABLE)


def _walk(base: Path, prefix: str, root: str | None):
    """★(相対パス, 実パス, 分類の行) を返す。方針が DO_NOT_MIGRATE / REGENERATE のフォルダには降りない。"""
    if not base.is_dir():
        return
    for entry in sorted(base.iterdir()):
        rel = f"{prefix}{entry.name}"
        if O.is_dq3(rel):
            yield rel, entry, "DQ3"
            continue
        row = O.classify(rel, root)
        if entry.is_dir():
            # ⚠ 中に写す行があるフォルダには降りる（★generated/ の中の tile_art.txt・runtime/dq2-backup/ の控え）
            if (row is not None and O.policy(row) in (O.DO_NOT_MIGRATE, O.REGENERATE)
                    and not _has_carried_inside(rel)):
                yield rel + "/", entry, row
                continue
            yield from _walk(entry, rel + "/", root)
        else:
            yield rel, entry, row


def candidates(source: Path, cfg: dict):
    for name in ("dq2_user_config.yaml", "user_config.yaml"):
        p = source / name
        if p.is_file():
            yield name, p, O.classify(name, "program")
    for p in sorted((source / "config").glob("*.yaml")):
        rel = f"config/{p.name}"
        yield rel, p, ("DQ3" if O.is_dq3(rel) else O.classify(rel, "program"))
    yield from _walk(source / "work", "work/", None)
    fceux = source_fceux_dir(source, cfg)
    if _inside(fceux, source) and fceux.is_dir():
        # ★FCEUX のフォルダを丸ごと見る（★fcs・sav はセーブ / fceux.cfg は写さない / ほかは FCEUX 本体 = RX-0167）
        for p in sorted(fceux.rglob("*")):
            if p.is_file():
                rel = p.relative_to(fceux).as_posix()
                yield rel, p, O.classify(rel, "fceux")


def optional_key(row: O.Entry) -> str:
    """★OPTIONAL の鍵（`work/map-assets/*` → `map-assets` / `work/events-*.jsonl` → `events-archive` / FCEUX 本体 → `fceux`）。"""
    if row.root == "fceux":
        return "fceux"
    pat = row.pattern.removeprefix("work/").removesuffix("/*")
    return "events-archive" if pat.startswith("events-") else pat


def optional_keys() -> dict[str, bool]:
    return {optional_key(e): e.default_on for e in O.entries(carry="optional")}


def selected(ctx: Context, row: O.Entry) -> bool:
    key = optional_key(row)
    if key in ctx.options.exclude:
        return False
    return key in ctx.options.include or (row.default_on and key not in ctx.options.exclude)


# --- 書き出し ----------------------------------------------------------------

def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _count(ctx: Context, key: str, n: int = 1) -> None:
    ctx.report[key] = ctx.report.get(key, 0) + n


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def _stat_sig(paths) -> list:
    return [(str(p), p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else (str(p), None, None)
            for p in paths]


def _db_files(db: Path) -> list[Path]:
    return [db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")]


def _tables(con: sqlite3.Connection) -> dict[str, int]:
    names = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {n: con.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}


def handle_db(ctx: Context, src_db: Path) -> None:
    """★backup API で写す（⚠ 単純コピー禁止: WAL・未反映のデータ・IngestState の絶対パス / 依頼 §9）。"""
    from ..core.db.database import Database
    from ..core.recorder import MAIN_STREAM, _head_signature, _tail_signature

    snap_dir = ctx.staging / ".tmp" / "db-snapshot"
    snap_dir.mkdir(parents=True, exist_ok=True)
    files = _db_files(src_db)
    before = _stat_sig(files)
    for f in files:
        if f.exists():
            shutil.copy2(f, snap_dir / f.name)
    if _stat_sig(files) != before:
        raise MigrationStop("旧の DB が写している間に変わりました（★旧の RetroUX を閉じてから）")
    snap = snap_dir / src_db.name
    scon = sqlite3.connect(snap)
    try:
        ok = scon.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise MigrationStop(f"旧の DB が壊れています（integrity_check: {ok}）")
        before_rows = _tables(scon)
        dst = ctx.staging / "work" / "retroux.sqlite3"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dcon = sqlite3.connect(dst)
        try:
            scon.backup(dcon)
        finally:
            dcon.close()
    except sqlite3.DatabaseError as exc:
        raise MigrationStop(f"旧の DB を読めません（{exc}）") from exc
    finally:
        scon.close()

    db = Database(dst)        # ★列を足す（★新しい版の形に / IngestState.tail_sig・path も）
    db.close()

    # ★IngestState: 旧の行（鍵 = 旧の events の絶対パス）→ 論理 ID `dq2:events:main`（RX-0163）
    #   ⚠ 新しい絶対パスへは書き換えない（★フォルダを動かすと取り込み直すので / 依頼 RX-0163 §5）
    src_events = ctx.source / "work" / "events.jsonl"
    new_events = str((ctx.dest / "work" / "events.jsonl").resolve())
    size = src_events.stat().st_size if src_events.exists() else 0
    sig = _head_signature(src_events) if src_events.exists() else None
    con = sqlite3.connect(dst)
    try:
        rows = con.execute("SELECT source, offset, head_sig FROM IngestState").fetchall()
        if any(r[0] == MAIN_STREAM for r in rows):
            raise MigrationStop("旧の DB に既に論理 ID の行があります（schema 0 の DB ではない）")
        expected = os.path.normcase(str(src_events.resolve()))
        match = [r for r in rows if os.path.normcase(r[0]) == expected]
        if not match:
            # ★旧フォルダを動かしたことがある → 先頭の署名が同じ行を採る（★1 行だけのとき / 中身で確かめる）
            match = [r for r in rows if sig is not None and r[2] == sig]
        if len(match) > 1:
            raise MigrationStop(f"IngestState に今の events の行が {len(match)} 行あります（どれか決められない）")
        if rows and not match and size > 0:
            raise MigrationStop("IngestState の行が旧の events.jsonl と合いません"
                                "（★このまま移すと過去の記録を二重に取り込みます）")
        moved = None
        if match:
            old_source, offset, head = match[0]
            if offset > size:
                raise MigrationStop(f"取り込み位置 {offset} が events.jsonl の大きさ {size} を超えています（events 不足）")
            if head is not None and sig is not None and head != sig:
                raise MigrationStop("events.jsonl の先頭が IngestState の署名と違います（別のファイル）")
            if offset > 0:
                with src_events.open("rb") as fh:
                    fh.seek(offset - 1)
                    if fh.read(1) != b"\n":
                        raise MigrationStop("取り込み位置が events.jsonl の行の途中です（別のファイル）")
            tail = _tail_signature(src_events, offset)
            con.execute("UPDATE IngestState SET source = ?, tail_sig = ?, path = ? WHERE source = ?",
                        (MAIN_STREAM, tail, new_events, old_source))
            moved = {"from": old_source, "to": MAIN_STREAM, "offset": offset, "path": new_events}
        con.execute(f"PRAGMA user_version = {D.CURRENT_SCHEMA}")
        con.commit()
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()
    for extra in _db_files(dst)[1:]:
        extra.unlink(missing_ok=True)
    ctx.report["db"] = {"rows": before_rows, "ingest": moved, "events_size": size}


def handle_user_config(ctx: Context, src: Path) -> None:
    if (ctx.source / "dq2_user_config.yaml").exists():
        _count(ctx, "skipped_by_newer")        # ★DQ2 専用の設定があればそちらを写す
        return
    data, _ = source_config(ctx.source)
    paths = dict(data.get("paths") or {})
    if str(paths.get("log", "")).replace("\\", "/") == "work/retroux.log":
        paths.pop("log")                        # ★共用ログの既定 → DQ2 のログ（RX-0149）
    data = {**data, "paths": paths}
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    out = ctx.staging / "dq2_user_config.yaml"
    out.write_bytes(("# 移行で作った DQ2 の設定（元: user_config.yaml / " + ID + "）\n"
                     "# ⚠ paths.fceux・paths.dq3_rom は DQ3 用なので落としました\n" + body).encode("utf-8"))
    _count(ctx, "converted")


def handle_settings(ctx: Context, src: Path) -> None:
    name = src.name
    if name not in ("keybindings.yaml", "mantan.yaml", "mission.yaml"):
        _count(ctx, "unclassified")
        ctx.notes.append(f"写していません: config/{name}（★DQ2 の利用者設定ではない）")
        return
    if (ctx.source / "work" / "dq2-settings" / name).exists():
        _count(ctx, "skipped_by_newer")
        return
    _copy(src, ctx.staging / "work" / "dq2-settings" / name)
    _count(ctx, "converted")


def _stem_match(name: str, stem: str) -> bool:
    from ..tools import dq2_savestate_backup as B

    return any(fnmatch.fnmatch(name, pat) for pat in B.patterns_for(stem))


def handle_fceux_save(ctx: Context, rel: str, src: Path) -> None:
    stem = source_places(ctx.source).rom_stem
    ok = _stem_match(src.name, stem) if rel.startswith("fcs/") else fnmatch.fnmatch(src.name, f"{stem}*.sav")
    if not ok:
        _count(ctx, "skipped_other_rom")        # ★DQ3 などのセーブ
        return
    _copy(src, ctx.staging / "tools" / "fceux" / rel)
    _count(ctx, "savestates" if rel.startswith("fcs/") else "battery_saves")


def handle_legacy_backup(ctx: Context, rel: str, src: Path) -> None:
    stem = source_places(ctx.source).rom_stem
    sub = rel.removeprefix("work/savestate-backup/")
    top = sub.split("/", 1)[0]
    if not _stem_match(top, stem):
        _count(ctx, "skipped_other_rom")
        return
    _copy(src, ctx.staging / "work" / "runtime" / "dq2-backup" / "savestate-backup" / sub)
    _count(ctx, "backup_generations")


def handle_rom(ctx: Context, rel: str, src: Path) -> None:
    cfg, _ = source_config(ctx.source)
    configured = _under(ctx.source, _path_value(cfg, "rom", "work/rom/DQ2_J.nes"))
    if os.path.normcase(src.resolve()) != os.path.normcase(configured.resolve()):
        _count(ctx, "skipped_other_rom")
        return
    from ..core import rom as rom_mod

    prg = rom_mod.identify(src).prg_sha256
    db = ctx.staging / "work" / "retroux.sqlite3"
    known = set()
    if db.exists():
        con = sqlite3.connect(db)
        try:
            known = {str(r[0]).upper() for r in con.execute("SELECT rom_hash FROM Rom")}
        finally:
            con.close()
    if prg != D.DQ2_PRG_SHA256 or (known and prg not in known):
        raise MigrationStop(f"ROM の照合に失敗しました（PRG SHA {prg[:12]}… / DB の Rom と一致しない）")
    dst = ctx.staging / rel
    _copy(src, dst)                              # ★同じ名前（★fcs は ROM の stem で探す）
    if _sha256(dst) != _sha256(src):
        raise MigrationStop("ROM を写したあとの SHA が元と違います")
    ctx.report["rom"] = {"name": src.name, "prg_sha256": prg}


#: ★移行先に既に FCEUX があるか（★あれば FCEUX 本体は写さない = 利用者が置いたものを上書きしない）
FCEUX_EXES = ("fceux64.exe", "fceux.exe")


def handle_fceux_program(ctx: Context, rel: str, src: Path) -> None:
    """★FCEUX 本体を `<移行先>/tools/fceux/` へ（RX-0167 / 依頼者「fceux をデフォルトで robocopy するようにして」）。

    ★範囲は手順書の robocopy と同じ（fcs・sav・fceux.cfg を除く全部）。
    ⚠ 移行先に FCEUX が既にあれば写さない（★上書きしない / notes に 1 行）。
    """
    have = [n for n in FCEUX_EXES if (ctx.dest / "tools" / "fceux" / n).exists()]
    if have:
        if not ctx.report.get("fceux_kept"):
            ctx.report["fceux_kept"] = have[0]
            ctx.notes.append(f"移行先に FCEUX（tools\\fceux\\{have[0]}）が既にあるので、FCEUX 本体は写していません")
        _count(ctx, "skipped_fceux_present")
        return
    _copy(src, ctx.staging / "tools" / "fceux" / rel)
    _count(ctx, "fceux_files")


def handle_archive(ctx: Context, rel: str, src: Path) -> None:
    if any(fnmatch.fnmatch(src.name, pat) for pat in ARCHIVE_SKIP):
        _count(ctx, "skipped_dq3")
        return
    _copy(src, ctx.staging / rel)
    _count(ctx, "copied")


HANDLERS = {
    "work/retroux.sqlite3*": "db",
    "user_config.yaml": handle_user_config,
    "config/keybindings.yaml": handle_settings,
    "config/mantan.yaml": handle_settings,
    "config/mission.yaml": handle_settings,
    "fcs/*": handle_fceux_save,
    "sav/*": handle_fceux_save,
    "work/savestate-backup/*": handle_legacy_backup,
    "work/rom/*": handle_rom,
    "work/playdata-archive/*": handle_archive,
    "*": handle_fceux_program,                  # ★FCEUX 本体（root fceux / RX-0167）
}


# --- step -------------------------------------------------------------------

def precheck(ctx: Context) -> list[str]:
    problems = []
    src = source_places(ctx.source)
    for row in O.entries(carry="convert"):
        if row.pattern not in HANDLERS:
            problems.append(f"CONVERT の {row.pattern} に専用処理がありません")
    if src.db.exists() and not _inside(src.db, ctx.source):
        problems.append(f"旧の DB が旧フォルダの外です（{src.db}）")
    if not src.db.exists() and src.events.exists() and src.events.stat().st_size > 0:
        problems.append("旧の DB が無いのに events.jsonl があります（★取り込み位置が分からない）")
    return problems


def apply(ctx: Context) -> None:
    cfg, _ = source_config(ctx.source)
    src_db = source_places(ctx.source).db
    db_done = False
    unclassified = []
    # ★DB を先に（★ROM の照合が DB の Rom を見る）
    if src_db.exists():
        handle_db(ctx, src_db)
        db_done = True
    for rel, path, row in candidates(ctx.source, cfg):
        if row == "DQ3":
            _count(ctx, "skipped_dq3")
            continue
        if row is None:
            unclassified.append(rel)
            continue
        pol = O.policy(row)
        if pol in (O.DO_NOT_MIGRATE, O.REGENERATE):
            _count(ctx, "skipped_" + pol.lower())
            continue
        if pol == O.OPTIONAL and not selected(ctx, row):
            _count(ctx, "skipped_optional")
            continue
        handler = HANDLERS.get(row.pattern)
        if handler == "db":
            if not db_done:
                raise MigrationStop("DB の行に当たったのに DB を写していません")
            continue
        if handler is None:
            if pol == O.CONVERT:
                raise MigrationStop(f"{rel} は CONVERT なのに専用処理がありません")
            _copy(path, ctx.staging / rel)
            _count(ctx, "copied")
        elif handler in (handle_user_config, handle_settings):
            handler(ctx, path)
        else:
            handler(ctx, rel, path)
    ctx.report["unclassified"] = unclassified
    if unclassified:
        ctx.notes.append(f"分類されていないので写していません: {len(unclassified)} 件（例 {unclassified[:5]}）")
    for key in PATH_KEYS:
        value = _path_value(cfg, key, "")
        if value and Path(value).is_absolute() and _inside(Path(value), ctx.source):
            ctx.notes.append(f"⚠ 設定の paths.{key} が旧フォルダの中を指しています（{value}）。書き換えていません")


def postcheck(ctx: Context) -> list[str]:
    problems = []
    dst = ctx.staging / "work" / "retroux.sqlite3"
    info = ctx.report.get("db")
    if info:
        con = sqlite3.connect(dst)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problems.append("移した DB の integrity_check が ok ではありません")
            after = _tables(con)
            for table, n in info["rows"].items():
                if after.get(table) != n:
                    problems.append(f"{table} の行数が違います（{n} → {after.get(table)}）")
            if con.execute("PRAGMA user_version").fetchone()[0] != D.CURRENT_SCHEMA:
                problems.append("DB の user_version が上がっていません")
            moved = info.get("ingest")
            if moved:
                row = con.execute("SELECT offset, tail_sig FROM IngestState WHERE source = ?",
                                  (moved["to"],)).fetchone()
                if row is None or row[0] != moved["offset"]:
                    problems.append("IngestState の付け替えが反映されていません")
                elif row[0] > 0 and row[1] is None:
                    problems.append("IngestState に取り込み済みの末尾の署名がありません")
            if con.execute("SELECT COUNT(*) FROM IngestState WHERE source LIKE '%events.jsonl'"
                           " AND source = ?", (str((ctx.dest / "work" / "events.jsonl").resolve()),)).fetchone()[0]:
                problems.append("IngestState に移行先の絶対パスの行があります（★鍵は論理 ID）")
        finally:
            con.close()
    src_events = ctx.source / "work" / "events.jsonl"
    new_events = ctx.staging / "work" / "events.jsonl"
    if src_events.exists():
        if not new_events.exists() or new_events.stat().st_size != src_events.stat().st_size:
            problems.append("events.jsonl の大きさが元と違います")
        if info and info.get("ingest") and info["ingest"]["offset"] > new_events.stat().st_size:
            problems.append("取り込み位置が移した events.jsonl を超えています")
    if (ctx.staging / "work" / "dq2-data.json").exists():
        problems.append("staging に印があります（★印は最後に runner が書く）")
    return problems


STEP = Step(id=ID, from_schema=0, to_schema=1, precheck=precheck, apply=apply, postcheck=postcheck)
