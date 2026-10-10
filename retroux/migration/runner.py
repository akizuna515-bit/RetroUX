"""DQ2 の移行 runner（RX-0157 / D-45 / 依頼 §7）。

★番号つきの step（`Step`）を、旧フォルダ（read-only）から新しいフォルダへ順に当てる。

```text
1. 移行先の状態を見る    印が今の版 → 何もしない（★完了済みは再適用しない）
                         途中の run が残っている → 止める（--discard-staging / --resume で明示）
                         印なしで遊んだデータがある → 止める（★上書きしない）
2. 移行元を見る          DQ2 のフォルダか・DQ3 のものではないか・schema 0 のデータがあるか
3. staging に作る        work/dq2-migration/staging/<run>/（★本番には触らない）
                         step ごとに precheck → apply → postcheck（★どれか失敗で中止・staging を消す）
4. 本番へ入れる          ファイルごとに os.replace（★入れる一覧を journal に先に書く = 途中で落ちても続きが分かる）
                         ⚠ 本番に同じ名前があれば入れる前に止める
5. 作り直し              generate_lua などを新しい版で（★失敗なら印を書かない = 起動しない）
6. 印                    work/dq2-data.json を最後に書く（★これが「終わった」の印）
```

journal は `work/dq2-migration/journal.jsonl`（1 行 1 記録 / run・phase）。
⚠ journal に終わっていない run があると、起動の判定（`dq2_data.detect`）が INCOMPLETE で止める
（★失敗した移行のまま FCEUX / GUI を起動しない / 依頼 §7-1）。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
import shutil
from pathlib import Path
from typing import Callable

from ..core import dq2_data as D


class MigrationStop(Exception):
    """★安全に止めた（本番は変えていない、または journal から続きが分かる）。"""


@dataclasses.dataclass(frozen=True)
class Options:
    #: ★選ぶもの（★ownership の optional の鍵 / 既定は default_on のもの）
    include: frozenset = frozenset()
    exclude: frozenset = frozenset()
    #: ★作り直し（★移行先のプログラムで動かす）。None なら作り直さない（★検査用。印に書く）
    regenerate: Callable[[Path], list] | None = None
    resume: bool = False
    discard_staging: bool = False


@dataclasses.dataclass
class Context:
    source: Path
    dest: Path
    staging: Path
    options: Options
    run: str
    journal: "Journal"
    #: ★step が数えたもの（報告と postcheck のため）
    report: dict = dataclasses.field(default_factory=dict)
    notes: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass(frozen=True)
class Step:
    id: str
    from_schema: int
    to_schema: int
    precheck: Callable[[Context], list]
    apply: Callable[[Context], None]
    postcheck: Callable[[Context], list]


@dataclasses.dataclass(frozen=True)
class Result:
    status: str          # "migrated" / "noop"
    run: str | None
    report: dict
    notes: tuple


class Journal:
    def __init__(self, dest: Path) -> None:
        self.path = Path(dest) / D.MIGRATION_DIR_REL / D.JOURNAL_NAME

    def write(self, run: str, phase: str, **extra) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
               "run": run, "phase": phase}
        rec.update(extra)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_bytes().decode("utf-8", "replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def last_of(self, run: str) -> dict | None:
        got = [r for r in self.records() if r.get("run") == run]
        return got[-1] if got else None

    def commit_list(self, run: str) -> list[str]:
        for rec in self.records():
            if rec.get("run") == run and rec.get("phase") == "committing":
                return list(rec.get("files") or [])
        return []


def steps_registry() -> tuple[Step, ...]:
    from . import m0001_legacy_to_portable

    return (m0001_legacy_to_portable.STEP,)


def plan(from_schema: int, to_schema: int = D.CURRENT_SCHEMA,
         steps: tuple[Step, ...] | None = None) -> list[Step]:
    """★from → to までの step の鎖。⚠ 途切れたら止める（★勝手に飛ばさない）。"""
    steps = steps if steps is not None else steps_registry()
    chain, at = [], from_schema
    while at < to_schema:
        nxt = [s for s in steps if s.from_schema == at]
        if len(nxt) != 1:
            raise MigrationStop(f"schema {at} から先へ進む step が {len(nxt)} 個あります（1 個である必要があります）")
        chain.append(nxt[0])
        at = nxt[0].to_schema
    if at != to_schema:
        raise MigrationStop(f"schema {from_schema} → {to_schema} の道がありません")
    return chain


def dest_places(dest: Path) -> D.Places:
    """★移行先（Portable 相当: program_root == write_root == dest）。"""
    return D.Places(write_root=dest, db=dest / "work" / "retroux.sqlite3",
                    events=dest / "work" / "events.jsonl",
                    fcs_dir=dest / "tools" / "fceux" / "fcs")


def _same_or_inside(a: Path, b: Path) -> bool:
    a, b = Path(os.path.normcase(a.resolve())), Path(os.path.normcase(b.resolve()))
    return a == b or b in a.parents or a in b.parents


def _new_run_id() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _unfinished(journal: Journal) -> dict | None:
    last: dict[str, dict] = {}
    for rec in journal.records():
        if rec.get("run"):
            last[rec["run"]] = rec
    for rec in last.values():
        if rec.get("phase") not in ("done", "aborted"):
            return rec
    return None


def migrate(source: Path, dest: Path, options: Options = Options(),
            steps: tuple[Step, ...] | None = None, *, out=print) -> Result:
    """★旧フォルダ `source` を新しいフォルダ `dest` へ移す。⚠ source には書かない。"""
    source, dest = Path(source), Path(dest)
    if _same_or_inside(source, dest):
        raise MigrationStop(f"移行元と移行先が重なっています（{source} / {dest}）")
    dest.mkdir(parents=True, exist_ok=True)
    journal = Journal(dest)

    # --- 1. 途中の run -------------------------------------------------
    left = _unfinished(journal)
    if left is not None:
        return _continue_unfinished(left, source, dest, options, journal, out=out)

    # --- 1. 移行先の状態 ------------------------------------------------
    found = D.detect(dest_places(dest))
    replacing = False
    if found.kind == D.CURRENT:
        used = D.used_reason(dest_places(dest))
        if used is None:
            # ★先に 1 回起動しただけ（印は created・遊んだ跡なし）→ 新規と同じく移す（RX-0164）
            #   ⚠ 起動で作られたファイルは消さずに退避する（work/dq2-migration/replaced/<run>/）
            replacing = True
        elif _was_migrated(dest):
            run = _new_run_id()
            journal.write(run, "done", result="noop", reason="移行先は既に移行済み")
            out(f"何もしません（移行先は既に移行済み / schema {found.schema}）")
            return Result("noop", run, {}, ())
        else:
            raise MigrationStop("移行先で既に遊んでいます（★混ぜません）: " + used)
    elif found.kind != D.NEW:
        raise MigrationStop("移行先が空ではありません（★上書きしません）\n" + found.describe())

    from . import m0001_legacy_to_portable as M

    M.check_source_is_dq2(source)
    got = M.source_detection(source)
    if got.kind != D.SCHEMA0:
        raise MigrationStop("移行元に移す旧版の DQ2 データがありません\n" + got.describe())

    chain = plan(0, D.CURRENT_SCHEMA, steps)
    run = _new_run_id()
    staging = dest / D.MIGRATION_DIR_REL / "staging" / run
    ctx = Context(source=source, dest=dest, staging=staging, options=options, run=run, journal=journal)
    journal.write(run, "staging", source=str(source), steps=[s.id for s in chain])
    try:
        staging.mkdir(parents=True)
        for step in chain:
            problems = step.precheck(ctx)
            if problems:
                raise MigrationStop(f"{step.id} の事前検査: " + " / ".join(problems))
            step.apply(ctx)
            problems = step.postcheck(ctx)
            if problems:
                raise MigrationStop(f"{step.id} の事後検査: " + " / ".join(problems))
            journal.write(run, "staging", step=step.id, step_done=True)
        files = _staged_files(staging)
        conflicts = [f for f in files if (dest / f).exists()]
        if conflicts and not replacing:
            raise MigrationStop(f"移行先に同じ名前があります（{len(conflicts)} 件 / 例 {conflicts[:3]}）")
    except BaseException as exc:
        shutil.rmtree(staging, ignore_errors=True)
        journal.write(run, "aborted", error=str(exc), stage="staging")
        raise
    if conflicts:
        ctx.notes.append(f"先に起動したときのファイル {len(conflicts)} 件を退避しました"
                         f"（{D.MIGRATION_DIR_REL}/replaced/{run}/）")
        ctx.report["replaced"] = conflicts
    journal.write(run, "committing", files=files, replaced=conflicts, report=ctx.report)
    _commit(staging, dest, files, conflicts, run)
    return _finish(run, source, dest, options, journal, ctx.report, ctx.notes, out=out)


def _was_migrated(dest: Path) -> bool:
    try:
        marker = D.read_marker(dest) or {}
    except D.MarkerError:
        return False
    return any(isinstance(h, dict) and h.get("event") == "migrated" for h in marker.get("history") or [])


def _staged_files(staging: Path) -> list[str]:
    return sorted(p.relative_to(staging).as_posix() for p in staging.rglob("*")
                  if p.is_file() and ".tmp" not in p.relative_to(staging).parts[:1])


def _commit(staging: Path, dest: Path, files: list[str], replaced: list[str] = (), run: str = "") -> None:
    """★ファイルごとに入れる（★同じ volume の os.replace）。⚠ 入れ済みは飛ばす（続きから）。

    ★`replaced`（先に起動したときのファイル）は、入れる前に `work/dq2-migration/replaced/<run>/` へ退避する。
    """
    keep = dest / D.MIGRATION_DIR_REL / "replaced" / run
    for rel in replaced:
        cur, saved = dest / rel, keep / rel
        if cur.exists() and not saved.exists() and (staging / rel).exists():
            saved.parent.mkdir(parents=True, exist_ok=True)
            os.replace(cur, saved)
    for rel in files:
        src, dst = staging / rel, dest / rel
        if not src.exists() and dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
    shutil.rmtree(staging, ignore_errors=True)


def _finish(run: str, source: Path, dest: Path, options: Options, journal: Journal,
            report: dict, notes: list, *, out=print) -> Result:
    journal.write(run, "regenerating")
    regenerated = options.regenerate is not None
    if regenerated:
        problems = options.regenerate(dest)
        if problems:
            journal.write(run, "regenerating", error=" / ".join(map(str, problems)))
            raise MigrationStop("作り直しに失敗しました（★印を書いていないので起動しません。"
                                "直してから --resume）: " + " / ".join(map(str, problems)))
    marker = D.new_marker(D.CURRENT_SCHEMA, D.program_version(), "migrated",
                          from_schema=0, source=str(source), run=run, regenerated=regenerated)
    try:
        before = D.read_marker(dest)
    except D.MarkerError:
        before = None
    if before:
        # ★先に起動したときの印（created）の履歴は残す（RX-0164）
        marker["history"] = list(before.get("history") or []) + marker["history"]
    D.write_marker(dest, marker)
    journal.write(run, "done", result="migrated", report=report)
    out(f"移行しました（run {run} / schema 0 → {D.CURRENT_SCHEMA}）")
    return Result("migrated", run, report, tuple(notes))


def _continue_unfinished(rec: dict, source: Path, dest: Path, options: Options,
                         journal: Journal, *, out=print) -> Result:
    run, phase = rec["run"], rec.get("phase")
    if phase == "staging":
        staging = dest / D.MIGRATION_DIR_REL / "staging" / run
        if not options.discard_staging:
            raise MigrationStop(f"前回の移行 {run} が staging の途中で終わっています（★本番は変えていません）。"
                                "消してやり直すには --discard-staging")
        shutil.rmtree(staging, ignore_errors=True)
        journal.write(run, "aborted", reason="discard_staging")
        return migrate(source, dest, dataclasses.replace(options, discard_staging=False), out=out)
    if phase in ("committing", "regenerating"):
        if not options.resume:
            raise MigrationStop(f"前回の移行 {run} が {phase} の途中で終わっています（⚠ 本番に一部が入っています）。"
                                "続きから行うには --resume")
        files = journal.commit_list(run)
        replaced = next((list(r.get("replaced") or []) for r in journal.records()
                         if r.get("run") == run and r.get("phase") == "committing"), [])
        staging = dest / D.MIGRATION_DIR_REL / "staging" / run
        if phase == "committing" or staging.exists():
            _commit(staging, dest, files, replaced, run)
        report = next((r.get("report") for r in journal.records()
                       if r.get("run") == run and r.get("phase") == "committing"), {}) or {}
        return _finish(run, source, dest, options, journal, report, [], out=out)
    raise MigrationStop(f"journal の状態が分かりません（run {run} / phase {phase}）")
