"""通常歩行の学習をやめたことを固定する（製品版ログ整理 Phase 4 / 指示書 §12・§16）。

## ★ なぜやめたか（実測 / `docs/audit/log-inventory.md`）

    MapEdge              2,117 行   ← 通常歩行で「通れた」
    MapBlockedDirection    496 行   ← 通常歩行で「進めなかった」
    VisitedTile         78,460 行
    ---------------------------------------------------
    MapTransition          346 行   ← ★ROM からは作れない（これは残す）

⚠ 通常歩行の学習が、残すべき遷移の **234 倍**。
★しかも中身は **ROM に最初から入っている**（`docs/design/navigation-passability.md`）。

## ⚠⚠ ここで見ていること

  1. 既定で edge / blocked を**記録しない**
  2. ★遷移（`MapTransition`）は**記録し続ける**
     ⚠ ここが一緒に切れていると「静かになった」ではなく「壊れた」
  3. 通常歩行で**ログ行が出ない**
  4. 同じ「想定外の座標変化」を**繰り返し出さない**

★1 と 2 を両方見るのが要です。⚠ 片方だけだと、全部切っても緑になります。
"""

from __future__ import annotations

import logging
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from retroux.core.db.database import Database  # noqa: E402
from retroux.core.navigation import (NavigationObserver,  # noqa: E402
                                     NavigationRepository)
from retroux.core.navigation.repository import Thresholds  # noqa: E402

HASH = "T" * 64
MAP_ID, MAP_PTR = 0x07, 0x8E83
TIMEOUT = 30


class Recorder(logging.Handler):
    """出た行をそのまま貯める。★件数と本文の両方を見る。"""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def setup(tmp_path):
    db = Database(tmp_path / "n.sqlite3")
    db.register_rom(HASH, "テストROM", "JP", mapper=2)
    repo = NavigationRepository(db, HASH, Thresholds(blocked_probable=3))
    log = logging.getLogger("test.navigation")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    handler = Recorder()
    log.handlers = [handler]
    # ★引数を渡さない（＝既定のまま）。ここが今回の要
    observer = NavigationObserver(repo, move_timeout_frames=TIMEOUT, logger=log)
    yield observer, repo, handler
    db.close()


def _state(x, y, *, frame=0, direction=None, map_id=MAP_ID, ptr=MAP_PTR):
    from retroux.core.bridge.state_reader import GameState

    return GameState(fresh=True, in_battle=False, frame=frame,
                     map_id=map_id, map_x=x, map_y=y, map_data_pointer=ptr,
                     input_direction=direction)


# --- 1. 通常歩行は記録しない ---------------------------------------------

def test_既定では通常歩行のedgeを記録しない(setup):
    observer, repo, _ = setup
    observer.observe(_state(3, 3))
    observer.observe(_state(3, 4))          # 1マス下へ歩いた
    assert repo.edges(MAP_ID, MAP_PTR) == [], "通常歩行の edge が記録されている"


def test_既定では進めない方向を記録しない(setup):
    observer, repo, _ = setup
    observer.observe(_state(3, 3, frame=0, direction="down"))
    observer.observe(_state(3, 3, frame=TIMEOUT + 1, direction="down"))
    got = repo.blocked(MAP_ID, MAP_PTR) if hasattr(repo, "blocked") else []
    assert not got, "進めない方向が記録されている"


def test_既定では通常歩行のログが出ない(setup):
    observer, _, handler = setup
    observer.observe(_state(3, 3))
    observer.observe(_state(3, 4))
    observer.observe(_state(4, 4))
    bad = [ln for ln in handler.lines if "新しい道" in ln or "進めない方向" in ln]
    assert bad == [], f"通常歩行のログが出ている: {bad}"


# --- 2. ⚠ 遷移は残っていること（★ここが要）-------------------------------

def test_マップをまたぐ遷移は記録し続ける(setup):
    """⚠⚠ これが無いと「静かになった」ではなく「壊れた」。

    ★旅の扉・階段・ピット・ワープは ROM 解析だけでは分からない（§16）。
    """
    observer, repo, _ = setup
    observer.observe(_state(3, 3))
    observer.observe(_state(15, 1, map_id=0x08, ptr=0x8EE3))
    got = repo.transitions() if hasattr(repo, "transitions") else None
    assert got, "マップをまたぐ遷移まで記録しなくなっている"


# --- 3. 重複の抑止 --------------------------------------------------------

def test_同じ想定外の座標変化は一度しか出さない(setup):
    """⚠ 実測 1,535 行。同じ座標対が 12 回出ていた（§3）。

    ⚠ 行ったり来たりすると (10,10)->(14,10) と (14,10)->(10,10) の
      **2 通り**が鳴ります。★それぞれが 1 回ずつになるのが正解。
      （5 往復すれば、抑止が無ければ 10 行出ます）
    """
    observer, _, handler = setup
    for _ in range(5):
        observer.observe(_state(10, 10))
        observer.observe(_state(14, 10))      # ★隣ではない＝想定外の跳び
    jumps = [ln for ln in handler.lines if "想定外の座標変化" in ln]
    assert len(jumps) == 2, f"5 往復で {len(jumps)} 行出ている（抑止が効いていない）"
    forward = [ln for ln in jumps if "(10,10) -> (14,10)" in ln]
    assert len(forward) == 1, f"同じ跳び方が {len(forward)} 回: {jumps}"


def test_違う跳び方は別々に出す(setup):
    """⚠ 抑止しすぎて**別の異常を隠さない**こと。

    ⚠ 続けて観測すると間の移動も跳びとして数えられるので、
      ★あいだで場所の記憶を切る（読めない状態を1つ挟む）。
    """
    from retroux.core.bridge.state_reader import GameState

    observer, _, handler = setup
    unreadable = GameState(fresh=False, in_battle=False, frame=0,
                           map_id=None, map_x=None, map_y=None,
                           map_data_pointer=None, input_direction=None)
    observer.observe(_state(10, 10))
    observer.observe(_state(14, 10))
    observer.observe(unreadable)              # ★ここで記憶が切れる
    observer.observe(_state(20, 20))
    observer.observe(_state(24, 20))
    jumps = [ln for ln in handler.lines if "想定外の座標変化" in ln]
    assert len(jumps) == 2, f"違う跳び方が {len(jumps)} 件: {jumps}"


# --- 4. 研究用に取り直せること --------------------------------------------

def test_設定を経由する道でも既定が切(tmp_path):
    """⚠⚠ **2か所そろっているか**を見る。

    `NavigationObserver` の既定だけ切にしても、`gui.py` が

        record_edges=bool(cfg.get("record_edges", True))

    と**自分の既定**を持っていると、実運用では入のままになります。
    ★片方だけ直して「切った」と思い込むのを防ぎます。
    """
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "retroux" / "gui.py").read_text(encoding="utf-8")
    for key in ("record_edges", "record_blocked"):
        assert f'cfg.get("{key}", True)' not in source, (
            f"gui.py の {key} の既定が入のまま")
        assert f'cfg.get("{key}", False)' in source, (
            f"gui.py に {key} の既定が見つからない")
    # ★遷移は入のままであること（⚠ 一緒に切っていないか）
    assert 'cfg.get("record_transitions", True)' in source, (
        "遷移まで切っている（★ROM 解析では作れない / §16）")


def test_設定で戻せる(tmp_path):
    """★やめたのは既定であって、仕組みではない。"""
    db = Database(tmp_path / "n2.sqlite3")
    db.register_rom(HASH, "テストROM", "JP", mapper=2)
    repo = NavigationRepository(db, HASH, Thresholds(blocked_probable=3))
    observer = NavigationObserver(repo, move_timeout_frames=TIMEOUT,
                                  record_edges=True)
    observer.observe(_state(3, 3))
    observer.observe(_state(3, 4))
    assert repo.edges(MAP_ID, MAP_PTR), "入にしても記録されない（仕組みごと壊れている）"
    db.close()
