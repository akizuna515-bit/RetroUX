"""DQ2 のデータの版（data schema）の印と判定（RX-0157 / D-45）。

★製品の版（`retroux/version.py`）とは**別**に、遊んだデータの形の版を持つ。

```text
印       <write_root>/work/dq2-data.json   ★正本
         {"product": "retroux-dq2", "schema": 1, "created_by": "<RetroUX の版>", "history": [...]}
DB       PRAGMA user_version               ★補助（0 = 記録なし。旧版の DB は全部 0）
```

## 判定（依頼 §5-1・§6）

```text
new         印なし・DQ2 の遊んだデータなし          → 印を書いて始めてよい
schema0     印なし・DQ2 の遊んだデータあり          → 旧版のデータ（★移行の元 / その場でも今のコードは読める）
current     印あり・schema が今の版                  → そのまま
older       印あり・知っている古い版                 → 移行が要る（★今は 1 しか無いので起きない）
unknown     印の schema を知らない（新しすぎる・壊れた値）→ ⚠ 止める（★勝手に最新版扱いしない）
broken      印が読めない・product が違う             → ⚠ 止める
mismatch    印と DB の user_version が食い違う       → ⚠ 止める（★どちらにも合わせない）
incomplete  移行の journal が途中で終わっている      → ⚠ 止める（★本番が半端かもしれない）
```

DQ2 の遊んだデータ = DB の `Rom` に DQ2 の行 / events.jsonl が空でない / DQ2 の ROM の stem のセーブステート。
⚠ DQ3 のものは数えない（★同じ work/ に同居している旧版がある）。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

PRODUCT = "retroux-dq2"
#: ★今の版。⚠ 上げるときは migration の step を同じ commit で足す
CURRENT_SCHEMA = 1
#: ★読める版（★0 は印なしの旧版。印に 0 と書くことはない）
KNOWN_SCHEMAS = (1,)
MARKER_REL = "work/dq2-data.json"
#: ★移行の journal と staging（`retroux/migration/runner.py`）
MIGRATION_DIR_REL = "work/dq2-migration"
JOURNAL_NAME = "journal.jsonl"

#: ★DQ2 の ROM（`retroux/plugins/dq2/memory_map.yaml` の rom.prg_sha256 / title と同じ値。検査で突き合わせる）
DQ2_PRG_SHA256 = "B0F0CE24890DB516C01B1E748A8B4C68B38CEBC404C2BC1C24A1EF6FE02AC5CC"
DQ2_TITLE_WORD = "ドラゴンクエストII"

NEW, SCHEMA0, CURRENT, OLDER = "new", "schema0", "current", "older"
UNKNOWN, BROKEN, MISMATCH, INCOMPLETE = "unknown", "broken", "mismatch", "incomplete"
STOP_KINDS = (UNKNOWN, BROKEN, MISMATCH, INCOMPLETE)


class MarkerError(Exception):
    """印が読めない・別の製品のもの。"""


@dataclasses.dataclass(frozen=True)
class Places:
    """★判定に使う場所（★移行では旧フォルダの場所を渡す / 起動では dq2_paths から）。"""
    write_root: Path
    db: Path
    events: Path
    fcs_dir: Path
    rom_stem: str = "DQ2_J"


@dataclasses.dataclass(frozen=True)
class Detection:
    kind: str
    schema: int | None
    db_user_version: int | None
    evidence: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def stop(self) -> bool:
        return self.kind in STOP_KINDS

    def describe(self) -> str:
        lines = [f"DQ2 のデータ: {self.kind}（schema={self.schema} / DB user_version={self.db_user_version}）"]
        lines += [f"  理由: {r}" for r in self.reasons]
        lines += [f"  根拠: {e}" for e in self.evidence]
        return "\n".join(lines)


# --- 印 -------------------------------------------------------------------

def marker_path(write_root: Path) -> Path:
    return Path(write_root) / MARKER_REL


def read_marker(write_root: Path) -> dict | None:
    """★印を読む。無ければ None。⚠ 読めない・別の製品なら MarkerError。"""
    path = marker_path(write_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise MarkerError(f"{path} を読めません（{exc}）") from exc
    if not isinstance(data, dict):
        raise MarkerError(f"{path} の形が違います（オブジェクトではない）")
    if data.get("product") != PRODUCT:
        raise MarkerError(f"{path} は {data.get('product')!r} のものです（DQ2 の印ではない）")
    if not isinstance(data.get("schema"), int) or isinstance(data.get("schema"), bool):
        raise MarkerError(f"{path} の schema が整数ではありません（{data.get('schema')!r}）")
    return data


def new_marker(schema: int, created_by: str, event: str, **extra) -> dict:
    return {"product": PRODUCT, "schema": int(schema), "created_by": created_by,
            "history": [history_entry(event, schema, created_by, **extra)]}


def history_entry(event: str, schema: int, by: str, **extra) -> dict:
    entry = {"at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
             "event": event, "schema": int(schema), "by": by}
    entry.update(extra)
    return entry


def write_marker(write_root: Path, data: dict) -> Path:
    """★書きかけを残さない（隣に書いてから置き換える）。"""
    path = marker_path(write_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".dq2-data-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def program_version() -> str:
    try:
        from .dq2_version import get_version   # ★DQ2 の製品の版（RX-0160）
        return f"RetroUX DQ2 {get_version()}"
    except Exception:                                   # noqa: BLE001
        return "RetroUX ?"


# --- DB -------------------------------------------------------------------

def _open_ro(db: Path) -> sqlite3.Connection:
    """★読むだけで開く。

    ⚠⚠ WAL の DB は `mode=ro` でも `-wal` / `-shm` を作る（★2026-10-03 の検査で実測: 旧フォルダに 2 個増えた）。
      → `-wal` が無い（＝本体に全部入っている）ときは `immutable=1` で開き、何も作らない。
    ⚠ `-wal` があるときは普通に読む（★immutable だと WAL の中身を見落とす）。
      移行の元は写しを開く（`retroux/migration` の `source_detection`）ので、ここで旧フォルダに書くことはない。
    """
    path = Path(db).resolve()
    wal = path.with_name(path.name + "-wal")
    flag = "immutable=1" if not (wal.exists() and wal.stat().st_size > 0) else "mode=ro"
    from urllib.parse import quote

    uri = "file:" + quote(path.as_posix(), safe="/:") + "?" + flag
    return sqlite3.connect(uri, uri=True)


def db_user_version(db: Path) -> int | None:
    if not Path(db).exists():
        return None
    con = _open_ro(db)
    try:
        return int(con.execute("PRAGMA user_version").fetchone()[0])
    finally:
        con.close()


def db_has_dq2(db: Path) -> bool:
    if not Path(db).exists():
        return False
    con = _open_ro(db)
    try:
        has = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Rom'").fetchone()
        if not has:
            return False
        rows = con.execute("SELECT rom_hash, title FROM Rom").fetchall()
    finally:
        con.close()
    return any(str(h).upper() == DQ2_PRG_SHA256 or DQ2_TITLE_WORD in str(t) for h, t in rows)


# --- 判定 -----------------------------------------------------------------

def dq2_savestates(fcs_dir: Path, stem: str) -> list[Path]:
    from ..tools import dq2_savestate_backup as B

    if not Path(fcs_dir).is_dir():
        return []
    import fnmatch

    pats = B.patterns_for(stem)
    return sorted(p for p in Path(fcs_dir).iterdir()
                  if p.is_file() and any(fnmatch.fnmatch(p.name, pat) for pat in pats))


def play_evidence(places: Places) -> list[str]:
    """★DQ2 の遊んだデータの根拠（★無ければ空）。"""
    got = []
    try:
        if db_has_dq2(places.db):
            got.append(f"DB の Rom に DQ2（{places.db}）")
    except sqlite3.Error as exc:
        got.append(f"DB がある（⚠ 読めない: {exc}）（{places.db}）")
    if places.events.exists() and places.events.stat().st_size > 0:
        got.append(f"events.jsonl {places.events.stat().st_size} バイト（{places.events}）")
    saves = dq2_savestates(places.fcs_dir, places.rom_stem)
    if saves:
        got.append(f"DQ2 のセーブステート {len(saves)} 件（{places.fcs_dir}）")
    return got


#: ★遊んだ跡の表（★1 行でもあれば「遊んだ」/ RX-0164）。⚠ Rom と IngestState は起動しただけで書かれるので数えない
PLAY_TABLES = ("BattleLog", "BattleEvent", "EncounteredMonster", "VisitedTile", "MapEdge",
               "MapTransition", "MapBlockedDirection", "MapOverride", "MapNote", "MapLandmark",
               "NavigationSession")


def used_reason(places: Places) -> str | None:
    """★印が `created`（新しく始めた）だけで、まだ遊んだ跡が無いなら None。あればその理由（RX-0164）。

    ★ZIP を先に 1 回起動してから移行する、を許すため（⚠ 起動しただけで印・DB・events の先頭は書かれる）。
    ⚠ 1 つでも遊んだ跡（DB の記録・取り込んでいない events・DQ2 のセーブ）があれば移行しない（★混ぜない）。
    """
    try:
        marker = read_marker(places.write_root)
    except MarkerError as exc:
        return str(exc)
    if marker is None:
        return None
    events = [h.get("event") for h in marker.get("history") or [] if isinstance(h, dict)]
    if any(e != "created" for e in events):
        return f"印の履歴に {', '.join(e for e in events if e != 'created')} があります"
    size = places.events.stat().st_size if places.events.exists() else 0
    if Path(places.db).exists():
        con = _open_ro(places.db)
        try:
            have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in PLAY_TABLES:
                if table in have:
                    n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    if n:
                        return f"DB の {table} に {n} 行あります"
            offset = 0
            if "IngestState" in have:
                row = con.execute("SELECT offset FROM IngestState WHERE source = ?",
                                  ("dq2:events:main",)).fetchone()
                offset = int(row[0]) if row else 0
        finally:
            con.close()
        if size > offset:
            return f"取り込んでいない events が {size - offset:,} バイトあります"
    elif size > 0:
        return f"DB が無いのに events が {size:,} バイトあります"
    saves = dq2_savestates(places.fcs_dir, places.rom_stem)
    if saves:
        return f"DQ2 のセーブステートが {len(saves)} 件あります"
    return None


def unfinished_migration(write_root: Path) -> str | None:
    """★journal の最後の run が終わっていなければ、その run の id。"""
    path = Path(write_root) / MIGRATION_DIR_REL / JOURNAL_NAME
    if not path.exists():
        return None
    state: dict[str, str] = {}
    for line in path.read_bytes().decode("utf-8", "replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        run = rec.get("run")
        if run:
            state[run] = rec.get("phase", "")
    for run, phase in state.items():
        if phase not in ("done", "aborted"):
            return run
    return None


def detect(places: Places) -> Detection:
    reasons: list[str] = []
    run = unfinished_migration(places.write_root)
    try:
        uv = db_user_version(places.db)
    except sqlite3.Error as exc:
        uv = None
        reasons.append(f"DB の user_version を読めません（{exc}）")
    if run:
        return Detection(INCOMPLETE, None, uv, (), (f"移行 {run} が途中で終わっています",))
    try:
        marker = read_marker(places.write_root)
    except MarkerError as exc:
        return Detection(BROKEN, None, uv, (), (str(exc),))
    if marker is None:
        evidence = tuple(play_evidence(places))
        if uv is not None and uv > CURRENT_SCHEMA:
            return Detection(UNKNOWN, None, uv, evidence,
                             (f"印が無いのに DB の user_version が {uv}（この版は {CURRENT_SCHEMA} まで）",))
        return Detection(SCHEMA0 if evidence else NEW, 0 if evidence else None, uv, evidence, tuple(reasons))
    schema = marker["schema"]
    if schema not in KNOWN_SCHEMAS:
        return Detection(UNKNOWN, schema, uv, (),
                         (f"印の schema {schema} を知りません（この版が読めるのは {list(KNOWN_SCHEMAS)}）",))
    if uv is not None and uv != schema:
        return Detection(MISMATCH, schema, uv, (),
                         (f"印は schema {schema}、DB の user_version は {uv}（★どちらにも合わせずに止めます）",))
    return Detection(CURRENT if schema == CURRENT_SCHEMA else OLDER, schema, uv, (), tuple(reasons))


def current_places(cfg=None) -> Places:
    """★起動している DQ2 の場所（dq2_paths / 設定から）。"""
    from . import dq2_paths
    from .config import dq2_user_config

    if cfg is None:
        cfg = dq2_user_config.load()[0]
    return Places(write_root=dq2_paths.write_root(), db=Path(cfg.path("db")),
                  events=dq2_paths.events(), fcs_dir=dq2_paths.fcs_dir(cfg),
                  rom_stem=dq2_paths.rom(cfg).stem)


def gate(places: Places | None = None, *, out=print) -> int:
    """★起動の前に見る（start-dq2.ps1）。戻り値: 0 = 起動してよい / 2 = 止める。

    ★new なら印を書く（★遊んだデータが無いので、取り違えようがない）。
    ⚠ schema0 では何も書かない（★旧版のデータはその場でも今のコードで読める。移行は `retroux.migration`）。
    """
    places = places or current_places()
    found = detect(places)
    if found.stop:
        out(found.describe())
        return 2
    if found.kind == NEW:
        write_marker(places.write_root, new_marker(CURRENT_SCHEMA, program_version(), "created"))
        out(f"DQ2 のデータ: 新しく始めます（{marker_path(places.write_root)} を作りました）")
    elif found.kind == SCHEMA0:
        out(found.describe() + "\n  ★旧版のデータです（この場で読めます / 移行はしていません）")
    elif found.kind == OLDER:
        out(found.describe() + "\n  ⚠ 移行が必要です（python -m retroux.migration）")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="DQ2 のデータの版を見る（RX-0157）")
    ap.add_argument("--gate", action="store_true", help="起動前の判定（new なら印を書く / 止めるなら 2）")
    ap.add_argument("--out", help="★結果を UTF-8 で書くファイル（1 行目 OK / STOP。起動スクリプトが読む）")
    args = ap.parse_args(argv)
    if args.gate:
        lines: list[str] = []
        code = gate(out=lines.append)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            body = "\n".join(["OK" if code == 0 else "STOP", *lines]) + "\n"
            Path(args.out).write_bytes(body.encode("utf-8"))
        for line in lines:
            print(line)
        return code
    print(detect(current_places()).describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
