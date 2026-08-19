"""セーブステートバックアップの二重起動チェック（MVP2 Phase 1）。

★なぜ硬くするか:
  2つ動くと**同じ変更を両方が世代に回す**。世代数は決まっているので
  倍の速さで流れ、**戻りたい世代が押し出される**。
  このツールが守っているのは「取り返しのつかない事故」なので、
  守るはずの仕組み自身が事故を起こしてはいけない。
"""

from __future__ import annotations

import pytest

from retroux.core.single_instance import AlreadyRunningError, RecorderLock


def test_second_start_is_refused(tmp_path):
    lock = RecorderLock(tmp_path / "savestate_backup.lock",
                        description="セーブステートのバックアップ",
                        consequence="2つ動くと世代が倍の速さで流れます。")
    lock.acquire()

    other = RecorderLock(tmp_path / "savestate_backup.lock",
                         description="セーブステートのバックアップ")
    with pytest.raises(AlreadyRunningError) as exc:
        other.acquire()

    # ★「何が起きるか」がメッセージに入っていること。
    #   「別のプロセスが動いています」だけでは、無視してよいのか判断できない。
    assert "セーブステートのバックアップ" in str(exc.value)


def test_message_differs_per_role(tmp_path):
    """役目ごとに違う結果を伝える（同じ文面を使い回さない）。"""
    ingest = RecorderLock(tmp_path / "a.lock")
    ingest.acquire()
    with pytest.raises(AlreadyRunningError) as exc:
        RecorderLock(tmp_path / "a.lock").acquire()
    assert "戦闘が二重に記録されます" in str(exc.value)


def test_force_overrides(tmp_path):
    lock = RecorderLock(tmp_path / "b.lock")
    lock.acquire()
    # ★承知の上で重ねる道は残す（検証時に使う）
    RecorderLock(tmp_path / "b.lock").acquire(force=True)


def test_stale_lock_is_released(tmp_path):
    """異常終了で残ったロックでは止まらない（心拍で判定するため）。

    ★時計を差し替えるのではなく、**ロックファイルを古くする**。
      time.time を差し替えたら、置き換えた関数が自分を呼んで無限再帰した。
      「いま何時か」を偽るより、「古い心拍」という状態そのものを作るほうが安全。
    """
    import os

    from retroux.core.single_instance import HEARTBEAT_STALE_SECONDS

    path = tmp_path / "c.lock"
    lock = RecorderLock(path)
    lock.acquire()

    old = os.stat(path).st_mtime - HEARTBEAT_STALE_SECONDS - 1
    os.utime(path, (old, old))

    RecorderLock(path).acquire()   # 例外にならない


def test_backup_lock_path_is_separate():
    """取り込みのロックと**別のファイル**であること（片方が他方を止めない）。"""
    from retroux.core.config.user_config import UserConfig

    cfg = UserConfig()
    assert cfg.path("lock") != cfg.path("backup_lock")
    assert cfg.path("backup_lock").name == "savestate_backup.lock"
