"""Monster Panel v1（RX3-0036 / 2026-09-01）。

★依頼者の指示書 §14〜§22。

```text
┌──────────────────────────┐
│ [ 絵 ] │ HP 8 / MP 0 / 攻 9 …  │
│        │ スライム              │
└──────────────────────────┘
```

⚠⚠ **匹数は出しません**（§15）。★表示の単位は「種」です。
⚠⚠ **`retroux/` は変更しません**（`RX3-0011`）。★継承して札だけ作り直す。
"""

from __future__ import annotations

import os
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROM_PATH = ROOT / "work" / "rom" / "DQ3_J.nes"


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:                                # pragma: no cover
        pytest.skip("Qt が無い環境")
    got = QApplication.instance()
    yield got if got is not None else QApplication([])


def _rom_ready() -> bool:
    try:
        from dq3rom import profile as dq3

        dq3.load_and_identify(ROM_PATH)
    except Exception:
        return False
    return True


needs_rom = pytest.mark.skipif(not _rom_ready(), reason="DQ3 の ROM が読めない")


def _cards(**over):
    from dq3.ui.monster_panel import Dq3MonsterCard

    base = dict(monster_id=0, name="スライム", stats=(("HP", 8), ("攻", 9)))
    base.update(over)
    return Dq3MonsterCard(**base)


# --- ★ROM 側（⚠ 画面なしで見られる）----------------------------------------

@needs_rom
def test_性能はROMの値をそのまま出す():
    """★指示書 §2.2「取得できた値をそのまま表示してよい」。"""
    from dq3.knowledge.enemies_seen import MASTER_FIELDS, master_of

    got = master_of(0)
    assert [k for k, _ in got] == [k for k, _ in MASTER_FIELDS]
    assert dict(got) == {"HP": 8, "MP": 0, "攻": 9, "守": 5,
                         "速": 4, "EXP": 4, "G": 2}


@needs_rom
def test_HPは10bitで出す():
    """★★ ⚠⚠ 下位 8 bit だけだと**別の数**になります。 ★★

    ```text
    id87  ★HP 500   ⚠ 下位 8 bit だけだと 244
    id101 ★HP 300   ⚠ 同 44
    ```
    """
    from dq3.knowledge.enemies_seen import details_of, master_of

    assert dict(master_of(87))["HP"] == 500
    assert dict(master_of(101))["HP"] == 300
    assert dict(details_of(87))["最大HP"] == 500


@needs_rom
def test_絵は置き場から引く(tmp_path):
    """⚠ 画面は絵の**作り方を持ちません**（指示書 §22）。

    ⚠⚠ 2026-09-12（RX3-0223）: 以前は置き場を渡さずに `ensure()` を呼び、★**本物の** `work/dq3-monster-art` を
      作り直していた（★絵の版が上がった日に 49 枚を書き換えた / RX3-0215 と同じ形）。→ ★一時フォルダに作る。
    """
    from dq3.knowledge import monster_art

    monster_art.ensure(art_dir=tmp_path)
    got = monster_art.path_of(0, art_dir=tmp_path)
    assert got is not None and got.exists(), monster_art.last_error
    assert monster_art.path_of(9999, art_dir=tmp_path) is None


# --- ★画面 -----------------------------------------------------------------

def test_retrouxを変えずにDQ3側で作っている():
    """★★ ⚠⚠ `RX3-0011` の決まり: **`retroux/` は変更しない**。 ★★

    ⚠ 一度 `retroux/ui/battle_monsters.py` に性能欄を足してしまい、
      `test_retrouxを変更していない` が**赤くなって気づきました**。
    ★`PartyPanel` のときと同じく、**DQ3 側に作り直す**のが決まりです。

    ⚠ ただし枠組み（横スクロール・空の出し方）は**継承して使います**
      （★指示書 §23「DQ2 の実装を最大限再利用」）。
    """
    from dq3.ui.monster_panel import Dq3MonsterStrip
    from retroux.ui.battle_monsters import BattleMonsterStrip

    assert issubclass(Dq3MonsterStrip, BattleMonsterStrip)
    src = (ROOT / "retroux" / "ui" / "battle_monsters.py").read_text(
        encoding="utf-8")
    assert "stats" not in src, "⚠⚠ retroux 側に DQ3 の都合が入っています"


def test_匹数を出さない(app):
    """⚠⚠ 指示書 §15「モンスターの匹数は不要」。"""
    from PySide6.QtWidgets import QLabel

    from dq3.ui.monster_panel import Dq3MonsterCard, Dq3MonsterStrip

    assert not hasattr(Dq3MonsterCard(monster_id=0, name="x"), "count"), (
        "⚠⚠ 札が匹数を持っています（★表示の単位は種）")
    strip = Dq3MonsterStrip()
    strip.set_cards([_cards()])
    texts = [w.text() for w in strip.findChildren(QLabel)]
    assert "スライム" in texts, texts
    assert not any("×" in t for t in texts), texts


def test_DQ2の帯は今までどおり(app):
    """★DQ2 の札は**触っていない**こと（⚠ 匹数も出る）。"""
    from PySide6.QtWidgets import QLabel

    from retroux.ui.battle_monsters import BattleMonsterStrip, MonsterCard

    strip = BattleMonsterStrip()
    strip.set_cards([MonsterCard(monster_id=0, name="スライム", count=4)])
    texts = [w.text() for w in strip.findChildren(QLabel)]
    assert "スライム×4" in texts, texts


def test_性能が絵の右に出る(app):
    from PySide6.QtWidgets import QLabel

    from dq3.ui.monster_panel import Dq3MonsterStrip

    strip = Dq3MonsterStrip()
    strip.set_cards([_cards()])
    texts = [w.text() for w in strip.findChildren(QLabel)]
    # ⚠ 性能は**2 列**に分かれるので、1 つの札に固めない
    joined = " / ".join(texts)
    assert "HP 8" in joined and "攻 9" in joined, texts


def test_多くても高さは変わらず横スクロールになる(app):
    """★指示書 §17「縦方向の画面高さを増やさない」。"""
    from PySide6.QtCore import Qt

    from dq3.ui.monster_panel import Dq3MonsterStrip

    strip = Dq3MonsterStrip()
    strip.resize(300, strip.height())
    one = strip.height()
    strip.set_cards([_cards(monster_id=i, name="敵%d" % i) for i in range(8)])
    assert strip.height() == one, "⚠⚠ 中身で高さが変わっています"
    assert (strip.horizontalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    assert (strip.verticalScrollBarPolicy()
            == Qt.ScrollBarPolicy.ScrollBarAlwaysOff)


def test_絵の枠はいちばん大きい敵に合わせる():
    """⚠ 64 角にしていて、★大きい敵が右端で切れていました（絵で気づいた）。"""
    from dq3.ui.monster_panel import ART_H, ART_W

    assert (ART_W, ART_H) == (80, 64), "★DQ3 の最大は 10 列 × 8 行"


# --- ★戦闘中／戦闘後（⚠ 指示書 §20・§21）---------------------------------

class _VM:
    """★`battle_view` だけを持つ最小の代役（⚠ 画面の判断を見るため）。"""

    def __init__(self, groups, fighting):
        self._got = (groups, fighting)

    def battle_view(self):
        return self._got

    def in_battle(self):
        return self._got[1]


def _window(vm, app):
    from dq3.ui.battle_window import Dq3BattleWindow
    from dq3.ui.monster_panel import Dq3MonsterStrip

    win = Dq3BattleWindow.__new__(Dq3BattleWindow)
    win.vm = vm
    win.monsters = Dq3MonsterStrip()
    return win


def test_同じ種が2群に分かれても1枚(app):
    """⚠⚠ 指示書 §20「同一 monster_id が複数個体存在しても重複排除」。"""
    vm = _VM([{"id": 1, "n": 3, "name": "A"},
              {"id": 1, "n": 2, "name": "A"},
              {"id": 23, "n": 1, "name": "B"}], True)
    win = _window(vm, app)
    win._show_enemies(*vm.battle_view())
    got = [c.monster_id for c in win.monsters.cards()]
    assert got == [1, 23], "⚠⚠ 種ごとに 1 枚になっていない: %r" % got


def test_戦闘が終わっても残り直近と分かる(app):
    """★指示書 §21「戦闘終了に伴ってカードを消さない」。"""
    vm = _VM([{"id": 1, "n": 1, "name": "A"}], False)
    win = _window(vm, app)
    win._show_enemies(*vm.battle_view())
    names = [c.name for c in win.monsters.cards()]
    # ★2026-09-02 依頼者: 札の名前に「（直近）」は付けない。★終わった戦闘だと分かるのはヒントの見出し
    assert names == ["A"], names
    assert "直近" in win.monsters.toolTip()


def test_性能は3列に分ける():
    """★★ ⚠⚠ 2026-09-01 実機: **7 行だと札からはみ出していました**。

    ```text
    ⚠ 1 列   HP/MP/攻/守/速/EXP/G を縦に 7 行 → 絵（8 行ぶん）より高い
    ★3 列   HP 8   守 5   G 2          ★RX3-0276: 2 列 → 3 列（名前・耐性・特技も絵の右の欄に入れるため 3 行に）
             MP 0   速 4
             攻 9   EXP 4
    ```

    ⚠ 依頼者の画面では **性能が 3 つ切れ、名前も出ていませんでした**。
    """
    from dq3.ui.monster_panel import (STAT_COLUMNS, STRIP_HEIGHT,
                                      stat_columns)

    assert STAT_COLUMNS == 3, "⚠ 既定が 3 列でない"
    # ⚠ **既定を使う**（★引数で渡すと、既定を変えても気づけない）
    got = stat_columns([("HP", 8), ("MP", 0), ("攻", 9), ("守", 5),
                        ("速", 4), ("EXP", 4), ("G", 2)])
    assert len(got) == 3, got
    assert got[0].count(chr(10)) == 2 and got[1].count(chr(10)) == 2, "⚠ 1・2 列目が 3 行でない"
    assert got[0].startswith("HP 8") and got[1].startswith("守 5") and got[2] == "G 2"
    # ★絵（64px）＋ 余白が収まる高さ
    assert STRIP_HEIGHT >= 100, "⚠ 札が入りません"


def test_性能が空でも落ちない():
    from dq3.ui.monster_panel import stat_columns

    assert stat_columns(()) == []
    assert stat_columns(None) == []


def test_札が切れない(app):
    """★★★ ⚠⚠ **窓に置いても札が切れないこと** ★★★

    ⚠ 2026-09-01 の実機で、`battle_window` が `setMaximumHeight(88)` を
      掛けていて、★104px の帯が **88px に潰されて**いました。
      性能が 3 つと名前が切れていました。

    ⚠⚠ DQ2 側は同じ失敗を 2026-08-14 に済ませています
      （`test_layout_heights.test_札を切らない`）。

    ★ここでは「帯を窓へ入れても、下限が中身に足りているか」を見ます。
    """
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from dq3.ui.monster_panel import STRIP_HEIGHT, Dq3MonsterStrip

    host = QWidget()
    box = QVBoxLayout(host)
    strip = Dq3MonsterStrip()
    box.addWidget(strip)
    host.resize(700, 400)
    strip.set_cards([_cards()])
    host.show()
    assert strip.minimumHeight() >= STRIP_HEIGHT, (
        "⚠⚠ 下限が %d しかありません（★中身は %d 要る）"
        % (strip.minimumHeight(), STRIP_HEIGHT))
    assert strip.maximumHeight() >= STRIP_HEIGHT, (
        "⚠⚠ 上限 %d で頭打ちです（★中身は %d）"
        % (strip.maximumHeight(), STRIP_HEIGHT))


# --- ★★ RX3-0037 下の窓の配分 ----------------------------------------------


def test_帯は下限であって固定ではない(app):
    """★★★ ⚠⚠ **伸びしろをログだけに持たせない** ★★★

    依頼者 2026-09-01:

        > モンスター画面とログ画面のバランスで、
        > ★モンスター画面はちゃんと**デフォルトでなるべく表示**させたい

    ⚠ もとは `setFixedHeight(104)` でした。★下の窓が高くなっても
      帯は 104 のままで、**増えたぶんは全部ログ**が取っていました。

    ⚠⚠ ただし**上限は掛けません**。★掛けると 2026-09-01 の
      `setMaximumHeight(88)`（性能 3 つと名前が切れた）の再来です。
    """
    from dq3.ui.monster_panel import STRIP_HEIGHT, Dq3MonsterStrip

    strip = Dq3MonsterStrip()
    assert strip.minimumHeight() == STRIP_HEIGHT, (
        "⚠⚠ 下限が %d（★札が切れる）" % strip.minimumHeight())
    assert strip.maximumHeight() > STRIP_HEIGHT * 4, (
        "⚠⚠ 上限 %d で頭打ちです（★固定に戻っている）"
        % strip.maximumHeight())
    strip.resize(400, STRIP_HEIGHT * 2)
    assert strip.height() == STRIP_HEIGHT * 2, "⚠ 高くできていない"


def test_札の幅は高さで変わらず絵の枠も伸ばさない():
    """★RX3-0276（2026-09-15 依頼者「空きが目立つ」→ 案 1 = 左に札・右にログ）。

    ⚠ 左右に分けたので足りないのは**幅**。★絵の枠を高さで伸ばすと、比を保つために札の幅も伸びてログを削る。
    → ★札の幅はいつも `CARD_WIDTH`（392 → 248）、絵の枠は大物（80x64）のまま。
    """
    from dq3.ui.monster_panel import (ART_H, ART_W, CARD_H, CARD_WIDTH, STRIP_HEIGHT, art_box,
                                      card_size, rows_for)

    assert (CARD_WIDTH, CARD_H) == (272, 100), "★RX3-0276: 392 → 272 × 100"
    assert art_box(STRIP_HEIGHT) == (ART_W, ART_H)
    assert art_box(STRIP_HEIGHT + 64) == (ART_W, ART_H), "⚠ 高さで絵の枠を伸ばしている（★札が広がる）"
    assert card_size(STRIP_HEIGHT) == card_size(STRIP_HEIGHT + 104) == (CARD_WIDTH, CARD_H), "⚠ 札の幅・高さの上限が違う"
    # ★高いときは段を積む（★下段の窓の帯 = 216 で 2 段 / 下限では 1 段）
    assert rows_for(STRIP_HEIGHT) == 1 and rows_for(216) == 2, (rows_for(STRIP_HEIGHT), rows_for(216))


def test_依頼者の窓の高さでも2段に入る():
    """⚠⚠ 2026-09-15 依頼者「横１列ではなく、横２列で表示できないか？スクロールせずに４つ表示できそう」。

    ★依頼者のログ窓は高さ 216（= 帯 206）で保存されていた。⚠ 札を 100 に固定していたので 2 段に 8px 足りず 1 段だった。
    → ★段は札の**下限**で決め、札はその段に入る高さにする。
    """
    from dq3.ui.monster_panel import (CARD_H, CARD_WIDTH, MIN_CARD_H, STRIP_SIDE, card_size,
                                      rows_for)

    at = 206                                          # ★依頼者の窓（216）の帯
    assert rows_for(at) == 2, "⚠⚠ 依頼者の窓で 1 段のまま"
    w, h = card_size(at)
    assert MIN_CARD_H <= h <= CARD_H and h * 2 + 6 <= at, (w, h)
    # ★敵 4 群が 2 段 × 2 列（★帯の既定の幅に収まる = 横スクロールしない）
    assert 2 * CARD_WIDTH + 6 + STRIP_SIDE <= 566, "⚠ 2 列が帯の既定の幅に入らない"


def test_名前と性能を絵の右に詰め耐性と特技は行を分ける(app):
    """★RX3-0276: ⚠ 392 の札では性能の 2 列が札の両端へ離れて空いていた（★列を伸びしろ 1 で足していた）。

    ★名前は絵の右の頭 / 性能の列は詰める / 耐性・特技はそれぞれの行で 2 行まで（⚠ 1 行に詰めて「…」で切らない）。
    ⚠ 画面外の字の幅は実機と違う（★覚え書き）→ ★絶対の字数ではなく、**前の 1 行（196 幅）より多く出るか**で見る。
    """
    from PySide6.QtWidgets import QLabel

    from dq3.ui import monster_panel as MP

    resist = "払× 眠△ 死× 封△ 混△ 弱△ 休×"
    special = "こうげき呪文(13) ねむり ほのお(2) なかまをよぶ"
    card = MP._Card(MP.Dq3MonsterCard(monster_id=1, name="テスト", resist=resist, special=special,
                                      stats=(("HP", 140), ("MP", 0), ("攻", 85), ("守", 54),
                                             ("速", 23), ("EXP", 405), ("G", 54))))
    card.show()
    # ⚠⚠ 並べ方が決まる前の位置は全部 0（★回さないと「列が離れていない」が必ず通る / 壊す実験で気づいた）
    app.processEvents()
    labels = card.findChildren(QLabel)
    texts = [w.text() for w in labels]
    r = [w for w in labels if w.text().startswith("耐性")]
    s = [w for w in labels if w.text().startswith("特技")]
    assert len(r) == 1 and len(s) == 1, "⚠ 耐性と特技が別の行になっていない: %r" % texts
    assert chr(10) not in r[0].text() and chr(10) not in s[0].text(), "⚠ 1 行を越えた（★札の高さは固定）"
    # ★全文はヒント（★RX3-0278: 字の上だけでなく札全体に付ける）
    assert card.toolTip().startswith("テスト\n耐性 " + resist), "★全文はヒント: %r" % card.toolTip()
    before = r[0].fontMetrics().elidedText("耐性 %s　特技 %s" % (resist, special),
                                           MP.Qt.TextElideMode.ElideRight, 196 - 8).rstrip("…")
    now = (r[0].text() + s[0].text()).replace(chr(10), "").rstrip("…")
    assert len(now) > len(before), "⚠ 前の 1 行より出ていない: %r / 前 %r" % (now, before)
    # ★名前は絵の右の頭（⚠ 下に 1 行使わない）/ 性能の 2 列は詰める（⚠ 札の両端へ離さない）
    name = [w for w in labels if w.text() == "テスト"][0]
    hp = [w for w in labels if w.text().startswith("HP 140")][0]
    col2 = [w for w in labels if w.text().startswith("守 54")][0]
    art = [w for w in labels if w.text() == "絵なし"][0]
    assert col2.geometry().x() > 0 and hp.geometry().width() > 0, "⚠ 位置が決まっていない（★この検査は空回り）"
    assert name.geometry().x() > art.geometry().x() and name.geometry().y() <= hp.geometry().y()
    assert r[0].geometry().x() > art.geometry().x(), "★耐性・特技も絵の右の欄"
    assert col2.geometry().x() - (hp.geometry().x() + hp.sizeHint().width()) <= 20, (
        "⚠⚠ 性能の列が離れている（★札の空き）: %d → %d" % (hp.geometry().x(), col2.geometry().x()))
    assert card.width() == MP.CARD_WIDTH and card.height() == MP.CARD_H


def test_長い耐性は区切りで折り返し2行を越えたら切る(app):
    from PySide6.QtWidgets import QLabel

    from dq3.ui import monster_panel as MP

    fm = QLabel().fontMetrics()
    long = "耐性 " + " ".join(["眠×", "死△", "黙×", "乱△", "幻×", "軟△", "遅×", "炎△", "氷×", "風△"] * 3)
    assert MP.wrap_lines(long, fm, 120).count(chr(10)) == 0, "★既定は 1 行（札の高さは固定 / RX3-0276）"
    got = MP.wrap_lines(long, fm, 120, max_lines=2)
    assert got.count(chr(10)) == 1 and got.endswith("…"), got
    for line in got.split(chr(10)):
        assert fm.horizontalAdvance(line) <= 120, line
    assert not got.split(chr(10))[0].endswith(("眠", "死", "黙")), "⚠ 「眠×」の途中で折った: %r" % got
    assert MP.wrap_lines("耐性 眠×", fm, 120) == "耐性 眠×"
    assert MP.wrap_lines("", fm, 120) == ""


def test_札のどこにマウスを置いても耐性の全文が出る(app):
    """★RX3-0278 依頼者「耐性が多いときに省略表示されてしまう。ツールチップ表示させたい」。

    ⚠ 以前は耐性・特技の**字の上だけ**にヒントがあり、札のほかの所では帯のヒントが出ていた。
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QApplication, QLabel, QToolTip

    from dq3.ui import monster_panel as MP

    tip = "耐性\n  × 効かない　炎（メラ・ギラ・イオ）\n特技\n  炎ブレス(30〜39)"
    strip = MP.Dq3MonsterStrip()
    strip.resize(900, 140)
    strip.show()
    strip.set_cards([_cards(name="おろち", resist=" ".join(["炎×", "乱×", "黙×", "遅×", "死×"] * 3),
                            special="炎ブレス(30〜39)", tip=tip)])
    strip.setToolTip("帯のヒント")
    app.processEvents()
    labels = strip.findChildren(QLabel)
    assert any(lab.text().endswith("…") for lab in labels), "⚠ 前提: 札の耐性が切れていない"
    for lab in labels:
        QToolTip.hideText()
        pos = lab.rect().center()
        QApplication.sendEvent(lab, QHelpEvent(QEvent.Type.ToolTip, pos, lab.mapToGlobal(pos)))
        app.processEvents()
        assert QToolTip.text() == "おろち\n" + tip, "⚠⚠ %r の上で全文が出ない: %r" % (lab.text(), QToolTip.text())
    QToolTip.hideText()


def test_下限より低くしても札は縮めない():
    """⚠ 下限を割った値を渡されても、★札は `STRIP_HEIGHT` ぶんを保つ。"""
    from dq3.ui.monster_panel import ART_H, ART_W, STRIP_HEIGHT, art_box, card_size

    assert art_box(10) == (ART_W, ART_H)
    assert card_size(10) == card_size(STRIP_HEIGHT)
    assert card_size(0)[1] == STRIP_HEIGHT - 12


def test_札が増えても帯は高くならない(app):
    """★★★ ⚠⚠ **中身で大きさを変えない**（`docs/design/dq3-ui-v0.md`）★★★

    ⚠ `setFixedHeight` を外したので、★「札が増えたら伸びる」に
      なっていないことを、ここで見ます。
    """
    from dq3.ui.monster_panel import STRIP_HEIGHT, Dq3MonsterStrip

    strip = Dq3MonsterStrip()
    strip.resize(700, STRIP_HEIGHT)
    before = strip.height()
    strip.set_cards([_cards(monster_id=i, name="敵%d" % i) for i in range(8)])
    assert strip.height() == before, (
        "⚠⚠ 札を 8 枚入れたら帯が %d → %d になりました"
        % (before, strip.height()))
    assert strip.minimumHeight() == STRIP_HEIGHT, "⚠ 下限が中身で動いた"


def test_高くすると段を積んで並べ直す(app):
    """★RX3-0276: 帯を高くしたら、⚠ **札を段に積み直す**（★札の大きさは変えない / 空きを作らない）。"""
    from dq3.ui.monster_panel import CARD_H, STRIP_HEIGHT, Dq3MonsterStrip, card_size

    strip = Dq3MonsterStrip()
    strip.resize(1400, STRIP_HEIGHT)
    # ⚠ 隠れたままだと `resizeEvent` が来ません（★実測 / `showEvent` で補う）
    strip.show()
    strip.set_cards([_cards(monster_id=i, name="敵%d" % i) for i in range(3)])
    assert strip.rows() == 1 and strip.columns() == 3
    assert all(w.size().height() == CARD_H for w in strip.card_widgets())

    strip.resize(1400, 216)                           # ★下段の窓の帯の高さ
    app.processEvents()                               # ⚠ 並べ方が決まる前の位置は全部 (0,0)（★撮る前に回す）
    assert strip.rows() == 2 and strip.columns() == 2, (
        "⚠⚠ 帯を高くしたのに 1 段のまま（★組み直していない）: %d 段" % strip.rows())
    cards = strip.card_widgets()
    assert len(cards) == 3 and all(w.size() == cards[0].size() for w in cards)
    assert cards[0].size().height() == card_size(216)[1] == CARD_H, "⚠ 札の高さが帯で変わった"
    from PySide6.QtCore import QPoint

    at = [w.mapTo(strip.widget(), QPoint(0, 0)) for w in cards]
    assert at[0].x() == at[1].x() and at[0].y() < at[1].y(), "★1 列目に上から 2 枚"
    assert at[2].x() > at[0].x() and at[2].y() == at[0].y(), "★3 枚目は 2 列目の上"


def test_窓を組んで配分を確かめる(app):
    """★★★ ⚠⚠ **足場ではなく、実際の窓で見る** ★★★

    ⚠ 2026-08-31 の教訓: 動かない足場で緑にしても、★組み立てた途端に
      壊れていることがあります（`test_dq3_map_browser` の 2 列目）。

    ★ここでは `Dq3BattleWindow` を**本当に組んで**、
      ⚠ 帯とログが `bottom_split` の配分どおりに**左右へ**置かれたかを見ます（★RX3-0276 / 案 1）。
    """
    from PySide6.QtCore import Qt

    from dq3.ui import layout
    from dq3.ui.battle_window import LOG_W_MIN, Dq3BattleWindow, _strip_width_min
    from dq3.ui.monster_panel import STRIP_HEIGHT

    class _VM:
        def battle_view(self):
            return ([{"id": 1, "name": "スライム", "n": 2, "known": True}],
                    True)

    win = Dq3BattleWindow(_VM())
    win.show()
    app.processEvents()

    strip_w, log_w = win.split_sizes()
    assert win.split.orientation() == Qt.Orientation.Horizontal, "⚠⚠ 上下のまま（★RX3-0276 = 左右）"
    assert win.split.sizes() == [strip_w, log_w], (
        "⚠⚠ 既定の配分が当たっていません %s" % (win.split.sizes(),))
    assert strip_w >= _strip_width_min(), "⚠⚠ 帯が札 1 列より狭い %d" % strip_w
    assert log_w >= LOG_W_MIN, "⚠ ログが下限を割った %d" % log_w
    # ★帯は窓の高さいっぱい（★左右に分けた狙い / ⚠ 下限を割らない）→ 2 段
    assert win.monsters.height() >= STRIP_HEIGHT, win.monsters.height()
    assert win.monsters.rows() >= 2, "⚠⚠ 帯が高いのに 1 段のまま（★札の下が空く）: %d" % win.monsters.height()

    # ⚠ 畳めないこと（★ログ 0 行 / 帯が消える、のどちらも作らない）
    assert not win.split.childrenCollapsible()
    assert win.split.count() == 2, win.split.count()
    assert layout.bottom_split(0, _strip_width_min(), LOG_W_MIN) == (0, 0)
    win.close()


# --- ★★ RX3-0042 横スクロール（⚠ 画面を撮って見つけた）---------------------


def test_札が多いとき全部にたどり着ける(app):
    """★★★ ⚠⚠ **指示書 §5「全種類を横スクロールで確認可能」** ★★★

    ## ⚠⚠ 2026-09-01: 効いていませんでした

      `QScrollArea(widgetResizable=True)` が中身を**窓の幅に押し込め**、
      ★8 枚で 1622px 要るところが 700px のままでした。

      ```text
      8 枚目   x=614..810   ⚠ 見ることも触ることもできない
      横バー   出ない
      ```

      ★検査は全部緑でした。⚠ **画面を撮って初めて**分かりました。
    """
    from dq3.ui.monster_panel import (STRIP_HEIGHT, Dq3MonsterStrip,
                                      card_size)

    from PySide6.QtCore import QPoint

    for height in (STRIP_HEIGHT, 216):                  # ★1 段 / 2 段（RX3-0276）
        for count in (1, 3, 5, 8, 12):
            strip = Dq3MonsterStrip()
            strip.resize(700, height)
            strip.show()
            strip.set_cards([_cards(monster_id=i, name="敵%d" % i)
                             for i in range(count)])
            # ⚠⚠ 並べ方が決まる前の位置は全部 (0,0)（★回さないと「右端に届く」が必ず通ってしまう）
            app.processEvents()
            bar = strip.horizontalScrollBar()
            cards = strip.card_widgets()
            assert len(cards) == count
            if count > 1:
                assert max(w.mapTo(strip.widget(), QPoint(0, 0)).x() for w in cards) > 0, "⚠ 位置が決まっていない"
            right = max(w.mapTo(strip.widget(), QPoint(w.width() - 1, 0)).x() for w in cards)
            # ★いちばん右の札の右端まで、スクロールで届くこと
            assert right <= strip.viewport().width() + bar.maximum(), (
                "⚠⚠ %d 枚目にたどり着けません（右端 %d / 見える幅 %d ＋ 可動域 %d / 高さ %d）"
                % (count, right, strip.viewport().width(), bar.maximum(), height))
            # ⚠ 札は縮まない（★指示書 §5）
            assert all(w.width() == card_size(height)[0] for w in cards)


def test_中身の幅は札の数から決める(app):
    """⚠ `layout.sizeHint()` は札を足した直後に **(12, 8)** を返しました。

    ★時間に依存しないよう、**札の数から直に計算**します。
    """
    from dq3.ui.monster_panel import (STRIP_HEIGHT, Dq3MonsterStrip,
                                      card_size)

    strip = Dq3MonsterStrip()
    strip.resize(700, STRIP_HEIGHT)
    strip.show()
    strip.set_cards([_cards(monster_id=i, name="敵%d" % i) for i in range(8)])
    card_w = card_size(STRIP_HEIGHT)[0]
    margins = strip._row.contentsMargins()
    want = (margins.left() + margins.right() + 8 * card_w
            + 7 * strip._row.spacing())
    assert strip.widget().width() == want, (
        "⚠ 中身の幅が %d（★%d のはず）" % (strip.widget().width(), want))


def test_札が少ないときは窓いっぱい(app):
    """⚠ 狭いと背景が途切れて見えます（★横バーも出さない）。"""
    from dq3.ui.monster_panel import STRIP_HEIGHT, Dq3MonsterStrip

    strip = Dq3MonsterStrip()
    strip.resize(700, STRIP_HEIGHT)
    strip.show()
    strip.set_cards([_cards()])
    assert strip.widget().width() >= strip.viewport().width()
    assert strip.horizontalScrollBar().maximum() == 0
def test_到達しない行が残っていない():
    """⚠⚠ ★`return` の後ろに置かれた 1 行が、一度も実行されていなかった（RX3-0038）。

    ```python
    def _stats_of(self, monster_id):
        got = master_of(monster_id)
        return tuple(got) if got else ()
        self.monsters.setToolTip(self._enemy_tip(groups, fighting))  # ⚠⚠ 届かない
    ```

    ⚠ そのため `_enemy_tip()` は 1 度も呼ばれず、
      ★No-Spoiler のヒントが実機で**出ていませんでした**。
    ⚠⚠ 「動いていない」だけなので、**赤くならずに気づけません**。
    """
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "dq3" / "ui" / "battle_window.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for i, stmt in enumerate(body[:-1]):
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Continue, ast.Break)):
                bad.append("%s 行目のあとに %d 文" % (stmt.lineno, len(body) - i - 1))
    assert not bad, "⚠⚠ 到達しない行があります: %s" % bad
