"""DQ2 と DQ3 の実行環境が重ならない（RX-0150 / Phase 1 の完了マトリクスの自動の列 / D-42）。

★依頼者「Phase 1 完了条件」の確認内容（`docs/requests/261003_dq2-brushup-next-phase.md` §4）:

  相手の backup を止めない / 相手の savestate を削除しない / 相手の generation count を使わない /
  相手の command・state を書き換えない / 相手の log を書き換えない

★ここは「**同じ場所を指していない**」ことを、両製品の場所の決め方から直接見ます
（⚠ 文字列ではなく、実際に使う関数・定数から取る）。
★動きそのもの（止まらない・削らない）は各 WI の検査が見ています:

```text
控え          tests/test_dq2_savestate_backup.py（DQ3 の stop で止まらない・DQ3 の世代を削らない）
              tests/test_dq3_savestate_backup.py（DQ3 の控えは DQ2_J を写さない）
窓            tests/test_dq2_window_align.py / tests/test_dq3_fceux_windows.py
生成物        tests/test_playdata.py（DQ3 の生成物を消さない）
設定・ログ    tests/test_dq2_user_config.py
```

⚠ 実機でしか見られないもの（起動の順・終了の仕方・同時に遊ぶ）は `docs/user-check/2026-10-03-dq2-dq3-isolation.md`。
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import pytest

from retroux.core import backup_status, dq2_paths
from retroux.core.config import dq2_user_config
from retroux.core.config import user_config as shared_config
from retroux.tools import dq2_savestate_backup as dq2_backup

dq3_paths = pytest.importorskip("dq3.paths")


@pytest.fixture()
def write_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """★両製品の書き先の根を同じ一時フォルダへ（⚠ 開発 repo では実際に同じ根を共有する）。"""
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    return tmp_path


def _norm(p) -> str:
    return os.path.normcase(str(Path(p)))


def _dq2_cfg(root: Path):
    cfg, _ = dq2_user_config.load(root=root / "no-config-here")
    return cfg


def _dq2_files(root: Path) -> dict[str, Path]:
    """★DQ2 が実行時に書く・読む主な場所（★相対の設定は write_root から見る = DQ3 と同じ根で比べる）。"""
    cfg = _dq2_cfg(root)
    work = root / "work"
    return {
        "state": root / cfg.paths.state,
        "command": root / cfg.paths.command,
        "events": dq2_paths.events(),                      # ★RX-0162: Lua と Python の正本
        "gamepad": work / "gamepad_input.txt",            # ★bridge.lua の固定名
        "log": root / cfg.paths.log,
        "backup_lock": dq2_backup.lock_path(),
        "backup_stop": dq2_backup.stop_path(),
        "backup_status": backup_status.status_path(dq2_backup.lock_path()),
        "backup_dst": dq2_backup.default_dst(),
        "config": dq2_user_config.config_path(),           # ★どちらもプログラムの直下に置く
    }


def _dq3_files(root: Path) -> dict[str, Path]:
    """★DQ3 が実行時に書く・読む主な場所。"""
    shared = shared_config.PathsConfig()
    return {
        "state": dq3_paths.runtime("state.json"),
        "command": dq3_paths.runtime("dq3-command.json"),
        "gamepad": dq3_paths.runtime("dq3-gamepad.txt"),
        "log_product": dq3_paths.runtime("dq3-log", "product.log"),
        "log_backup_note": dq3_paths.runtime("dq3-log", "savestate-backup.log"),
        "log_backup_engine": root / shared.log,          # ★DQ3 の控え（共有 engine）は paths.log へ書く
        "backup_lock": root / shared.backup_lock,
        "backup_stop": (root / shared.backup_lock).with_suffix(".stop"),
        "backup_status": backup_status.status_path(root / shared.backup_lock),
        "backup_dst": root / "work" / "savestate-backup",
        "config": shared_config.USER_CONFIG_PATH,
    }


def test_DQ2とDQ3の場所が1つも重ならない(write_root: Path) -> None:
    dq2 = {k: _norm(v) for k, v in _dq2_files(write_root).items()}
    dq3 = {k: _norm(v) for k, v in _dq3_files(write_root).items()}
    shared = sorted(set(dq2.values()) & set(dq3.values()))
    pairs = [(a, b) for a, x in dq2.items() for b, y in dq3.items() if x == y]
    assert not shared, f"⚠ 同じ場所を指している: {pairs}"


def test_控えのフォルダもDQ3と別(write_root: Path) -> None:
    """⚠ 状態ファイルの名前は固定（savestate_backup.status.json）なので、フォルダごと別でないと衝突する。"""
    dq2 = _dq2_files(write_root)
    dq3 = _dq3_files(write_root)
    assert dq2["backup_lock"].parent != dq3["backup_lock"].parent
    assert not _norm(dq2["backup_dst"]).startswith(_norm(dq3["backup_dst"]) + os.sep)


def test_設定ファイルの名前が違う() -> None:
    assert dq2_user_config.config_path().name == "dq2_user_config.yaml"
    assert shared_config.USER_CONFIG_PATH.name == "user_config.yaml"


@pytest.mark.parametrize("name", [
    "DQ2_J.fc0", "DQ2_J.fc9", "DQ2_J.fcs", "DQ2_J-bak.fc0",
    "DQ3_J.fc0", "DQ3_J.fc9", "DQ3_J.fcs", "DQ3_J-bak.fc1",
])
def test_セーブの見張りは片方の製品だけが拾う(name: str) -> None:
    from dq3 import savestate_backup as dq3_backup

    dq2_hit = any(fnmatch.fnmatch(name, p) for p in dq2_backup.patterns_for("DQ2_J"))
    dq3_hit = any(fnmatch.fnmatch(name, p) for p in dq3_backup.dq3_patterns(Path("DQ3_J.nes")))
    assert dq2_hit != dq3_hit, f"⚠ {name}: DQ2={dq2_hit} DQ3={dq3_hit}（★どちらか片方だけ）"
    assert dq2_hit == name.startswith("DQ2_J")


def test_DQ2のFCEUXの既定はDQ3と同じでも設定で分けられる(tmp_path: Path) -> None:
    """★開発 repo では共有 tools/fceux を許す（J6）。★設定を書けば DQ2 だけ別の FCEUX になる。"""
    cfg = _dq2_cfg(tmp_path)
    cfg.paths.fceux = str(tmp_path / "fceux-dq2" / "fceux64.exe")
    assert dq2_paths.fcs_dir(cfg) == tmp_path / "fceux-dq2" / "fcs"
