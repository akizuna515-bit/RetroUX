"""引き継ぎの窓（RX3-0471 / 2026-10-01）。

## ⚠⚠ ここで見ないもの

★**本物のフォルダ選択ダイアログと、人の画面操作は見ません。**
⚠ `QFileDialog` はモーダルで、画面外 Qt では `RX3-0258` の穴（見せていない欄への
入力で Python ごと落ちる）を踏みます。→ ★`ask_folder` / `confirm` / `show_result`
を差し替えます（⚠ 依頼者の了承済み / 実機確認に残す）。

## ★ここで見るもの

```text
① ⚠⚠ 窓が**コピー対象の一覧を持っていない**（★`ownership` / `migrate` だけ）
② ★道を入れると見立てが出て、⚠ 駄目なフォルダでは「引き継ぐ」が押せない
③ ⚠ キャンセルで 1 バイトも書かない
④ ⚠⚠ 完了 / 一部完了 / 失敗が**同じ顔にならない**
⑤ ★「引き継がず開始」を覚えて、次からは誘わない
⑥ ⚠ あとから呼べる道が画面にある
```
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib

import pytest

from dq3 import migrate as MG
from dq3 import ownership as OWN

ROOT = pathlib.Path(__file__).resolve().parents[1]

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from dq3.ui import migrate_dialog as MD  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    """★画面外の `QApplication`（⚠ 窓は 1 つも `show()` しません）。"""
    got = QApplication.instance()
    yield got if got is not None else QApplication([])


@pytest.fixture(autouse=True)
def _never_block(monkeypatch):
    """★★ ⚠⚠ **本物のモーダル窓に入らせない**（2026-10-01 に踏んだ）★★

    ## ⚠⚠ 何が起きたか

    ★壊す実験で「キャンセルでも走る」を当てたとき、`_on_migrate()` が
    ⚠ 差し替えていない `show_result()` まで進み、
    ⚠⚠ **本物の `QMessageBox.exec()` が画面外で入力を待って止まりました**
    （★検査は「赤」でも「緑」でもなく **無反応**。40 分走り続けました）。

    ⚠ これは `RX3-0258`（画面外 Qt の落とし穴）と同じ形です。
    → ★だから `exec()` 自体を**この検査ファイル全体で**塞ぎます。
      ⚠ 1 件ずつ差し替える形にすると、**差し替え忘れた道が止まります**。
    """
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(MD.MigrateDialog, "exec", lambda self: 0)
    monkeypatch.setattr(
        MD, "ask_folder",
        lambda parent=None, start="": pytest.fail(
            "⚠⚠ 本物のフォルダ選択ダイアログを開こうとしました"
            "（★検査では `ask_folder` を差し替えてください）"))


def _snapshot(root: pathlib.Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _old(root: pathlib.Path) -> pathlib.Path:
    """★「遊んだあとの旧版」（⚠ 8 分類すべてを入れる）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "dq3").mkdir(exist_ok=True)
    (root / "dq3" / "paths.py").write_bytes(b"# program\n")
    (root / "DQ3.cmd").write_bytes(b"@echo off\r\n")
    (root / "build-info.json").write_text(
        json.dumps({"product": "retroux-dq3", "version": "1.1.0",
                    "source_commit": "abc1234"}), encoding="utf-8")
    (root / "user_config.yaml").write_bytes(b"paths: {}\n")
    work = root / "work"
    for rel in ("dq3-knowledge", "savestate-backup", "playdata-archive",
                "rom", "user-data"):
        (work / rel).mkdir(parents=True, exist_ok=True)
    (work / "dq3-knowledge" / "memos.jsonl").write_bytes(b'{"m":1}\n')
    (work / "savestate-backup" / "DQ3_J.fc1.1").write_bytes(bytes(64))
    (work / "playdata-archive" / "seen.json").write_bytes(b"{}\n")
    (work / "rom" / "DQ3_J.nes").write_bytes(b"NES\x1a")
    # ⚠ 空のフォルダは写りません（★中身が無いので運ぶものが無い）→ 1 つ置く
    (work / "user-data" / "config").mkdir(parents=True, exist_ok=True)
    (work / "user-data" / "config" / "dq3_phase0.yaml").write_bytes(b"keys: mine\n")
    (work / "dq3-ui-settings.json").write_bytes(b'{"t":2}\n')
    (work / "dq3-window-state.json").write_bytes(b'{"x":1}\n')
    return root


def _new(root: pathlib.Path) -> pathlib.Path:
    """★「新しい ZIP を空のフォルダへ展開した直後」（⚠ work/ は無い）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "dq3").mkdir(exist_ok=True)
    (root / "dq3" / "paths.py").write_bytes(b"# program 1.2.0\n")
    (root / "DQ3.cmd").write_bytes(b"@echo off\r\n")
    (root / "build-info.json").write_text(
        json.dumps({"product": "retroux-dq3", "version": "1.2.0",
                    "source_commit": "def5678"}), encoding="utf-8")
    return root


@pytest.fixture()
def pair(tmp_path):
    return _old(tmp_path / "RetroUX-DQ3-1.1.0"), _new(tmp_path / "RetroUX-DQ3-1.2.0")


@pytest.fixture()
def dlg(qapp, pair):
    """★窓（⚠ 出しません / `exec()` を呼びません）。"""
    _old_root, new = pair
    got = MD.MigrateDialog(dst=new)
    yield got
    got.deleteLater()


# --- ★★ ⚠⚠ ① 窓は一覧を持たない ★★ --------------------------------

def test_窓はコピー対象の一覧を持っていない():
    """⚠⚠ **GUI に別のコピー対象一覧を持たせない**（依頼者 2026-10-01 §1）。

    ★`work/...` のような**置き場の名前**が窓のソースに出てこないこと。
    ⚠ 出てきたら、`ownership` を直しても画面が古いままになります。
    """
    src = (ROOT / "dq3" / "ui" / "migrate_dialog.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]        # ★説明（docstring）は除く
    # ⚠ 見るのは **相対パスそのもの**（★`work/rom` の `rom` だけだと `from` に当たる）
    for entry in OWN.USER_DATA:
        assert entry.rel not in body, (
            "⚠⚠ 窓が置き場の名前を持っています: %s（★`ownership` を見てください）"
            % entry.rel)
    for spec in OWN.USER_OVERRIDE:
        assert spec.rel not in body, (
            "⚠⚠ 窓が override の一覧を持っています: %s" % spec.rel)


def test_窓が出す言葉はmigrateのもの(dlg, pair):
    old, _new = pair
    dlg.edit.setText(str(old))
    body = dlg.view.toPlainText()
    assert body == MG.summary(MG.probe(old, dlg._dst),
                              MG.conflicts(old, dlg._dst),
                              MG.stale_references(old, dlg._dst))


# --- ★ ② 見立てとボタン ---------------------------------------------

def test_空のときは押せない(dlg):
    assert dlg.b_migrate.isEnabled() is False
    assert dlg.view.toPlainText() == ""


def test_正しい旧版を入れると押せる(dlg, pair):
    old, _new = pair
    dlg.edit.setText(str(old))
    assert dlg.b_migrate.isEnabled() is True
    body = dlg.view.toPlainText()
    assert "retroux-dq3 1.1.0 が見つかりました" in body
    assert "引き継ぐもの:" in body


def test_駄目なフォルダは押せず理由が出る(dlg, tmp_path):
    wrong = tmp_path / "Documents"
    wrong.mkdir()
    dlg.edit.setText(str(wrong))
    assert dlg.b_migrate.isEnabled() is False
    body = dlg.view.toPlainText()
    assert "引き継げません" in body
    for rel, _why in MG.ROOT_MARKERS:
        assert rel in body, "⚠ %s が足りないことを言っていません" % rel


def test_自分自身を指すと押せない(dlg, pair):
    _old_root, new = pair
    dlg.edit.setText(str(new))
    assert dlg.b_migrate.isEnabled() is False
    assert "いま動いているフォルダ自身" in dlg.view.toPlainText()


def test_引用符つきで貼っても読める(dlg, pair):
    """⚠ Windows の「パスのコピー」は `"..."` が付く（★そのまま貼られる）。"""
    old, _new = pair
    dlg.edit.setText('"%s"' % old)
    assert dlg.b_migrate.isEnabled() is True


def test_見立ては1バイトも書かない(dlg, pair):
    old, new = pair
    before_old, before_new = _snapshot(old), _snapshot(new)
    dlg.edit.setText(str(old))
    assert _snapshot(old) == before_old
    assert _snapshot(new) == before_new


# --- ★ ③ キャンセル -------------------------------------------------

def test_キャンセルすると何も書かない(dlg, pair, monkeypatch):
    old, new = pair
    before_old, before_new = _snapshot(old), _snapshot(new)
    monkeypatch.setattr(dlg, "confirm",
                        lambda body: QMessageBox.StandardButton.Cancel)
    dlg.edit.setText(str(old))
    dlg._on_migrate()
    assert dlg.result_of_run is None
    assert _snapshot(old) == before_old
    assert _snapshot(new) == before_new, "⚠⚠ キャンセルしたのに書いています"
    assert MG.decision(new) is None


def test_キャンセルの確認に引き継げないものが出る(dlg, pair, monkeypatch):
    """⚠⚠ **実行する前に**知らせる（依頼者 §2）。"""
    old, new = pair
    (new / "work" / "dq3-knowledge").mkdir(parents=True)
    (new / "work" / "dq3-knowledge" / "memos.jsonl").write_bytes(b"mine\n")
    seen = {}
    monkeypatch.setattr(dlg, "confirm",
                        lambda body: seen.setdefault("body", body)
                        and QMessageBox.StandardButton.Cancel
                        or QMessageBox.StandardButton.Cancel)
    dlg.edit.setText(str(old))
    dlg._on_migrate()
    assert "引き継げないもの" in seen["body"]
    assert "work/dq3-knowledge/memos.jsonl" in seen["body"]


# --- ★★ ⚠⚠ ④ 結果の出しかた ★★ -----------------------------------

def _accept(dlg, monkeypatch) -> list:
    """★確認で「実行」を押し、⚠ 結果の窓は出さずに受け取る。"""
    shown = []
    monkeypatch.setattr(dlg, "confirm",
                        lambda body: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(dlg, "show_result",
                        lambda got, stale=(): shown.append((got, stale)))
    return shown


def test_完了のときの結果(dlg, pair, monkeypatch):
    old, new = pair
    shown = _accept(dlg, monkeypatch)
    dlg.edit.setText(str(old))
    dlg._on_migrate()
    got, _stale = shown[0]
    assert got.outcome == MG.OUT_OK
    body = MD.result_text(got)
    for word in ("コピーできた", "引き継げなかった", "失敗",
                 "結果", "次にすること", "詳しい記録"):
        assert word in body, word
    assert MG.OUT_OK in body
    # ⚠⚠ **見出しがあるだけでは足りない**（★中身が空でも「次にすること」は出る）
    #   ⚠ 2026-10-01 の壊す実験で、`next_step()` を空にしても緑のままでした。
    assert got.next_step().strip(), "⚠⚠ 次にすることが空です"
    assert "このまま遊べます" in got.next_step()
    assert got.next_step() in body
    # ★8 分類すべてが写っている
    for entry in OWN.USER_DATA:
        assert (new / entry.rel).exists(), entry.rel


def test_一部完了は完了と同じ顔にならない(dlg, pair, monkeypatch):
    """⚠⚠ 「途中失敗や一部スキップを、全件成功と同じ『引き継ぎ完了』にしない」。"""
    old, new = pair
    (new / "work" / "dq3-knowledge").mkdir(parents=True)
    (new / "work" / "dq3-knowledge" / "memos.jsonl").write_bytes(b"mine\n")
    shown = _accept(dlg, monkeypatch)
    dlg.edit.setText(str(old))
    dlg._on_migrate()
    got, _stale = shown[0]
    assert got.outcome == MG.OUT_PARTIAL
    body = MD.result_text(got)
    assert MG.OUT_PARTIAL in body
    assert "新版に同じものが既にあった" in body
    assert "新しいフォルダへもう一度展開" in got.next_step()
    # ⚠⚠ 新版のほうを消していない
    assert (new / "work" / "dq3-knowledge" / "memos.jsonl").read_bytes() == b"mine\n"


def test_失敗は失敗と出る(dlg, pair, monkeypatch):
    old, new = pair
    shown = _accept(dlg, monkeypatch)
    monkeypatch.setattr(
        MG.shutil, "copy2",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("⚠ わざと")))
    dlg.edit.setText(str(old))
    dlg._on_migrate()
    got, _stale = shown[0]
    assert got.outcome == MG.OUT_FAILED
    body = MD.result_text(got)
    assert MG.OUT_FAILED in body and "わざと" in body
    assert "もう一度" in got.next_step()
    # ⚠⚠ 途中だと分かる印が残っている
    assert MG.incomplete_marker(new).is_file()
    assert MG.decision(new) is None, "⚠ 失敗を「済み」にしています"


def test_選び直しが要る設定を結果にも出す(dlg, pair, monkeypatch):
    old, new = pair
    (old / "user_config.yaml").write_text(
        "paths:\n  dq3_rom: %s\n"
        % (old / "work" / "rom" / "DQ3_J.nes").as_posix(), encoding="utf-8")
    shown = _accept(dlg, monkeypatch)
    dlg.edit.setText(str(old))
    assert "選び直しが要る" in dlg.view.toPlainText()
    dlg._on_migrate()
    got, stale = shown[0]
    assert [k for k, _r, _w in stale] == ["dq3_rom"]
    body = MD.result_text(got, stale)
    assert "選び直して" in body and "dq3_rom" in body
    assert "書き換えていません" in body


# --- ★ ⑤ 断ったことを覚える -----------------------------------------

def test_引き継がず開始を覚える(dlg, pair):
    _old_root, new = pair
    assert MG.should_offer(new) is True
    dlg._on_skip()
    assert dlg.declined is True
    got = MG.decision(new)
    assert got and got["kind"] == MG.DONE_DECLINED
    assert MG.should_offer(new) is False


def test_誘いは条件を見てから出す(qapp, pair, monkeypatch):
    """★`offer_if_first_run()` は ⚠ 条件を満たさなければ**窓を作らない**。"""
    _old_root, new = pair
    made = []
    monkeypatch.setattr(MD, "MigrateDialog",
                        lambda *a, **kw: made.append(kw) or _Fake())
    assert MD.offer_if_first_run(dst=new) is not None
    assert len(made) == 1
    MG.record_decision(MG.DONE_DECLINED, root=new)
    assert MD.offer_if_first_run(dst=new) is None
    assert len(made) == 1, "⚠⚠ 決めたあとにも窓を作っています"


class _Fake:
    def exec(self):
        return 0


# --- ★ ⑥ あとから呼べる道 -------------------------------------------

def test_管理画面に引き継ぎのボタンがある():
    """⚠⚠ 誘いを見送っても**あとから呼べる**（依頼者 §1）。"""
    src = (ROOT / "dq3" / "ui" / "admin_window.py").read_text(encoding="utf-8")
    assert "def do_migrate" in src
    assert "旧版からデータを引き継ぐ" in src
    assert "self.b_migrate.clicked.connect(self.do_migrate)" in src


def test_起動は窓を作る前に誘う():
    """⚠⚠ **順番が肝**（★閉じると user の窓位置が出来るため / 2026-10-01 実測）。"""
    src = (ROOT / "dq3" / "ui" / "app.py").read_text(encoding="utf-8")
    assert "offer_if_first_run" in src
    assert src.index("offer_if_first_run()") < src.index("Dq3MainWindow(vm"), (
        "⚠⚠ 窓を作ってから誘っています（★user data が先に出来ます）")


def test_誘いを止める口がある():
    """★撮影・検査から黙らせられる（⚠ 無いと動画に窓が写る）。"""
    src = (ROOT / "dq3" / "ui" / "app.py").read_text(encoding="utf-8")
    assert "--no-migrate-offer" in src
