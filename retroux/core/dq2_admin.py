"""DQ2 管理画面が出すもの（RX-0171〜0174 / 2026-10-06）。★Qt を知らない判定だけ。

★画面（`retroux/ui/admin_window.py`）は、ここが返す形を並べるだけにします。
  ⚠ 判定を画面に書くと、検査が窓を立てないと書けなくなります。

```text
runtime_kind()       同梱 Python / 開発の .venv / そのほか
places()             ROM・FCEUX・データ保存場所（★表示だけ / 変えるのは dq2_user_config.yaml）
backup_view()        セーブステート控えの状態（BP-27 / ★画面側の判定。控えの状態ファイルの形は変えない）
migration_view()     このフォルダの移行の状態（★移行は実行しない / migrate-dq2.cmd の案内）
```

⚠ すべて DQ2 LOCAL（★DQ3 はこのファイルを import しない）。
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

#: ★控えの状態（BP-27）
OK, STOPPED, NO_FCEUX, NO_FCS, NO_SAVES = "ok", "stopped", "no-fceux", "no-fcs", "no-saves"

#: ★画面に出す言葉（★1 か所）
BACKUP_LABELS = {
    OK: "正常",
    STOPPED: "控えが止まっています",
    NO_FCEUX: "FCEUX が見つかりません",
    NO_FCS: "セーブステートのフォルダ（fcs）がありません",
    NO_SAVES: "セーブステートがまだありません",
}


def runtime_kind(executable: str | None = None) -> str:
    """★動いている Python の種別（★起動スクリプトと同じ順の見分け / `launcher-common.ps1`）。"""
    exe = Path(executable or sys.executable)
    parts = [p.lower() for p in exe.parts]
    if "runtime" in parts and "python" in parts:
        return "同梱 Python"
    if ".venv" in parts:
        return "開発環境（.venv）"
    return "そのほかの Python"


@dataclasses.dataclass(frozen=True)
class Place:
    label: str
    path: str
    exists: bool

    @property
    def note(self) -> str:
        return "" if self.exists else "⚠ 見つかりません"


def places(cfg=None) -> list[Place]:
    """★ROM・FCEUX・データ保存場所（★表示だけ）。⚠ 読めなければ空の欄にして落ちない。"""
    from . import dq2_paths

    out = []
    try:
        info = dq2_paths.launch_info(cfg)
    except Exception:                                    # noqa: BLE001 ★表示のための処理で止めない
        info = {}
    for key, label in (("rom", "ROM"), ("fceux", "FCEUX")):
        path = info.get(key) or ""
        out.append(Place(label, path, bool(path) and Path(path).is_file()))
    try:
        data = dq2_paths.work()
    except Exception:                                    # noqa: BLE001
        data = None
    out.append(Place("データ保存場所", str(data) if data else "", bool(data) and Path(data).is_dir()))
    return out


@dataclasses.dataclass(frozen=True)
class BackupView:
    code: str
    lines: tuple

    @property
    def label(self) -> str:
        return BACKUP_LABELS[self.code]

    @property
    def warning(self) -> bool:
        return self.code != OK


def judge_backup(*, fceux_exists: bool, fcs_exists: bool, running: bool, saves: int) -> str:
    """★控えの状態を 1 つに決める（★純粋関数 / 先に「場所」の問題を出す = 直す手がかりになる方）。"""
    if not fceux_exists:
        return NO_FCEUX
    if not fcs_exists:
        return NO_FCS
    if not running:
        return STOPPED
    if saves <= 0:
        return NO_SAVES
    return OK


def backup_view(cfg=None, *, lock=None, busy=None) -> BackupView:
    """★セーブステート控えの状態（BP-27）。⚠ 控えの状態ファイルは読むだけ（★形を変えない / DQ3 に影響させない）。

    ★「動いているか」は心拍と PID（`RecorderLock.is_active`）で見る（⚠ 状態ファイルの running は死んでも残る）。
    ★セーブの数は控えと同じ形（`<ROM 名>*.fc?` ほか）で数える（`dq2_savestate_backup.watched_files`）。
    """
    from ..tools import dq2_savestate_backup as B
    from . import backup_status, dq2_paths

    try:
        fceux = Path(dq2_paths.fceux_exe(cfg))
        fcs = Path(dq2_paths.fcs_dir(cfg))
        stem = dq2_paths.rom(cfg).stem or B.DEFAULT_ROM_STEM
    except Exception:                                    # noqa: BLE001
        fceux = fcs = None
        stem = B.DEFAULT_ROM_STEM
    lock = Path(lock) if lock is not None else B.lock_path()
    running = (busy or B.is_busy)(lock)
    saves = B.watched_files(fcs, stem) if (fcs is not None and fcs.is_dir()) else []
    code = judge_backup(fceux_exists=bool(fceux and fceux.is_file()),
                        fcs_exists=bool(fcs and fcs.is_dir()), running=running, saves=len(saves))
    status = backup_status.read(lock)
    lines = [("監視先", str(fcs) if fcs else "（分かりません）"),
             ("セーブステート", "%d 件（%s*）" % (len(saves), stem))]
    if status.generations is not None:
        lines.append(("世代数", "%d" % status.generations))
    lines.append(("最終保存", status.last_backup or "まだありません（★この起動のあいだ）"))
    if status.destination:
        lines.append(("控えの保存先", status.destination))
    return BackupView(code, tuple(lines))


@dataclasses.dataclass(frozen=True)
class MigrationView:
    text: str
    can_migrate: bool
    reason: str


def migration_view(places_=None) -> MigrationView:
    """★このフォルダの移行の状態（★画面からは実行しない / 依頼者 2026-10-06）。"""
    from . import dq2_data as D

    try:
        here = places_ or D.current_places()
        marker = D.read_marker(here.write_root) or {}
        history = [h for h in marker.get("history") or [] if isinstance(h, dict)]
        migrated = next((h for h in reversed(history) if h.get("event") == "migrated"), None)
        used = D.used_reason(here)
    except Exception as exc:                             # noqa: BLE001 ★表示のための処理で止めない
        return MigrationView("移行の状態を読めませんでした（%s）" % exc, False,
                             "移行の状態を読めないため、案内を出せません")
    if migrated is not None:
        return MigrationView("旧フォルダから移行済み（%s）" % str(migrated.get("at", ""))[:16].replace("T", " "),
                             False, "このフォルダは移行済みです（★移行は 1 度だけ）")
    if used:
        return MigrationView("このフォルダで遊んでいます", False,
                             "移行できるのは、新しく展開してまだ遊んでいないフォルダだけです（%s）" % used)
    return MigrationView("まだ遊んでいません（旧フォルダから移せます）", True, "")


__all__ = ["runtime_kind", "places", "backup_view", "judge_backup", "migration_view",
           "Place", "BackupView", "MigrationView", "BACKUP_LABELS",
           "OK", "STOPPED", "NO_FCEUX", "NO_FCS", "NO_SAVES"]
