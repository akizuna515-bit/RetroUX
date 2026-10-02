"""管理画面（RX3-0059）。★offscreen で開き、状態 / 初期化 / 復元 / 停止を偽の材料で。"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.knowledge import playdata as PD          # noqa: E402
from dq3.ui import emu_speed as ES                 # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"
#: ★リストック設定の表は品名を ROM（`item_info`）から引く（RX3-0212）
needs_rom = pytest.mark.skipif(not ROM_PATH.exists(), reason="★ROM がありません")


class _VM:
    def __init__(self):
        self.raw = {"frame": 100, "game": "dq3", "loc_kind": 1, "map_id": 9, "map_x": 14, "map_y": 21,
                    "walk": {"active": False}, "nav": {"active": True, "phase": "walk"}}
        self.reloaded = 0

    def _raw(self): return self.raw
    def position(self): return (1, 9, 14, 21)
    def location_view(self, _id):
        class V: is_known = True; name = "アリアハン"
        return V()
    def reload_knowledge(self): self.reloaded += 1


class _Cmd:
    def __init__(self): self.sent = []; self.seq = 0
    def send(self, action, **p): self.seq += 1; self.sent.append(action); return self.seq


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _window(tmp_path, confirm=True):
    _app()
    from dq3.ui.admin_window import AdminWindow

    k = tmp_path / "k"
    k.mkdir()
    (k / "seen.json").write_text("{}", encoding="utf-8")
    (k / "npc-heard.json").write_text('{"9": {"1": {}}}', encoding="utf-8")
    (k / "memos.jsonl").write_text(json.dumps({"order": 1, "text": "主「やど", "source": "npc_talk"}) + "\n", encoding="utf-8")
    svc = PD.PlayDataService(k, tmp_path / "vault")
    sent = []
    speed = ES.EmulatorSpeedController(sender=lambda c: (sent.append(c) or True), finder=lambda: 1)
    vm, cmd = _VM(), _Cmd()
    from dq3.ui.ui_settings import UiSettings

    w = AdminWindow(vm, cmd, speed=speed, service=svc, confirm=lambda t, x: confirm,
                    settings=UiSettings(tmp_path / "ui.json"))
    return w, vm, cmd, svc, k, sent


def test_状態が既存情報と一致する(tmp_path):
    w, vm, cmd, svc, k, _ = _window(tmp_path)
    s = w.status_values()
    assert (s["rom"], s["place"], s["map_id"], s["x"], s["y"]) == ("DQ3 JP", "アリアハン", 9, 14, 21)
    assert s["bridge"] is True and s["fceux"] is True
    assert w.l_map.text() == "9" and w.l_xy.text() == "14, 21"


def test_聞き込み履歴の初期化は確認のあと地図を残す(tmp_path):
    w, vm, cmd, svc, k, _ = _window(tmp_path)
    assert "1 人" in w.l_hearing.text()
    w.do_clear_hearing()
    assert not (k / "npc-heard.json").exists() and (k / "seen.json").exists()
    assert vm.reloaded == 1 and "0 人" in w.l_hearing.text()


def test_確認でキャンセルすると何も変わらない(tmp_path):
    w, vm, cmd, svc, k, _ = _window(tmp_path, confirm=False)
    w.do_clear()
    w.do_clear_hearing()
    assert (k / "seen.json").exists() and (k / "npc-heard.json").exists() and vm.reloaded == 0


def test_退避して復元できる(tmp_path):
    w, vm, cmd, svc, k, _ = _window(tmp_path)
    w.do_backup()
    assert "退避" in w.message and svc.latest_backup()
    (k / "seen.json").write_text('{"x": 1}', encoding="utf-8")
    w.do_restore()
    assert (k / "seen.json").read_text(encoding="utf-8") == "{}"


def test_閉じても速度に触らない(tmp_path):
    """★RX3-0259: 手動 400% を外したので、閉じたときに速度を戻す処理も外した（⚠ 聞き込み・街移動の高速化を戻さない）。"""
    w, vm, cmd, svc, k, sent = _window(tmp_path)
    w.speed.set_speed(2.0)
    sent.clear()
    w.close()
    assert w.speed.current == 2.0 and sent == [], "⚠⚠ 管理画面を閉じた拍子に速度を変えた"
    w.speed.restore()


def test_チェックの選択は保存され開き直しても残る(tmp_path):
    w, vm, cmd, svc, k, _ = _window(tmp_path)
    # ★期待は**その場の並びから作る**（⚠ 項目が増えるたびに直す形にしない / 2026-09-03）
    want = [key for key in w.selected_items() if key != "monsters"]
    w.checks["monsters"].setChecked(False)
    body = json.loads((tmp_path / "ui.json").read_text(encoding="utf-8"))
    assert body["admin"]["playdata_items"] == want
    from dq3.ui.admin_window import AdminWindow
    from dq3.ui.ui_settings import UiSettings

    again = AdminWindow(vm, cmd, speed=w.speed, service=svc, confirm=lambda t, x: True,
                        settings=UiSettings(tmp_path / "ui.json"))
    assert again.selected_items() == want


def test_勇者メモを聞き込みの記録から作り直せる(tmp_path):
    """⚠⚠ 2026-09-07 依頼者「1 人ひとり聞き直すのは本末転倒」（RX3-0098）。"""
    import json

    w, vm, cmd, svc, k, _ = _window(tmp_path)
    (k / "npc-conversations.json").write_text(json.dumps({
        "9/1": [{"npc_id": 1, "talk_id": 11, "text_hash": "aaaa", "text": "＊「やあ。",
                 "first_heard_at": "2026-09-05T09:00:00", "last_heard_at": "2026-09-05T09:00:00", "count": 1}],
    }, ensure_ascii=False), encoding="utf-8")
    (k / "memos.jsonl").write_text("", encoding="utf-8")
    w.do_rebuild_memos()
    rows = [json.loads(ln) for ln in (k / "memos.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 1 and rows[0]["source"] == "npc_talk" and rows[0]["map_id"] == 9
    assert "1" in w.message
    # ⚠ もう一度押しても増えない
    w.do_rebuild_memos()
    rows = [json.loads(ln) for ln in (k / "memos.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(rows) == 1


# --- ★RX3-0258 管理画面を 2 カラムに / リストック設定を表に -------------------------------------------

def _boxes(w) -> dict:
    from PySide6.QtWidgets import QGroupBox

    return {b.title(): b for b in w.findChildren(QGroupBox)}


def test_左右2カラムに分かれ_幅が偏らない(tmp_path):
    """★依頼者 §1: 左 = プレイデータ → 聞き込みテスト（プレイデータ・履歴）/ 右 = リストック設定 → 状態。

    ★RX3-0259 で「自動操作・速度」「自動機能」を外した → 指示書の例（左上 = プレイデータ・履歴）に合わせた。
    """
    w, *_ = _window(tmp_path)
    w.show()
    _app().processEvents()
    boxes = _boxes(w)
    left = [boxes[t] for t in ("プレイデータ", "聞き込みテスト")]
    right = [boxes[t] for t in ("リストック設定", "状態")]
    from PySide6.QtCore import QPoint

    at = lambda b: b.mapTo(w, QPoint(0, 0))               # noqa: E731 ★管理画面の中の位置（⚠ 枠は列の入れ物の中）
    assert len({at(b).x() for b in left}) == 1 and len({at(b).x() for b in right}) == 1, "⚠ 列がそろっていない"
    assert at(left[0]).x() < at(right[0]).x(), "⚠⚠ 2 カラムになっていない"
    assert [at(b).y() for b in left] == sorted(at(b).y() for b in left)
    assert [at(b).y() for b in right] == sorted(at(b).y() for b in right)
    ratio = left[0].width() / right[0].width()
    assert 0.8 <= ratio <= 1.25, "⚠ 左右の幅が偏っている: %d / %d" % (left[0].width(), right[0].width())
    w.close()


def test_縦に長くならない(tmp_path):
    """⚠ 依頼者「1920×1080 で 1 画面に収まりにくい」（RX3-0258）。

    ★1920×1080・150% で使える高さは約 672（タスクバーを除く）→ 題名の帯を除いて中身は約 641。★余裕 30 を見て Windows で 610 まで。
    ⚠ 画面の外の寸法は実機より低い（★2026-09-14 実測: 今 offscreen 524 / Windows 596、状態を 6 行に戻すと 560 / 640）
      → ★offscreen の上限は 610 × 524/596 ≒ 540。
    """
    w, *_ = _window(tmp_path)
    hint = w.sizeHint()
    assert hint.height() <= 540, "⚠⚠ 管理画面が縦に長い（★Windows で 610 を超える見込み）: %s" % hint
    assert hint.width() <= 1200, "⚠ 横に広すぎる: %s" % hint


@needs_rom
def test_リストック設定は表で_自由入力の欄は無い(tmp_path):
    from dq3.ui.restock_window import RestockTable
    from dq3.ui.town_bar import restock_wants

    w, vm, cmd, svc, k, _ = _window(tmp_path)
    assert isinstance(w.restock_table, RestockTable)
    assert not hasattr(w, "e_restock"), "⚠⚠ 旧い自由入力の文字の欄が残っている"
    assert w.restock_table.parentWidget() is _boxes(w)["リストック設定"] or \
        _boxes(w)["リストック設定"].isAncestorOf(w.restock_table)
    w.restock_table.spins[108].setValue(3)                   # ★まんげつそう 3 個
    body = json.loads((tmp_path / "ui.json").read_text(encoding="utf-8"))
    assert "まんげつそう:3" in body["admin"]["restock_wants"], body
    assert (108, 3) in restock_wants(w.settings), "⚠ 補充の計画が読む値と表の値がずれている"


def test_外した設定は出さない(tmp_path):
    """★RX3-0259（2026-09-14 依頼者「自動操作・速度の設定はいらない / walker、街ナビの設定も不要」）。"""
    from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton

    w, *_ = _window(tmp_path)
    texts = ([b.text() for b in w.findChildren(QPushButton)] + [c.text() for c in w.findChildren(QCheckBox)]
             + [lb.text() for lb in w.findChildren(QLabel)])
    for gone in ("高速実行", "手動で 400%", "自動移動を停止", "Walker", "街ナビ"):
        assert not any(gone in t for t in texts), "⚠ 外したものが残っている: %s" % gone
    assert "自動操作・速度" not in _boxes(w) and "自動機能" not in _boxes(w)
    for name in ("fast_checks", "b_speed", "b_stop", "fast_run", "toggle_speed", "stop_auto"):
        assert not hasattr(w, name), name


def test_詳しいログの入り切りは管理画面で保存しログ画面へ知らせる(tmp_path):
    """★RX3-0276（依頼者「詳しいログ表示のON/OFFは管理画面に逃がして。これで1行とるのもったいない。」）。

    ⚠ 行は増やさない（★「Lua Bridge」の行の右 / 高さの上限は `test_縦に長くならない`）。
    """
    from dq3.ui.admin_window import AdminWindow
    from dq3.ui.ui_settings import UiSettings

    w, vm, cmd, svc, k, _ = _window(tmp_path)
    told = []
    w.on_detail_log = told.append
    assert not w.c_detail_log.isChecked(), "★既定は出さない（RX3-0482 / 新規利用はオフ）"
    w.c_detail_log.setChecked(True)
    body = json.loads((tmp_path / "ui.json").read_text(encoding="utf-8"))
    assert body["log"]["show_detail"] is True and told == [True]
    again = AdminWindow(vm, cmd, speed=w.speed, service=svc, confirm=lambda t, x: True,
                        settings=UiSettings(tmp_path / "ui.json"))
    assert again.c_detail_log.isChecked(), "⚠ 開き直したら戻っていない"
    again.c_detail_log.setChecked(False)
    body = json.loads((tmp_path / "ui.json").read_text(encoding="utf-8"))
    assert body["log"]["show_detail"] is False and told == [True], "★切っても保存（知らせ先は w だけ）"
    grid = w.l_bridge.parentWidget().layout()
    assert grid.getItemPosition(grid.indexOf(w.c_detail_log))[0] == \
        grid.getItemPosition(grid.indexOf(w.l_bridge))[0], "⚠ 行を増やした（★Lua Bridge の行の右に置く）"


def test_残る機能は消していない(tmp_path):
    w, *_ = _window(tmp_path)
    for name in ("b_backup", "b_restore", "b_clear", "b_clear_hearing", "b_rebuild_memos", "b_clear_place",
                 "b_restock_reset", "restock_table", "l_fceux", "l_bridge", "l_rom", "l_place", "l_map", "l_xy"):
        assert getattr(w, name) is not None, name


def test_画面の見え方を選ぶと覚えて次の起動から効くと伝える(tmp_path):
    """★★ 管理画面 → 設定 → cfg までつないで見る（RX-0140 / 2026-09-18）。

    ⚠⚠ 2026-09-18 に「作ったのに呼ばれていない」で実機が動かなかった（RX3-0282）。
      ★だから**人が触る口から**確かめる（⚠ 部品を直接呼ぶだけにしない）。
    """
    import io as _io

    from dq3 import emulator_video as EV

    w, _vm, _cmd, _svc, _k, _sent = _window(tmp_path)
    index = w.cb_video.findData("PAL 3x")
    assert index >= 0, "⚠ 走査線の選択肢が無い"
    w.cb_video.setCurrentIndex(index)
    assert w.settings.get(EV.SECTION, EV.KEY) == "PAL 3x"
    assert "次に FCEUX" in w.message, "⚠ すぐ効かないことを伝えていない"
    # ★覚えた名前で、同梱 cfg と同じ形のファイルを書き換えられる
    cfg = tmp_path / "fceux.cfg"
    plain = ("winspecial 0" + chr(13) + chr(10) + "vmspecial 0" + chr(13) + chr(10)).encode()
    _io.open(cfg, "wb").write(plain)
    assert EV.apply_to_cfg(EV.chosen(w.settings), cfg) is True
    assert _io.open(cfg, "rb").read() == plain.replace(b"winspecial 0", b"winspecial 9")


def test_見え方は7つから選べて1つずつ説明が出る(tmp_path):
    """★2026-09-18 依頼者「動きは OK。スキャンラインは他も選べるようにして」。"""
    from PySide6.QtCore import Qt

    from dq3 import emulator_video as EV

    w, *_ = _window(tmp_path)
    got = [w.cb_video.itemData(i) for i in range(w.cb_video.count())]
    assert got == [name for name, _label, _tip in EV.CHOICES], got
    assert len(got) == 7
    for i, name in enumerate(got):
        tip = w.cb_video.itemData(i, Qt.ItemDataRole.ToolTipRole)
        assert tip and tip == EV.tip_of(name), name
    # ★どれを選んでも覚える（⚠ 走査線だけの作りにしていないこと）
    w.cb_video.setCurrentIndex(got.index("hq2x"))
    assert w.settings.get(EV.SECTION, EV.KEY) == "hq2x"
    assert "丸み 強" in w.message


# --- ★frame / フィールド を右画面からここへ移した（RX3-0328 / 2026-09-21）---

def test_frameとフィールドを管理画面に出す(tmp_path):
    """★依頼者 2026-09-21「frame／フィールド表示は管理画面に移動させていい」。

    ⚠⚠ ソースに「戦闘中」の字があるだけでは足りません（★2026-09-21 の壊す実験で空振り）。
      → ★**本当に出る値**を見ます。
    """
    w, _vm, _cmd, _svc, _k, _sent = _window(tmp_path)
    got = w.status_values()
    assert got["frame"] == 100
    assert got["where"] == "フィールド", got
    w.refresh()
    assert "frame 100" in w.l_bridge.text() and "フィールド" in w.l_bridge.text(), w.l_bridge.text()


def test_戦闘中も出し分ける(tmp_path):
    """⚠ 片方の枝しか通らない検査にしない（★「既定 OFF の道は一度も実行されない」）。"""
    w, vm, _cmd, _svc, _k, _sent = _window(tmp_path)
    vm.raw["in_battle"] = True
    assert w.status_values()["where"] == "戦闘中"
    w.refresh()
    assert "戦闘中" in w.l_bridge.text(), w.l_bridge.text()


def test_届いていなければ場所を出さない(tmp_path):
    """⚠ frame が無いのに「フィールド」と言わない（★嘘を出さない）。"""
    w, vm, _cmd, _svc, _k, _sent = _window(tmp_path)
    vm.raw["frame"] = None
    assert w.status_values()["where"] is None
