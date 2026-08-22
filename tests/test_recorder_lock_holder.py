"""ロックを握っている相手を言う／死んだ相手には譲る（RX-0064 / 2026-08-22）。

★実機で「終了ボタンで『保存して終了』が押せない」が起きた。原因は閉じ切らずに
  起動し直して古い pythonw が生き残っていたこと。判定は正しいのに、
  ⚠ **誰のせいで閲覧専用なのか**が画面にもログにも出ていなかった。

⚠ ここでは**何も殺さない**（README §219 の懸念）。掃除は「相手が死んでいたら
  引き継ぐ」だけ。
"""

from __future__ import annotations

import json
import os
import pathlib

from retroux.core import process_probe
from retroux.core.single_instance import AlreadyRunningError, RecorderLock


def test_ロックにPIDと実行ファイル名とセッションを書く(tmp_path):
    lock = RecorderLock(tmp_path / "a.lock", session="s1")
    lock.touch()
    got = json.loads((tmp_path / "a.lock").read_text(encoding="utf-8"))
    assert got["pid"] == os.getpid()
    assert got["image"] == process_probe.current_image_name()
    assert got["session"] == "s1"


def test_古い形式のPIDだけのロックも読める(tmp_path):
    """⚠ 2026-08-22 より前のロックが残っていても壊れない。"""
    p = tmp_path / "b.lock"
    p.write_text("4321", encoding="utf-8")
    assert RecorderLock(p).read() == {"pid": 4321}
    p.write_text("こわれている", encoding="utf-8")
    assert RecorderLock(p).read() == {}


def test_誰が握っているかを1行で言える(tmp_path):
    lock = RecorderLock(tmp_path / "c.lock", session="s9")
    lock.touch()
    said = lock.holder().describe()
    assert str(os.getpid()) in said
    assert "s9" in said and "最終心拍" in said


def test_死んだプロセスのロックは心拍が新しくても譲る(tmp_path):
    """★ここが実害の中心。⚠ 落ちた直後の 10 秒間、後発が理由もなく閲覧専用だった。"""
    p = tmp_path / "d.lock"
    p.write_text(json.dumps({"pid": 999_999, "image": "pythonw.exe"}), encoding="utf-8")
    lock = RecorderLock(p)
    assert lock.holder().alive is False
    assert lock.is_active() is False
    lock.acquire()                       # ★例外にならない（引き継げる）
    assert lock.read()["pid"] == os.getpid()


def test_生きている相手には譲らずに理由を言う(tmp_path):
    lock = RecorderLock(tmp_path / "e.lock", session="s2")
    lock.touch()                         # ★自分（= 生きているプロセス）が握る
    assert lock.is_active() is True
    try:
        RecorderLock(tmp_path / "e.lock").acquire()
    except AlreadyRunningError as exc:
        assert str(os.getpid()) in str(exc), exc
    else:
        raise AssertionError("★生きている相手なのに acquire が通った")


def test_PIDの使い回しを実行ファイル名で見抜く(tmp_path):
    """⚠ Windows は PID を使い回す。★別のプロセスを「記録役」と思い込まない。"""
    p = tmp_path / "f.lock"
    p.write_text(json.dumps({"pid": os.getpid(), "image": "notepad.exe"}),
                 encoding="utf-8")
    assert RecorderLock(p).is_active() is False
    assert process_probe.alive(os.getpid(), process_probe.current_image_name()) is True


def test_確かめられないときは心拍で判断する(tmp_path, monkeypatch):
    """⚠ Windows 以外・API が呼べない環境で「居ない」と決めつけない。"""
    monkeypatch.setattr(process_probe, "alive", lambda *a, **k: None)
    p = tmp_path / "g.lock"
    p.write_text(json.dumps({"pid": 999_999, "image": "pythonw.exe"}), encoding="utf-8")
    assert RecorderLock(p).is_active() is True      # ★心拍は新しい


def test_掃除はしない(tmp_path):
    """⚠⚠ **殺す道具を置かない**（README §219: 取り違えて別の回を殺す恐れ）。"""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "retroux" / "core" / "process_probe.py").read_bytes().decode("utf-8")
    for banned in ("TerminateProcess", "taskkill", "os.kill", "subprocess"):
        assert banned not in src, f"★{banned} を置かない"


# --- ⚠ 実機で「何も変わらない」と言われた件（2026-08-22 / RX-0064）------------
#
# ★閲覧専用にするか決めているのは起動スクリプト（start-retroux.ps1）のほうで、
#   GUI には最初から `--read-only` が渡ってくる。⚠ ロック取得の失敗経路だけを
#   見ていたので、**理由が1行も出なかった**。決めたのが誰であれ調べる。

def test_read_only_で来ても記録役を調べる(tmp_path):
    from retroux.gui import read_only_because

    p = tmp_path / "h.lock"
    holder = RecorderLock(p, session="s3")
    holder.touch()                       # ★生きているプロセスが握っている
    said = read_only_because(RecorderLock(p), read_only=True)
    assert said and str(os.getpid()) in said and "s3" in said


def test_記録中なら理由を作らない(tmp_path):
    """★自分が記録役のときに「別の誰かが居る」と言わない。"""
    from retroux.gui import read_only_because

    lock = RecorderLock(tmp_path / "i.lock")
    lock.touch()
    assert read_only_because(lock, read_only=False) is None


def test_誰も握っていなければ理由を作らない(tmp_path):
    """⚠ 人が `--read-only` を明示しただけのとき、居ない相手のせいにしない。"""
    from retroux.gui import read_only_because

    assert read_only_because(RecorderLock(tmp_path / "j.lock"), read_only=True) is None


def test_起動スクリプトが記録役を出している():
    """⚠ 道具を作っただけで呼んでいない、をやらない（★今回まさにそれだった）。"""
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "start-retroux.ps1").read_bytes().decode("utf-8")
    assert '"status", "--who"' in src, "★起動スクリプトが実際に呼んでいること"
    assert "記録役: " in src


# --- 2枚目の GUI は開かない（RX-0064 / 依頼者の判断 a / 2026-08-22）-------------
#
# ⚠ 二重起動のとき FCEUX もセーブステート保護も起動を飛ばすので、開くのは
#   **記録も保存もしない空の窓**でしかなかった。★開かずに理由を言って終わる。

def _launcher_text() -> str:
    return (pathlib.Path(__file__).resolve().parents[1]
            / "scripts" / "start-retroux.ps1").read_bytes().decode("utf-8-sig")


def test_記録役が居たら閲覧専用で開かずに止める():
    src = _launcher_text()
    i = src.index('$lockCheck.Trim() -eq "BUSY"')
    block = src[i:i + 1800]
    assert "Stop-Launcher" in block, "★2枚目を開かずに止める"
    assert "記録役: " in block, "⚠ 誰が握っているかをメッセージに入れる"
    # ★逃げ道（-ReadOnly）は**ログにだけ**書く。⚠ VBS から渡せないものを
    #   ダイアログに書くと、できないことを勧めることになる（2026-08-22 依頼者）。
    assert "-ReadOnly（開発用）" in block
    # ⚠ 以前はここで $ReadOnly = $true にして開いていた。★戻していないこと
    assert "$ReadOnly = $true" not in block


def test_日本語は標準出力ではなくファイルで受け取る():
    """⚠⚠ PowerShell 5.1 は native exe の出力を cp932 で復号する（実測で化けた）。

    ★`[Console]::OutputEncoding` の差し替えは、コンソールが無い起動で効かない
      ことを実測した（2026-08-22）。**ファイル経由が確実**。
    """
    common = (pathlib.Path(__file__).resolve().parents[1]
              / "scripts" / "launcher-common.ps1").read_bytes().decode("utf-8-sig")
    assert "function Get-PythonText" in common
    assert "-Encoding UTF8" in common, "★読むときに符号化を明示する"
    assert "$lockWho = Get-PythonText" in _launcher_text()


def test_whoの結果をUTF8でファイルへ書ける(tmp_path):
    from retroux.tools.session import status

    lock_dir = tmp_path / "work"
    lock_dir.mkdir()
    out = tmp_path / "who.txt"
    # ★実際の user_config を使う（⚠ ここは「書けること」だけを見る）
    assert status(None, "ingest", who=True, out=str(out)) == 0
    said = out.read_text(encoding="utf-8")
    assert said and "�" not in said
