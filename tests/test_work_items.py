"""Work Item 台帳の形を pytest からも見る（変更管理プロセス §40）。

## ⚠ なぜ pytest からも回すか

★checker を作っても、**誰も走らせなければ意味がない**。
⚠ この計画では「作ったが pytest から外れていて気づけなかった」を実際に踏んでいる
（Lua の挙動テストが pytest の外にあった / F-089 の周辺）。

## ★ ここで見ること

  1. 台帳が checker を通ること
  2. ⚠ **checker が空振りしていないこと**（★わざと壊して赤くなるか）
  3. 公開残件を抽出できること
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKER = PROJECT_ROOT / "scripts" / "check_work_items.py"
LEDGER = PROJECT_ROOT / "docs" / "10-work-items.md"
WORKFLOW = PROJECT_ROOT / "docs" / "11-change-workflow.md"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        encoding="utf-8", env={"PYTHONUTF8": "1", "PATH": ""}, timeout=60)


# --- 1. 台帳が通ること -----------------------------------------------------

def test_台帳がcheckerを通る():
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_台帳に少なくとも1件ある():
    done = _run("--summary")
    assert done.returncode == 0, done.stdout
    assert "Work Item:" in done.stdout


def test_公開残件を抽出できる():
    """★`Target=public-1.0` かつ `Status != DONE`（§41）。"""
    done = _run("--release", "public-1.0")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "public-1.0 の残件:" in done.stdout


# --- 2. ⚠⚠ 空振りしていないこと（★ここが要）------------------------------

@pytest.fixture
def broken(tmp_path):
    """本物の台帳を写して、わざと壊せるようにする。

    ⚠ **本物は触らない**（★過去に「わざと壊す道具」がコミットへ紛れた）。
    """
    def make(replace_from: str, replace_to: str) -> pathlib.Path:
        body = LEDGER.read_text(encoding="utf-8")
        assert replace_from in body, f"壊す対象が見つからない: {replace_from[:40]}"
        p = tmp_path / "broken.md"
        p.write_text(body.replace(replace_from, replace_to, 1), encoding="utf-8")
        return p
    return make


def test_不正なStatusを見つける(broken):
    """⚠ 壊す対象は**必ず在るもの**にする。

    ★以前は `Status: DOC-SYNC` を壊していたが、RX-0001 を DONE にした
      とたんに**対象が消えて空振り**した（2026-08-13）。
      → ★どの台帳にも必ずある `Status: NEW` を使う。
    """
    p = broken("Status: NEW", "Status: WORKING")
    done = _run("--ledger", str(p))
    assert done.returncode == 1, done.stdout
    assert "Status が不正" in done.stdout


def test_不正なVerificationを見つける(broken):
    p = broken("Verification: V1", "Verification: V9")
    done = _run("--ledger", str(p))
    assert done.returncode == 1, done.stdout


def test_DONEなのに残件があるのを見つける(broken):
    """⚠⚠ ★これが一番見落とす（§26）。

    ⚠ `Status: NEW` の項目は Acceptance が未完了なので、
      DONE に変えれば必ず引っかかる（★台帳の中身に依存しない）。
    """
    p = broken("Status: NEW", "Status: DONE")
    done = _run("--ledger", str(p))
    assert done.returncode == 1, done.stdout
    assert "Acceptance" in done.stdout


def test_REQUIREDなのに確認手順が無いのを見つける(broken):
    """⚠ 「一通り遊んで確認してください」を防ぐ（§24）。"""
    p = broken("User verification:\n1. RetroUX を起動して地図ウィンドウを開く",
               "（消した）")
    done = _run("--ledger", str(p))
    assert done.returncode == 1, done.stdout
    assert "User verification" in done.stdout


def test_必須の節が無いのを見つける(broken):
    """⚠ 「書き忘れ」と「不要と判断した」を区別するため（§14）。"""
    p = broken("Tests:\n- tests/test_work_items.py", "（消した）")
    done = _run("--ledger", str(p))
    assert done.returncode == 1, done.stdout


def test_IDの重複を見つける(tmp_path):
    body = LEDGER.read_text(encoding="utf-8")
    body += ("\n## RX-0001 かぶり\n\nType: BUG\nPriority: P1\n"
             "Target: public-1.0\nStatus: NEW\nVerification: V0\n"
             "UserCheck: NONE\n\nSummary:\nx\n\nSource:\n- x\n\n"
             "Tests:\n- x\n\nDocs:\n- x\n")
    p = tmp_path / "dup.md"
    p.write_text(body, encoding="utf-8")
    done = _run("--ledger", str(p))
    assert done.returncode == 1, done.stdout
    assert "ID が重複" in done.stdout


# --- 3. ⚠ ルールを複数文書へ写していないこと（§30）------------------------

def test_ルール本文を複製していない():
    """⚠⚠ 同じルールを2か所に書くと、★片方だけ古くなる。

    2026-08-12 の総監査で**何度も**確認された形。
    ★`CLAUDE.md` / `AGENTS.md` は**リンクだけ**を持つ。
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    # ★正本にしか無いはずの語（定義の本文）
    marks = ("V0` Static", "Definition of Done", "UserCheck（§20")
    for rel in ("CLAUDE.md", "AGENTS.md", "README.md"):
        body = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        for mark in marks:
            assert mark not in body, (
                f"{rel} に正本の本文が写っている: {mark!r}"
                "（★リンクだけにすること / §30）")
    assert all(m in workflow for m in marks), "正本に定義が無い"


def test_入口から辿れる():
    """★`CLAUDE.md` / `AGENTS.md` から新フローへ辿れること（§28・§29）。"""
    for rel in ("CLAUDE.md", "AGENTS.md"):
        body = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        assert "docs/11-change-workflow.md" in body, f"{rel} に導線が無い"
        assert "docs/10-work-items.md" in body, f"{rel} に台帳への導線が無い"

# --- ★★ 人が読む一覧（2026-08-18 / 依頼者の指摘）----------------------
#
#   > workitems のステータスが人間がみたらわかりずらいのだが、
#   > どこをどうみればいい？
#
# ⚠ `Status` / `Verification` / `UserCheck` は**機械と作業者のための欄**。
# ★`--todo` は「何をするか」「何を見るか」だけを出す。

def test_todoが人に見せる形になっている():
    from scripts.check_work_items import parse, todo

    items = parse(LEDGER.read_text(encoding="utf-8"))
    got = todo(items)
    assert "あなたがやること" in got
    # ⚠⚠ **英語のステータスを人に見せない**（★これが「分かりづらい」の正体）
    for word in ("USER-VERIFY", "IMPLEMENTING", "ANALYZED", "REQUIRED",
                 "Verification", "UserCheck", "V0", "V1", "V2", "V3"):
        assert word not in got, f"⚠ {word} が人向けの一覧に出ている"


def test_todoが実機確認を取りこぼさない():
    """★★★ ⚠⚠ **一度これで P1 を落とした**（2026-08-18）★★★

    `IMPLEMENTING` を「作業中だから人は待っていてよい」と外したら、
    ⚠ RX-0004（公開前チェックリストを実機で消化する）が**消えた**。
    ★あれは「実機で確かめること自体が依頼者の作業」。
    """
    from scripts.check_work_items import parse, todo

    items = parse(LEDGER.read_text(encoding="utf-8"))
    v3 = [it["id"] for it in items
          if it["fields"].get("Verification") == "V3"
          and it["fields"].get("UserCheck") == "REQUIRED"
          and it["fields"].get("Status") not in ("DONE", "WONTFIX", "DEFERRED")]
    got = todo(items)
    missing = [rid for rid in v3 if rid not in got]
    assert not missing, f"⚠ 実機でしか確かめられないものが漏れている: {missing}"


def test_todoは終わったものを出さない():
    """⚠ 鳴りすぎも壊れ方。★済んだものを並べない。"""
    from scripts.check_work_items import parse, todo

    items = parse(LEDGER.read_text(encoding="utf-8"))
    got = todo(items)
    done = [it["id"] for it in items
            if it["fields"].get("Status") == "DONE"]
    assert done, "★DONE が1件も無い（⚠ この検査の前提が崩れた）"
    shown = [rid for rid in done if rid in got]
    assert not shown, f"⚠ 終わったものが出ている: {shown}"


def test_todoは見るところを添えている():
    """★「何を見るか」が無いと、結局こちらに聞くことになる。"""
    from scripts.check_work_items import parse, todo

    items = parse(LEDGER.read_text(encoding="utf-8"))
    got = todo(items)
    assert "見るのはここだけ" in got, (
        "★Check only を出していない（⚠ 人が何を見ればよいか分からない）")
