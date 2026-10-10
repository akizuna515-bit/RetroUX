"""DQ2 専用のセーブステート控え（RX-0143 / RX-0144 / D-42）。

★見たいのは「DQ2 の控えが DQ3 の領域に触らない」こと:

  1. 見張るのは DQ2 ROM の stem のファイルだけ（★DQ3_J のスロットを回さない）
  2. DQ3 の控えフォルダの世代を削らない（⚠ 以前は 100 → 10 に削っていた / 調査 D1）
  3. ロック・停止・状態・保存先が DQ3 の控え（`paths.backup_lock`）と別の場所
  4. DQ3 の停止の合図では止まらず、DQ2 の合図でだけ止まる
  5. DQ2 の GUI は**自分の札**の控えにだけ停止の合図を置く（⚠ 以前は無条件 / 調査 D2）
  6. 起動スクリプトが DQ2 専用の控えだけを起動・数える

⚠ 本物の work/ には書かない（★`RETROUX_WRITE_ROOT` を tmp に向ける / conftest も一時フォルダへ向けている）。
"""

from __future__ import annotations

import json
import threading
import time
import types
from pathlib import Path

import pytest

from retroux.core import backup_status
from retroux.core.single_instance import RecorderLock
from retroux.tools import dq2_savestate_backup as B

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """★書き先の根を tmp に（DQ2 の控えの場所はすべてここから決まる）。"""
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    return tmp_path


def _fcs(root: Path) -> Path:
    src = root / "fcs"
    src.mkdir(exist_ok=True)
    return src


# --- 1. 見張るのは DQ2 だけ ---------------------------------------------------

def test_見張るのはDQ2のROMのファイルだけ(root: Path) -> None:
    src = _fcs(root)
    for name in ("DQ2_J.fc0", "DQ2_J.fc9", "DQ2_J.fcs", "DQ2_J-bak.fc0",
                 "DQ3_J.fc0", "DQ3_J-bak.fc1", "DQ3_J.fcs", "other.fc0"):
        (src / name).write_bytes(name.encode())

    got = [p.name for p in B.watched_files(src, "DQ2_J")]
    assert got == ["DQ2_J-bak.fc0", "DQ2_J.fc0", "DQ2_J.fc9", "DQ2_J.fcs"]


def test_scanはDQ3のスロットに世代を作らない(root: Path) -> None:
    src = _fcs(root)
    dst = root / "dst"
    (src / "DQ2_J.fc0").write_bytes(b"dq2")
    (src / "DQ3_J.fc0").write_bytes(b"dq3")

    assert B.scan(src, dst, generations=10, rom_stem="DQ2_J", quiet=True) == 1
    assert (dst / "DQ2_J.fc0").is_dir()
    assert not (dst / "DQ3_J.fc0").exists()


def test_DQ3の控えフォルダの世代を削らない(root: Path) -> None:
    """⚠ 旧保存先は DQ3 の控えと共有だった。★同じ場所を渡されても DQ3_J の 100 世代に触らない。"""
    src = _fcs(root)
    shared = root / "work" / "savestate-backup"
    dq3_dir = shared / "DQ3_J.fc0"
    dq3_dir.mkdir(parents=True)
    for i in range(100):
        (dq3_dir / f"20261003-000000-000000-{i:06d}.bak").write_bytes(b"old%d" % i)
    # ★DQ3 のスロットが変わった（⚠ 以前はここで 10 世代まで削っていた）
    (src / "DQ3_J.fc0").write_bytes(b"new dq3")
    (src / "DQ2_J.fc0").write_bytes(b"dq2")

    B.scan(src, shared, generations=10, rom_stem="DQ2_J", quiet=True)

    assert len(list(dq3_dir.glob("*.bak"))) == 100
    assert (src / "DQ3_J.fc0").read_bytes() == b"new dq3"


def test_ROMの名前が取れないときはDQ2_Jを見る() -> None:
    class Broken:
        def path(self, name: str) -> Path:
            raise KeyError(name)

    assert B.rom_stem_from(Broken()) == "DQ2_J"


def test_ROMの名前にglobの文字があっても字義どおり(root: Path) -> None:
    src = _fcs(root)
    (src / "DQ[2]_J.fc0").write_bytes(b"x")
    (src / "DQ2_J.fc0").write_bytes(b"y")
    assert [p.name for p in B.watched_files(src, "DQ[2]_J")] == ["DQ[2]_J.fc0"]


# --- 2. 場所が DQ3 の控えと別 -------------------------------------------------

def test_ロック停止状態保存先はDQ2専用の場所(root: Path) -> None:
    home = root / "work" / "runtime" / "dq2-backup"
    assert B.lock_path() == home / "savestate_backup.lock"
    assert B.stop_path() == home / "savestate_backup.stop"
    assert backup_status.status_path(B.lock_path()) == home / "savestate_backup.status.json"
    assert B.default_dst() == home / "savestate-backup"
    assert B.legacy_dst() == root / "work" / "savestate-backup"


def test_DQ3の控えのロックと重ならない(root: Path) -> None:
    """★DQ3 の控えは `paths.backup_lock`（既定 work/savestate_backup.lock）を使う。"""
    from retroux.core.config.user_config import PathsConfig

    dq3_lock = root / PathsConfig().backup_lock
    assert B.lock_path() != dq3_lock
    assert B.lock_path().parent != dq3_lock.parent            # ★状態ファイルの名前が同じなので、フォルダごと別
    assert B.stop_path() != dq3_lock.with_suffix(".stop")
    assert backup_status.status_path(B.lock_path()) != backup_status.status_path(dq3_lock)
    assert B.default_dst() != root / "work" / "savestate-backup"


def test_statusはDQ2のロックだけを見る(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from retroux.core.config.user_config import PathsConfig

    # ★DQ3 の控えのロックが動いていても、DQ2 は FREE
    dq3_lock = RecorderLock(root / PathsConfig().backup_lock)
    dq3_lock.path.parent.mkdir(parents=True, exist_ok=True)
    dq3_lock.acquire()
    try:
        assert B.main(["--status"]) == 0
        assert capsys.readouterr().out.strip() == "FREE"

        mine = RecorderLock(B.lock_path())
        mine.path.parent.mkdir(parents=True, exist_ok=True)
        mine.acquire()
        try:
            assert B.main(["--status"]) == 0
            assert capsys.readouterr().out.strip() == "BUSY"
        finally:
            mine.release()
        # ★DQ2 のロックを離しても、DQ3 のロックは残る
        assert dq3_lock.path.exists()
    finally:
        dq3_lock.release()


# --- 3. 止め方 ------------------------------------------------------------------

def _quiet_logging(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    """⚠ main() が本物のログへ書かないように。"""
    from retroux.core import logging_setup
    from retroux.core.config.user_config import UserConfig

    original = UserConfig.path

    def path(self, name: str):
        if name == "log":
            return root / "log" / "retroux.log"
        if name == "rom":
            return root / "rom" / "DQ2_J.nes"
        return original(self, name)

    monkeypatch.setattr(UserConfig, "path", path)
    monkeypatch.setattr(logging_setup, "setup_logging",
                        lambda *a, **k: types.SimpleNamespace(shutdown=lambda: None))


def test_DQ3の停止の合図では止まらずDQ2の合図で止まる(
        root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from retroux.core.config.user_config import PathsConfig

    _quiet_logging(monkeypatch, root)
    src = _fcs(root)
    (src / "DQ2_J.fc0").write_bytes(b"dq2")
    result: list[int] = []
    t = threading.Thread(target=lambda: result.append(
        B.main(["--src", str(src), "--interval", "0.05", "--session", "s-dq2"])), daemon=True)
    t.start()
    try:
        deadline = time.monotonic() + 5
        while not backup_status.status_path(B.lock_path()).exists():
            assert time.monotonic() < deadline, "★DQ2 の控えが立たない"
            time.sleep(0.02)

        # ⚠ DQ3 の控えの停止の合図（work/savestate_backup.stop）
        dq3_stop = (root / PathsConfig().backup_lock).with_suffix(".stop")
        dq3_stop.parent.mkdir(parents=True, exist_ok=True)
        dq3_stop.write_text("stop", encoding="utf-8")
        time.sleep(0.4)
        assert t.is_alive(), "⚠ DQ3 の停止の合図で DQ2 の控えが止まった"
        assert dq3_stop.exists(), "⚠ DQ3 の合図を DQ2 の控えが消した"

        B.stop_path().write_text("stop", encoding="utf-8")
        t.join(timeout=5)
        assert not t.is_alive(), "★DQ2 の停止の合図で止まらない"
    finally:
        B.stop_path().parent.mkdir(parents=True, exist_ok=True)
        B.stop_path().write_text("stop", encoding="utf-8")
        t.join(timeout=5)
    assert result == [0]
    got = json.loads(backup_status.status_path(B.lock_path()).read_text(encoding="utf-8"))
    assert got["session"] == "s-dq2"
    assert got["generations"] == 10
    # ★世代は DQ2 専用の保存先に
    assert list((B.default_dst() / "DQ2_J.fc0").glob("*.bak"))


def _status(lock: Path, session: str | None) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    backup_status.write(lock, running=True, generations=10, watching="w", destination="d",
                        interval=1.0, session=session)


def _gui_stop(session: str | None, lock: Path) -> tuple[bool, types.SimpleNamespace]:
    from retroux.ui.main_window import MainWindow

    me = types.SimpleNamespace(_session=session)
    return MainWindow._stop_own_backup(me, lock_path=lock), me


def test_GUIは札が無ければ合図を置かない(root: Path) -> None:
    lock = B.lock_path()
    _status(lock, "s-1")
    ok, _ = _gui_stop(None, lock)
    assert ok is False
    assert not lock.with_suffix(".stop").exists()


def test_GUIは札の無い控えにも札が無ければ合図を置かない(root: Path) -> None:
    """⚠ 手で起動した控え（札なし）と、手で起動した GUI（札なし）は「同じ」ではない。"""
    lock = B.lock_path()
    _status(lock, None)
    ok, _ = _gui_stop(None, lock)
    assert ok is False
    assert not lock.with_suffix(".stop").exists()


def test_GUIは別の起動の控えに合図を置かない(root: Path) -> None:
    lock = B.lock_path()
    _status(lock, "someone-else")
    ok, _ = _gui_stop("s-1", lock)
    assert ok is False
    assert not lock.with_suffix(".stop").exists()


def test_GUIは自分の札の控えにだけ合図を置く(root: Path) -> None:
    from retroux.core.config.user_config import PathsConfig

    lock = B.lock_path()
    _status(lock, "s-1")
    dq3_lock = root / PathsConfig().backup_lock
    _status(dq3_lock, "s-1")       # ⚠ 札が偶然同じでも、DQ3 の場所には置かない

    ok, me = _gui_stop("s-1", lock)
    assert ok is True
    assert lock.with_suffix(".stop").exists()
    assert not dq3_lock.with_suffix(".stop").exists()
    # ★2 度目（「終了」と窓の ×）は置き直さない
    from retroux.ui.main_window import MainWindow

    lock.with_suffix(".stop").unlink()
    assert MainWindow._stop_own_backup(me, lock_path=lock) is True
    assert not lock.with_suffix(".stop").exists()


def test_GUIの既定はDQ2専用のロック(root: Path) -> None:
    """★引数を省いたときに DQ2 の場所を見る（⚠ `paths.backup_lock` を見ない）。"""
    lock = B.lock_path()
    _status(lock, "s-2")
    ok, _ = _gui_stop("s-2", None)  # type: ignore[arg-type]
    assert ok is True
    assert B.stop_path().exists()


# --- 4. 旧保存先 ----------------------------------------------------------------

def test_旧保存先は一覧と復元だけ(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = _fcs(root)
    legacy = B.legacy_dst() / "DQ2_J.fc0"
    legacy.mkdir(parents=True)
    (legacy / "20261001-000000-000000-000001.bak").write_bytes(b"legacy")
    (src / "DQ2_J.fc0").write_bytes(b"current")

    assert B.main(["--list", "--legacy"]) == 0
    assert "DQ2_J.fc0  （1世代）" in capsys.readouterr().out

    assert B.main(["--restore", "DQ2_J.fc0", "--legacy", "--src", str(src)]) == 0
    assert (src / "DQ2_J.fc0").read_bytes() == b"legacy"
    # ★復元前の状態は**新しい**保存先に残す（⚠ 旧保存先には書き足さない）
    kept = list((B.default_dst() / "DQ2_J.fc0").glob("*.bak"))
    assert [p.read_bytes() for p in kept] == [b"current"]
    assert len(list(legacy.glob("*.bak"))) == 1


def test_legacyだけでは監視を始めない(root: Path) -> None:
    assert B.main(["--legacy"]) == 2


# --- 5. 起動スクリプト ------------------------------------------------------------

def _launcher() -> str:
    return (ROOT / "scripts" / "start-dq2.ps1").read_text(encoding="utf-8-sig")


def _code_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


def test_起動スクリプトはDQ2専用の控えを起動する() -> None:
    code = "\n".join(_code_lines(_launcher()))
    assert '"retroux.tools.dq2_savestate_backup"' in code
    assert "-m retroux.tools.dq2_savestate_backup --status" in code
    # ⚠ 共有の控え（DQ3 も使う）と、共有のロックを見る口を使わない
    assert '"retroux.tools.savestate_backup"' not in code
    assert "--what backup" not in code


def test_起動スクリプトのプロセス検査はDQ3の控えに当たらない() -> None:
    import fnmatch

    line = next(ln for ln in _code_lines(_launcher()) if "$backupProcs = " in ln)
    pattern = line.split("-like '", 1)[1].split("'", 1)[0]
    assert fnmatch.fnmatch("pythonw.exe -m retroux.tools.dq2_savestate_backup --session x", pattern)
    assert not fnmatch.fnmatch("pythonw.exe -m dq3.savestate_backup --session x", pattern)
    assert not fnmatch.fnmatch("python.exe -m retroux.tools.savestate_backup", pattern)


def test_手で動かす入口もDQ2専用の控え() -> None:
    text = (ROOT / "scripts" / "backup.cmd").read_bytes().decode("cp932")
    assert "-m retroux.tools.dq2_savestate_backup" in text
    assert "-m retroux.tools.savestate_backup" not in text


# --- RX-0170: 起動に失敗したら、その起動の控えも止める ---------------------------

def test_起動の札が合う控えにだけ止まってもらう(root: Path) -> None:
    lock = B.lock_path()
    _status(lock, "mine")
    assert B.stop_own("other", lock) == B.OTHER
    assert not lock.with_suffix(".stop").exists(), "⚠⚠ 別の起動の控えを止めた"
    assert B.stop_own("mine", lock) == B.STOPPED
    assert lock.with_suffix(".stop").exists()


def test_控えが無いか止まっていれば何もしない(root: Path) -> None:
    lock = B.lock_path()
    assert B.stop_own("mine", lock) == B.NONE
    lock.parent.mkdir(parents=True, exist_ok=True)
    backup_status.write(lock, running=False, generations=10, watching="w", destination="d",
                        interval=1.0, session="mine")
    assert B.stop_own("mine", lock) == B.NONE
    assert not lock.with_suffix(".stop").exists()


def test_立ち上がりかけの控えは状態が出るまで待ってから止める(
        root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ 控えは合図の置き場を**消してから**状態を書く → 状態より先に合図を置くと消される（RX-0170）。

    ★本物の `main` を走らせ、立ち上がりと同時に `stop_own` を呼ぶ（GUI がすぐ終わった起動と同じ順）。
    """
    _quiet_logging(monkeypatch, root)
    src = _fcs(root)
    result: list[int] = []
    t = threading.Thread(target=lambda: result.append(
        B.main(["--src", str(src), "--interval", "0.05", "--session", "s-0170"])), daemon=True)
    t.start()
    try:
        assert B.stop_own("s-0170", wait=5) == B.STOPPED
        t.join(timeout=5)
        assert not t.is_alive(), "⚠⚠ 起動に失敗した起動の控えが残り続ける"
    finally:
        B.stop_path().parent.mkdir(parents=True, exist_ok=True)
        B.stop_path().write_text("stop", encoding="utf-8")
        t.join(timeout=5)
    assert result == [0]


def test_止める口を起動スクリプトから呼べる(
        root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ 口が無いと `main` は控えとして**見張りを始めてしまう**（★終わらない）→ 別の糸で時間を切る。"""
    _quiet_logging(monkeypatch, root)
    _status(B.lock_path(), "abc")

    def run(args: list[str]) -> list[int]:
        got: list[int] = []
        t = threading.Thread(target=lambda: got.append(B.main(args)), daemon=True)
        t.start()
        t.join(timeout=5)
        if t.is_alive():
            B.stop_path().write_text("stop", encoding="utf-8")
            t.join(timeout=5)
            pytest.fail("⚠⚠ --stop-session で止まらず、控えとして見張りを始めた")
        return got

    assert run(["--src", str(_fcs(root)), "--stop-session", "abc", "--wait", "0"]) == [0]
    assert capsys.readouterr().out.strip() == "STOPPED"
    assert run(["--src", str(_fcs(root)), "--stop-session", "zzz", "--wait", "0"]) == [0]
    assert capsys.readouterr().out.strip() == "OTHER"


def test_起動スクリプトは失敗したときにこの起動の控えを止める() -> None:
    """★RX-0170: 控えを立てたら印を付け、GUI が立っていない・終わったまま抜けるなら止める。"""
    code = "\n".join(_code_lines(_launcher()))
    assert "--stop-session $script:RetroUXSession" in code, "⚠ この起動の札で止めていない"
    start = code.index('$backupArgs = @("-m", "retroux.tools.dq2_savestate_backup"')
    assert "$script:BackupStartedHere = $true" in code[start:start + 400], \
        "⚠ 控えを立てたことを覚えていない（★立てていない控えは止めない）"
    gone = code.index("if ($gui.HasExited) {")
    assert "Stop-OwnDq2Backup" in code[gone:code.index("Stop-Launcher", gone) + 1], \
        "⚠ GUI がすぐ終わったとき、知らせる箱より先に控えを止めていない"
    tail = code[code.rindex("finally {"):]
    assert "if (-not $guiAlive) { Stop-OwnDq2Backup }" in tail, \
        "⚠ 途中で止まった起動（exit）でも控えを止める finally が無い"


# --- RX-0176: FCEUX のフォルダが無ければ fcs を作らない -----------------------------

def test_FCEUXのフォルダが無ければ見張り先を作らない(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ 以前は `parents=True` で、存在しない FCEUX のフォルダごと作って見張っていた（RX-0176）。"""
    _quiet_logging(monkeypatch, root)
    ghost = root / "no-such-fceux" / "fcs"
    assert B.main(["--src", str(ghost), "--once"]) == 1
    assert not ghost.parent.exists(), "⚠⚠ 存在しない FCEUX のフォルダを作った"


def test_FCEUXのフォルダがあれば見張り先だけ作る(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """★新しく展開した FCEUX は fcs がまだ無い（2026-08-20 UAT）→ 今までどおり作る。"""
    _quiet_logging(monkeypatch, root)
    (root / "fceux").mkdir()
    src = root / "fceux" / "fcs"
    assert B.main(["--src", str(src), "--once"]) == 0
    assert src.is_dir()
