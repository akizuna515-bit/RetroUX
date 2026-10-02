"""引き継ぎの誘いを**設定チェックより先に**出す（RX3-0481 / 2026-10-02）。

## ⚠⚠ 何が起きていたか（★実機で判明）

★利用者が ZIP を別のフォルダへ展開して `DQ3.cmd` を叩くと、
⚠ 「旧版から引き継ぎますか？」ではなく **「user_config.yaml を作りますか？」**が出た。

```text
⚠ 誘いは `dq3/ui/app.py` の中（★メイン画面を作る直前）
⚠⚠ ところが `start-dq3.ps1` の設定チェックが先にあり、見つからないと exit 1
→ ★`dq3.ui.app` に**永久に到達しない**（⚠ `should_offer()` は True だった）
```

⚠⚠ さらに、案内で雛形を作ると `user_config.yaml` が「既にある」で**飛ばされ**、
★旧版の ROM / FCEUX の場所が**引き継げない**（⚠ `outcome` が「一部完了」）。

## ★この検査が守るもの

⚠ 「`--migrate-offer-only` がある」だけでは弱い（★launcher が叩かなければ無意味）。
→ ★**順番**（誘い → 設定チェック）と、⚠ **終了コードの契約**を突き合わせます。
⚠⚠ `.ps1` に数字の意味を書き写していないこと（★正本は `dq3.migrate` の `EXIT_*`）も見ます。
"""

from __future__ import annotations

import io
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dq3 import migrate as MG  # noqa: E402

PS1 = ROOT / "scripts" / "start-dq3.ps1"


@pytest.fixture(scope="module")
def ps1() -> str:
    with io.open(PS1, encoding="utf-8-sig", newline="") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def qapp():
    """★画面外の `QApplication`（⚠ 窓は 1 つも `show()` しません）。

    ⚠ この計画には `pytest-qt` が入っていないので、★各検査が自分で用意します
      （`tests/test_dq3_migrate_dialog.py` と同じ形）。
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    got = QApplication.instance()
    yield got if got is not None else QApplication([])


# --- ★★ 順番（⚠ ここが今回の本体）------------------------------------------

def test_誘いは設定チェックより前にある(ps1):
    """⚠⚠ これが逆だと、設定の無い環境で**誘いに到達しません**。"""
    offer = ps1.find("--migrate-offer-only")
    gate = ps1.find("dq3.paths --fceux")
    assert offer > 0, "⚠ launcher が誘いの入口を叩いていません"
    assert gate > 0, "⚠ 設定チェックが見つかりません（★この検査は空回り）"
    assert offer < gate, (
        "⚠⚠ 誘いが設定チェックより**後ろ**にあります"
        "（★設定の無い環境では到達しません / RX3-0481）")


def test_設定の解決は誘いのあとで行う(ps1):
    """★引き継いだ設定がその回の起動で使われるには、⚠ **あとで**解決する必要がある。"""
    offer = ps1.find("--migrate-offer-only")
    for needle in ("dq3.paths --fceux", "dq3.paths --rom"):
        assert ps1.find(needle) > offer, (
            "⚠⚠ %s が誘いより前にあります（★引き継いだ設定が使われません）" % needle)


def test_失敗と一部完了では起動しない(ps1):
    """⚠⚠ 「結果と次の操作を見せて終了」（依頼者 2026-10-02 §2）。"""
    block = ps1[ps1.find("--migrate-offer-only"):ps1.find("dq3.paths --fceux")]
    for code in (MG.EXIT_PARTIAL, MG.EXIT_FAILED):
        got = re.search(r"^\s*%d\s*\{(.+?)^\s*\}" % code, block,
                        re.S | re.M)
        assert got, "⚠ 終了コード %d の枝がありません" % code
        assert "Fail " in got.group(1), (
            "⚠⚠ %d で起動を止めていません（★FCEUX と画面が起きてしまう）" % code)


def test_取り消しでは起動せず覚えも書かない(ps1):
    """★× / 取り消しは「今回は起動しない」。⚠ 次回また聞くこと（= 覚えを書かない）。"""
    block = ps1[ps1.find("--migrate-offer-only"):ps1.find("dq3.paths --fceux")]
    got = re.search(r"^\s*%d\s*\{(.+?)^\s*\}" % MG.EXIT_CANCELLED, block,
                    re.S | re.M)
    assert got, "⚠ 取り消しの枝がありません"
    assert "exit 0" in got.group(1), "⚠ 今回の起動を終わらせていません"
    assert "次回" in got.group(1), "⚠ 「次回また聞く」と言っていません"


def test_知らない終了コードでは黙って続行しない(ps1):
    """⚠⚠ 引き継ぎ画面の起動エラーを、★通常起動で飲み込まないこと。"""
    block = ps1[ps1.find("--migrate-offer-only"):ps1.find("dq3.paths --fceux")]
    got = re.search(r"^\s*default\s*\{(.+?)^\s*\}", block, re.S | re.M)
    assert got, "⚠ `default` の枝がありません（★知らないコードが素通りします）"
    assert "Fail " in got.group(1), "⚠⚠ 黙って続行しています"


def test_続行してよいコードだけが続行の枝にある(ps1):
    """★`EXIT_CONTINUE` と `.ps1` の枝がずれていないこと（⚠ 片方だけ直る形を止める）。"""
    block = ps1[ps1.find("--migrate-offer-only"):ps1.find("dq3.paths --fceux")]
    handled = {int(m) for m in
               re.findall(r"^\s*(\d+)\s*\{[^{}]*migrateHandled = \$true",
                          block, re.M)}
    assert handled == set(MG.EXIT_CONTINUE), (
        "⚠⚠ 続行する枝 %s が `migrate.EXIT_CONTINUE` %s と違います"
        % (sorted(handled), sorted(MG.EXIT_CONTINUE)))


def test_数字の意味をps1に書き写していない(ps1):
    """⚠⚠ 契約の**正本は 1 つ**（★`dq3/migrate.py` の `EXIT_*`）。

    ⚠ `.ps1` には数字しか無く、★意味は註とこの検査で結びます。
      （`docs/11-change-workflow.md` の「同じ判定を 2 か所に書かない」）
    """
    assert "EXIT_MIGRATED" not in ps1 and "EXIT_CANCELLED" not in ps1, (
        "⚠ `.ps1` が Python の名前を参照しています（★PowerShell からは読めません）")
    assert "dq3/migrate.py" in ps1, "⚠ 正本の場所を註に書いていません"


# --- ★二重表示を防ぐ ---------------------------------------------------------

def test_誘いを処理したら画面側では出さない(ps1):
    """⚠⚠ 依頼者 2026-10-02 §3（★案内の二重表示）。"""
    at = ps1.find("if (-not $NoUi) {")
    assert at > 0, "⚠ 画面の起動が見つかりません"
    tail = ps1[at:at + 700]
    assert "--no-migrate-offer" in tail, (
        "⚠⚠ 画面の起動に `--no-migrate-offer` を渡していません（★二度出ます）")
    assert "$migrateHandled" in tail, (
        "⚠ 無条件に渡しています（★誘いを処理していないときは出せるべきです）")


def test_管理からの導線は塞いでいない():
    """★あとから呼ぶ道は残す（依頼者 2026-10-01 §1 / ⚠ ここを壊さない）。

    ⚠ `--no-migrate-offer` は**初回の誘い**だけを止めます。★［管理］からは
      `MigrateDialog` を直に作るので、⚠ いつでも呼べます。
    """
    admin = (ROOT / "dq3" / "ui" / "admin_window.py").read_text(encoding="utf-8")
    assert "MigrateDialog" in admin, (
        "⚠⚠ 管理画面からの引き継ぎの導線が見つかりません")
    # ⚠⚠ 字面では見ません（★`should_offer` は註にも出ます / 2026-10-02 に踏んだ）。
    #   ★AST で「**呼んでいる名前**」だけを集めます。
    import ast

    called = set()
    for node in ast.walk(ast.parse(admin)):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name:
                called.add(name)
    assert "should_offer" not in called, (
        "⚠⚠ 管理画面が誘いの条件を**呼んで**います（★一度断ったら呼べなくなります）")
    assert "offer_if_first_run" not in called, (
        "⚠⚠ 管理画面が `offer_if_first_run` を使っています"
        "（★あれは条件を見るので、⚠ 断ったあとは何も出ません）")
    assert "MigrateDialog" in called, (
        "⚠ 管理画面が `MigrateDialog` を**作って**いません（★字面だけ在る状態）")


# --- ⚠⚠ 本文が見ている switch が param() に在ること --------------------------

def test_本文が見ているswitchは全部宣言されている(ps1):
    """⚠⚠ 2026-10-02 に `$NoBackup` が**未宣言**で見つかりました。

    ```text
    ⚠ 本文        if (-not $NoBackup) { … }
    ⚠⚠ param()    **無かった**
    → ★`-NoBackup` を付けても黙って無視され（`$args` へ捨てられ）、
      ⚠ 未宣言の変数は $null なので「控えは必ず起きる」ままでした。
    ```

    ★`[CmdletBinding()]` の無い .ps1 は知らない引数を捨てます（`RX-0132`）。
    → ⚠ 字面では気づけないので、**機械で突き合わせます**。
    """
    head = ps1[:ps1.find(")\n", ps1.find("param("))]
    declared = {m.lower() for m in re.findall(r"\[switch\]\$(\w+)", head)}
    declared |= {m.lower() for m in re.findall(r"\[string\]\$(\w+)", head)}
    used = {m.lower() for m in re.findall(r"-not\s+\$(\w+)\b", ps1)}
    used |= {m.lower() for m in re.findall(r"if\s*\(\s*\$(\w+)\s*\)", ps1)}
    # ⚠ 本文で作っている変数は除く（★`param()` の話ではない）
    local = {m.lower() for m in re.findall(r"^\s*\$(\w+)\s*=", ps1, re.M)}
    #: ⚠ PowerShell が自分で持っているもの（★`param()` の話ではない）
    builtin = {"null", "true", "false", "args", "psscriptroot", "pscommandpath",
               "error", "lastexitcode", "host", "pwd"}
    missing = sorted(used - declared - local - builtin)
    assert not missing, (
        "⚠⚠ 本文が見ているのに `param()` に無い: %s"
        "（★指定しても黙って無視されます）" % missing)


# --- ★終了コードを決めるところ -----------------------------------------------

class _Dlg:
    def __init__(self, declined=False, result=None):
        self.declined = declined
        self.result_of_run = result


def _result(outcome):
    skipped = ("x",) if outcome == MG.OUT_PARTIAL else ()
    failed = ("y",) if outcome == MG.OUT_FAILED else ()
    return MG.Result(ok=not failed, copied=1, size=1, skipped=skipped,
                     failed=failed, journal=None)


def test_結末ごとの終了コード(qapp):
    from dq3.ui.migrate_dialog import exit_code_for

    assert exit_code_for(None) == MG.EXIT_NOT_NEEDED
    assert exit_code_for(_Dlg(declined=True)) == MG.EXIT_DECLINED
    assert exit_code_for(_Dlg()) == MG.EXIT_CANCELLED, (
        "⚠ 窓を × で閉じたときに「引き継いだ」と言っています")
    assert exit_code_for(_Dlg(result=_result(MG.OUT_OK))) == MG.EXIT_MIGRATED
    assert exit_code_for(_Dlg(result=_result(MG.OUT_PARTIAL))) == MG.EXIT_PARTIAL
    assert exit_code_for(_Dlg(result=_result(MG.OUT_FAILED))) == MG.EXIT_FAILED


def test_終了コードは互いに違う():
    """⚠ 1 つでも重なると launcher が区別できません。"""
    codes = [MG.EXIT_NOT_NEEDED, MG.EXIT_MIGRATED, MG.EXIT_DECLINED,
             MG.EXIT_CANCELLED, MG.EXIT_PARTIAL, MG.EXIT_FAILED]
    assert len(set(codes)) == len(codes), codes
    assert 1 not in codes and 2 not in codes, (
        "⚠⚠ 1 / 2 は Python と argparse の失敗で出ます（★意味を持たせない）")


# --- ★利用者データを作らずに抜ける ------------------------------------------

def test_誘いだけの道はViewModelを作らない():
    """⚠⚠ 作ると設定や記録の初期値が出来て、★そのあと引き継げません（実測）。"""
    src = (ROOT / "dq3" / "ui" / "app.py").read_text(encoding="utf-8")
    at_offer = src.find("if args.migrate_offer_only:")
    at_vm = src.find("vm = Dq3ViewModel(")
    assert at_offer > 0 and at_vm > 0
    assert at_offer < at_vm, (
        "⚠⚠ `--migrate-offer-only` が `Dq3ViewModel` より後ろにあります"
        "（★利用者データが先に出来ます / RX3-0481）")


def test_誘う必要が無ければQtを触らない(monkeypatch, tmp_path):
    """★通常起動を遅くしない（⚠ `should_offer()` が偽なら窓の道へ行かない）。"""
    from dq3.ui import app as A

    monkeypatch.setattr(MG, "should_offer", lambda *a, **k: False)

    def _boom(*a, **k):                                  # pragma: no cover
        raise AssertionError("⚠⚠ Qt を触りました")

    monkeypatch.setitem(sys.modules, "dq3.ui.migrate_dialog", None)
    monkeypatch.setattr(A, "_migrate_offer_only",
                        A._migrate_offer_only)           # ★本物を使う
    assert A._migrate_offer_only() == MG.EXIT_NOT_NEEDED


# --- ★旧版への絶対パスの案内（依頼者 2026-10-02 §4）-------------------------

def test_旧版を指す設定は4つのことを言う(tmp_path):
    from dq3.ui.migrate_dialog import result_text

    alive = tmp_path / "old" / "DQ3_J.nes"
    alive.parent.mkdir(parents=True, exist_ok=True)
    alive.write_bytes(b"x")
    stale = [("dq3_rom", str(alive), "⚠⚠ 旧版フォルダの中を指しています。"
                                     "★旧版を消すと使えなくなるので、"
                                     "⚠ 新版で場所を選び直してください"),
             ("fceux", str(tmp_path / "old" / "ない.exe"), "⚠ 同上")]
    got = result_text(_result(MG.OUT_OK), stale)
    assert "DQ3 の ROM" in got, "⚠ ROM / FCEUX のどちらかが分からない"
    assert "FCEUX" in got
    assert str(alive) in got, "⚠ いまの参照先を出していない"
    assert "旧版を消すと使えなくなる" in got, "⚠ 消すと使えなくなることを言っていない"
    assert "選び直して" in got, "⚠ 選び直す必要を言っていない"
    assert "書き換えていません" in got, "⚠ 黙って書き換えないことを言っていない"
    # ★在る / 無いで言うことが変わる
    assert "★使えます" in got and "**使えません**" in got, got


def test_旧版を指す設定が無ければ何も言わない():
    from dq3.ui.migrate_dialog import result_text

    got = result_text(_result(MG.OUT_OK), [])
    assert "選び直して" not in got


def test_欄の名前の表はmigrateの一覧と揃っている():
    """⚠ 片方だけ増えると、★新しい欄が「生の名前」で出ます。"""
    from dq3.ui.migrate_dialog import STALE_LABELS

    assert set(STALE_LABELS) == set(MG.OUTSIDE_KEYS), (
        "⚠⚠ `STALE_LABELS` %s と `migrate.OUTSIDE_KEYS` %s がずれています"
        % (sorted(STALE_LABELS), sorted(MG.OUTSIDE_KEYS)))
