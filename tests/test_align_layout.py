"""ウィンドウの並べ方のテスト（2026-08-01 の指示書 §3・§18.1）。

    ┌──────────── 作業領域 ─────────────┐
    │ ┌──────────────┐                  │  FCEUX  : 上端・左（既定）
    │           │    FCEUX     │        │  MAP    : FCEUX の下・左
    │           └──────────────┘        │  RetroUX: FCEUX の下・右
    │     ┌──────────┐ ┌──────────┐     │  Lua    : 最小化
    │     │   MAP    │ │ RetroUX  │     │
    │     └──────────┘ └──────────┘     │
    └──────────────────────────────────┘

⚠⚠ **並びは2度変わっている。**
  1. 最初: `[Lua] [FCEUX(真ん中)] [RetroUX]` の横並び
  2. 2026-07-31: FCEUX を左上、RetroUX をその右
  3. 2026-08-01: **ゲーム画面を主役にする**（上端）。
     RetroUX と MAP はその下へ。空きは将来の常時表示領域として空ける。
     ★横の寄せ方は設定（`anchor`）。⚠ 既定は **`top_left`**
     （依頼者の画面が 3840px 幅で、中央だと窓が右へ寄りすぎるため）。

★★ **実測を基準にする理由** ★★
  FCEUX は指定した大きさを内部倍率に合わせて丸める（1280×960 → 784×731）。
  計算で決め打ちすると、隙間が空いたり重なったりする。

Win32 は叩けないので、**どこへ動かそうとしたか**を捕まえて確かめる。
"""

from __future__ import annotations

import pytest

from retroux.core.config.user_config import UserConfig
from retroux.core.window_align import WindowInfo
from retroux.tools import align_windows


@pytest.fixture(autouse=True)
def _forget_gui_position(monkeypatch):
    """★**「位置を覚えていない」状態を既定にする。**

    ⚠⚠ ここを明示しないと、開発機に `work/window-state.json` が
      あるかどうかで**テストの結果が変わる**（2026-07-30 に実際に踏んだ。
      R-8 の修正を入れた瞬間、既存の並びのテストが 3 -> 2 で落ちた）。

    ★並びの計算を試すテストは「覚えていない」前提で書く。
      覚えている場合の挙動は専用のテストで見る。
    """
    monkeypatch.setattr(align_windows, "layout_is_remembered",
                        lambda: False)


#: テストで使う作業領域。**FHD からタスクバー 40px を引いた形**。
#
# ⚠⚠ ここを固定しないと、走らせた機械のモニタ構成で結果が変わる
#   （実際、実測を入れた直後に 796×1552 という別の値が返って落ちた）。
#   ★作業領域そのものの取り方は `test_window_align.py` で見る。
AREA = (0, 0, 1920, 1040)

#: FCEUX の実測サイズ。1280×960 を指定しても 784×731 になる（実測）。
EMU_W, EMU_H = 784, 731

#: 地図の窓の題名（`align_windows` が持つ定義をそのまま使う）。
#  ⚠ テスト側で文字列を書き直さない。書くと片方だけ直したときに気づけない。
MAP = align_windows.MAP_TITLE_PREFIX


#: ⚠⚠ **Qt の窓には最小サイズがある**（2026-08-01 に実測で判明）。
#
#   指定: (1875, 978) 700×320
#   実際: (1875, 382) 750×916   ← 小さすぎる指定は拒否され、
#                                  **そのとき位置の指定まで無視される**
#
# ★模型にこれを入れておかないと、「計算どおりに並ぶ」テストだけが緑になり、
#   実機で並ばない状態を見逃す（実際に見逃した）。
MIN_SIZE = {"RetroUX": (788, 754), "見た地図": (600, 686)}

#: ⚠⚠ **1920×1080 には標準レイアウトが収まらない**（2026-08-01 に実測）。
#
#   FCEUX 731 ＋ 隙間 10 ＋ RetroUX の最小高 754 = 1495 > 1040
#
#   ★依頼者の画面は 3840×1552 なので収まる。1080p では収まらない。
#     そのときは**重なってでも画面の中**へ入れる（画面外は気づけないため）。
#   下段の並びを確かめるテストは、収まる大きさで行う。
TALL_AREA = (0, 0, 3840, 1552)


@pytest.fixture
def placements(monkeypatch):
    """align を差し替えて、指示した位置を記録する。"""
    class _Calls(dict):
        """記録の入れ物。★要求値も添えて持てるようにする。"""
        requested: dict = {}

    calls = _Calls()
    # ★いまの位置と大きさ（`arrange` は置いた結果を読み直す）
    state: dict[str, tuple] = {}
    # ★「大きさを指定したか」だけを別に持つ（FCEUX は指定しないのが正しい）
    requested: dict[str, tuple] = {}

    def current(title):
        return state.get(title, (0, 0, EMU_W, EMU_H))

    def fake_wait(title, deadline):
        x, y, w, h = current(title)
        return WindowInfo(handle=1, title=title, x=x, y=y, width=w, height=h)

    def fake_align(title, x, y, width=None, height=None, match="prefix"):
        _, _, cur_w, cur_h = current(title)
        if width is None or height is None:
            w, h = cur_w, cur_h          # 位置だけ動かす（SWP_NOSIZE）
        else:
            # ★最小サイズより小さい指定は**拒否される**
            min_w, min_h = MIN_SIZE.get(title, (0, 0))
            w, h = max(width, min_w), max(height, min_h)
        state[title] = (x, y, w, h)
        # ★★ 記録するのは **実際になった位置と大きさ**（要求値ではない）★★
        #   ⚠ 要求値で判定すると、拒否されて別の場所に居ても緑になる。
        #     実機で並ばない状態を見逃した原因がこれ。
        calls[title] = state[title]
        requested[title] = (width, height)
        return WindowInfo(handle=1, title=title, x=x, y=y, width=w, height=h)

    monkeypatch.setattr(align_windows, "_wait_for", fake_wait)
    monkeypatch.setattr(align_windows.window_align, "align", fake_align)
    monkeypatch.setattr(align_windows.window_align, "available", lambda: True)
    monkeypatch.setattr(align_windows.window_align, "work_area",
                        lambda handle=None: AREA)
    # ★地図は「開いている」前提にする。閉じている場合は専用のテストで見る。
    monkeypatch.setattr(
        align_windows.window_align, "find_windows",
        lambda title, match="contains": [fake_wait(title, 0)])
    # ★Lua は最小化できる前提。できない場合は専用のテストで見る。
    monkeypatch.setattr(align_windows.window_align, "minimize",
                        lambda title, **kw: True)
    monkeypatch.setattr(align_windows.window_align, "focus",
                        lambda title, **kw: True)
    calls.requested = requested          # type: ignore[attr-defined]
    return calls


def test_three_windows_are_placed(placements):
    """★FCEUX・RetroUX・MAP。⚠ Lua は最小化なので `place` を通らない。"""
    moved, messages = align_windows.arrange(UserConfig())

    assert "FCEUX" in placements and "RetroUX" in placements
    assert moved >= 2


def test_the_game_is_at_the_top(placements):
    """★★ 本題その1: ゲーム画面が主役（指示書 §3.3）★★

    ⚠ 画面の高さではなく作業領域を使う。タスクバーの位置は人によって違う。
    ★横の寄せ方は設定（`anchor`）で決まる。既定は `top_left`。
    """
    align_windows.arrange(UserConfig())
    x, y, w, h = placements["FCEUX"]

    area_x, area_y, area_w, _ = AREA
    # ★★ 2026-08-09（案1）: ゲーム画面は**左右のパネルに挟まれます**。★★
    #   ⚠ 以前は左上詰めでした。4区画では横位置が両脇の幅で決まるので、
    #     「左端に寄っている」は成り立ちません。★挟まれていることを見ます。
    assert x > area_x, "左に地図の居場所がない"
    assert x + w < area_x + area_w, "右に RetroUX の居場所がない"
    # ★上端＋わずかな余白（指示書 §3.3 は 0〜12px）
    assert area_y <= y <= area_y + 12, f"上端から離れすぎ: {y}"
    # ★大きさは**指定しない**（FCEUX が内部倍率で丸めてしまうため）
    assert placements.requested["FCEUX"] == (None, None)
    assert (w, h) == (EMU_W, EMU_H), "大きさを変えてしまっている"


def test_the_map_is_below_and_the_panel_is_beside_the_game(
        placements, monkeypatch):
    """★★ **地図は FCEUX の下、RetroUX は横**（2026-08-07 / 依頼者の指示）。

        > RetroUXのウィンドウは、エミュレータ画面の横に置いてほしい

    ⚠ 以前は「MAP と RetroUX を FCEUX の下に横並び」でした。
      ★横に広い画面では右が大きく余り、RetroUX が縦に潰れて
        戦闘ログが数行しか見えませんでした。

    ⚠ 計算で決め打ちしないこと。FCEUX は指定サイズを丸めるので、
      渡した数値と実際の大きさが一致しません。
    """
    monkeypatch.setattr(align_windows.window_align, "work_area",
                        lambda handle=None: TALL_AREA)
    align_windows.arrange(UserConfig())
    ex, ey, _, _ = placements["FCEUX"]
    mx, my, mw, mh = placements[MAP]
    gx, gy, gw, gh = placements["RetroUX"]

    # ★★ 2026-08-09（案1）: 地図は FCEUX の**左**、RetroUX は**右**。★★
    #   ⚠ 2026-08-07 までは「地図は FCEUX の下」でした。
    assert mx + mw <= ex, "MAP が FCEUX に重なっている"
    assert my == ey, "MAP の上端が FCEUX とそろっていない"
    # ★★ RetroUX は**横**。⚠ 下ではない。
    assert gx >= ex + EMU_W, "RetroUX が FCEUX に重なっている"
    assert gy == ey, "RetroUX の上端が FCEUX とそろっていない"
    # ⚠⚠ **横に置く意味は「縦に伸ばせること」**（★数行しか見えないなら無意味）
    assert gh > EMU_H // 2, f"RetroUX が低すぎます: {gh}"


def test_the_lower_row_follows_the_same_anchor(placements, monkeypatch):
    """★下段も FCEUX と**同じ向き**に寄る（片方だけ中央にしない）。

    ⚠ 一度 `align_windows` 側にも中央の計算が残っていて、設定を
      `top_left` にしてもこちらが中央へ戻していた（実測で判明）。
      **寄せ方を決めるのは `layout.py` だけ。**
    """
    monkeypatch.setattr(align_windows.window_align, "work_area",
                        lambda handle=None: TALL_AREA)
    align_windows.arrange(UserConfig())
    ex, _, _, _ = placements["FCEUX"]
    mx, _, _, _ = placements[MAP]

    # ★★ 2026-08-09（案1）: 地図は左端から始まります。★★
    #   ⚠ 「下段」という並びが無くなったので、寄せ方ではなく
    #     **作業領域の左端に付いていること**を見ます。
    #   ★寄せ方を決めるのが `layout.py` だけ、という元の狙いは変わりません。
    assert mx - TALL_AREA[0] <= 20, f"地図が左端から離れている: {mx}"
    assert mx < ex, "地図が FCEUX より右にある"


def test_the_log_window_goes_to_the_bottom_row(placements):
    """★★ 下段の窓も `layout.py` の座標へ置く（2026-08-09 / 案1）★★

    ⚠⚠ ここが抜けていると、**下段だけ既定の位置に取り残されます**。
      ★地図と同じで「居るときだけ」並べる作りなので、登録を忘れても
        エラーにならず、静かに置き去りになります。
    """
    align_windows.arrange(UserConfig())
    ex, ey, _, _ = placements["FCEUX"]
    lx, ly, lw, _lh = placements[align_windows.LOG_TITLE_PREFIX]

    assert ly >= ey + EMU_H, "下段が FCEUX に重なっている"
    assert lx - AREA[0] <= 16, f"下段が左端から始まっていない: {lx}"
    assert lw > EMU_W, "下段が端まで伸びていない"


def test_the_map_is_not_a_thin_sidebar(placements):
    """⚠ 地図は正方形か横長になりやすい。細い縦長にしない（指示書 §3.4）。"""
    align_windows.arrange(UserConfig())
    _, _, w, h = placements[MAP]
    # ★禁じられているのは「**細い**縦長サイドバー」。
    #   ⚠ 縦長そのものは禁止ではない（実測 600×686 ＝ ほぼ正方形）。
    #   「細い」を比で決める: 幅が高さの 0.7 倍を下回ったら細長すぎる。
    assert w >= 400, f"細すぎる: {w}"
    assert w / h >= 0.7, f"細い縦長になっている（{w}×{h}）"


def test_the_map_is_skipped_quietly_when_it_is_closed(placements, monkeypatch):
    """⚠ 地図を閉じている人に毎回「見つかりません」を出さない。"""
    monkeypatch.setattr(align_windows.window_align, "find_windows",
                        lambda title, match="contains": [])
    _, messages = align_windows.arrange(UserConfig())
    assert MAP not in placements
    assert not any("見た地図" in m for m in messages), messages


def test_the_lua_window_is_minimized(placements, monkeypatch):
    """★★ 本題その3: Lua Script は**最小化**（指示書 §9）★★

    ⚠ 閉じると Lua が止まる。隠す（SW_HIDE）とタスクバーからも消えて
      戻す手段を失う。**最小化**が唯一の正解。
    """
    called: list = []
    monkeypatch.setattr(align_windows.window_align, "minimize",
                        lambda title, **kw: called.append(title) or True)

    align_windows.arrange(UserConfig())

    assert called == ["Lua Script"], "最小化していない"
    assert "Lua Script" not in placements, "最小化したのに位置も動かしている"


def test_a_window_that_cannot_be_minimized_is_tucked_into_a_corner(
        placements, monkeypatch):
    """⚠ 最小化できない環境でも、主要領域を占有させない（逃げ道）。"""
    monkeypatch.setattr(align_windows.window_align, "minimize",
                        lambda title, **kw: False)

    align_windows.arrange(UserConfig())

    x, y, w, h = placements["Lua Script"]
    area_x, area_y, area_w, area_h = AREA
    assert (x, y + h) == (area_x, area_y + area_h), "隅へ寄せていない"
    assert w <= 300 and h <= 220, f"大きすぎる: {w}×{h}"


def test_nothing_is_placed_outside_the_work_area(placements):
    """⚠ 画面外へ出さない（受入条件4）。"""
    align_windows.arrange(UserConfig())
    area_x, area_y, area_w, area_h = AREA
    for title, (x, y, w, h) in placements.items():
        assert x >= area_x, f"{title} が左へはみ出した"
        assert y >= area_y, f"{title} が上へはみ出した"
        if w is not None:
            assert x + w <= area_x + area_w, f"{title} が右へはみ出した"
        if h is not None:
            assert y + h <= area_y + area_h, f"{title} が下へはみ出した"


def test_the_map_default_size_is_kept_when_there_is_room(placements):
    """★下段の高さは設定値。⚠ ただし画面に入らなければ詰める。"""
    align_windows.arrange(UserConfig())
    _, my, _, mh = placements[MAP]
    assert mh > 0
    assert my + mh <= AREA[1] + AREA[3], "下へはみ出している"


def test_a_tall_game_window_shrinks_the_lower_row(placements, monkeypatch):
    """⚠ FCEUX が大きいと下段の余りが減る。**画面外へ出さずに詰める**。"""
    tall = 900

    def fake_wait(title, deadline):
        return WindowInfo(handle=1, title=title, x=0, y=0,
                          width=EMU_W, height=tall)

    monkeypatch.setattr(align_windows, "_wait_for", fake_wait)
    align_windows.arrange(UserConfig())

    _, my, _, mh = placements[MAP]
    assert my + mh <= AREA[1] + AREA[3], "はみ出した"
    assert mh > 0, "高さが無くなった"


def test_resize_emulator_option(placements):
    """resize_emulator: true のときだけ大きさを指定する。"""
    cfg = UserConfig()
    cfg.emulator.resize_emulator = True
    align_windows.arrange(cfg)

    _, _, w, h = placements["FCEUX"]
    assert (w, h) == (1280, 960)


def test_missing_window_is_skipped_not_fatal(monkeypatch):
    """見つからないウィンドウは飛ばす。**ただし黙らない。**

    ⚠ 前面化も試すので、実機の状態に左右されないよう固定する
      （固定しないと開発機で FCEUX が動いているかどうかで結果が変わる）。
    """
    monkeypatch.setattr(align_windows, "_wait_for", lambda title, deadline: None)
    monkeypatch.setattr(align_windows.window_align, "available", lambda: True)
    monkeypatch.setattr(align_windows.window_align, "focus",
                        lambda title, **kw: True)
    # ⚠⚠ **`find_windows` も固定する。**
    #   固定しないと、開発機で地図の窓が開いているかどうかで
    #   飛ばした数が 3 と 4 で変わる（実際に踏んだ / 2026-08-01）。
    monkeypatch.setattr(align_windows.window_align, "find_windows",
                        lambda title, match="contains": [])
    monkeypatch.setattr(align_windows.window_align, "minimize",
                        lambda title, **kw: False)

    moved, messages = align_windows.arrange(UserConfig())

    assert moved == 0
    skipped = [m for m in messages if "飛ばしました" in m]
    # ★FCEUX / RetroUX / Lua Script の3つ。
    #   ⚠ 地図は**開いていなければ黙って飛ばす**ので数に入らない
    #     （閉じている人に毎回警告を出さないため）。
    assert len(skipped) == 3, messages


# --- 覚えている位置を壊さない（R-8 / 2026-07-30）------------------------

def test_a_remembered_layout_survives_the_startup_align(placements,
                                                        monkeypatch):
    """★★ **これが R-8 の本題。** ★★

    ⚠⚠ 起動の手順はこうなっている:
        1. GUI が起動して、保存した位置に復元する
        2. そのあと**手順7の自動整列が `SetWindowPos` で上書きする**

      だから利用者から見ると
      **「保存して終了しても窓の位置がリセットされる」**（実機で判明）。

    ★★ **窓ごとに扱いが違う**（2026-07-31 に FCEUX も対象へ）★★

    | 窓 | 自動整列で動かすか | なぜ |
    | --- | --- | --- |
    | RetroUX GUI | **動かさない** | `window-state.json` に覚えている |
    | FCEUX 本体 | **動かさない** | ★`fceux.cfg` の `MainWindow_wndx/y` に**自分で**覚えている |
    | Lua Script | **動かす** | ⚠ 誰も覚えていない。放っておくとゲーム画面に重なる |
    """
    monkeypatch.setattr(align_windows, "layout_is_remembered",
                        lambda: True)

    moved, messages = align_windows.arrange(UserConfig())

    assert "RetroUX" not in placements, "覚えている GUI の位置を上書きしている"
    assert "FCEUX" not in placements, \
        "FCEUX を上書きしている（fceux.cfg の記憶が毎回消える）"
    # ★Lua だけは並べる（誰も覚えていないため）
    assert MAP not in placements, "覚えている地図の位置を上書きしている"
    # ★Lua だけは扱う（誰も覚えていないため）。
    #   ⚠ 最小化なので `place` を通らない＝記録には残らない。
    assert placements == {}
    assert moved == 1, "Lua を最小化した1件だけのはず"
    # ★飛ばしたことを黙らない（「整列が効かない」と誤解されるため）
    assert sum("覚えている" in m for m in messages) == 2, messages


def test_the_align_button_can_still_force_the_gui_into_place(placements,
                                                             monkeypatch):
    """★「整列」ボタンは**明示的な指示**なので、覚えていても動かす。

    ⚠ ここが効かないと、一度動かした窓を元の並びへ戻す手段が無くなる。
    """
    monkeypatch.setattr(align_windows, "layout_is_remembered",
                        lambda: True)

    cfg = UserConfig()
    moved, messages = align_windows.arrange(cfg, force=True)

    # ★覚えていても、ボタンなら標準の位置へ並べ直す
    assert "FCEUX" in placements, "ボタンなら FCEUX も並べ直すこと"
    assert "RetroUX" in placements and MAP in placements
    ex, ey, _, _ = placements["FCEUX"]
    mx, my, _, _ = placements[MAP]
    gx, gy, _, _ = placements["RetroUX"]
    # ★★ 新しい並び（2026-08-09 / 案1）: 地図は**左**、RetroUX は**右**。
    #   ⚠ 2026-08-07 は「地図は下」でした。★上端は3つともそろいます。
    assert mx < ex < gx, "左・中・右の並びになっていない"
    assert my == ey, "地図の上端が FCEUX とそろっていない"
    assert gy == ey, "RetroUX の上端が FCEUX とそろっていない"
    assert moved >= 3


def test_fceux_remembers_its_own_position_in_its_config():
    """★★ **FCEUX は自分で位置を覚えている**（2026-07-31 に確認）★★

    ⚠ だから「戻らない」のは FCEUX のせいではなく、
      **こちらが毎回上書きしていた**のが原因だった。
      動かさなければ FCEUX が自分で元の位置に戻す。

    ★この事実に依存して「FCEUX を動かさない」を決めたので、
      前提が消えたら気づけるようにしておく。
    """
    import pathlib

    cfg = (pathlib.Path(__file__).resolve().parents[1]
           / "tools" / "fceux" / "fceux.cfg")
    if not cfg.exists():
        pytest.skip("fceux.cfg がありません")
    text = cfg.read_text(encoding="utf-8", errors="replace")
    assert "MainWindow_wndx" in text, "FCEUX が位置を覚える項目が無い"
    assert "MainWindow_wndy" in text
    # ⚠ Lua Script の窓には対応する項目が**無い**（だから毎回並べる）
    assert "LuaPosX" not in text


def test_an_unreadable_state_file_falls_back_to_aligning(monkeypatch, tmp_path):
    """⚠ 覚えているか分からないときは**整列する側**に倒す。

    ★並べて見せるほうが安全（位置が変わるだけ）。
      逆に倒すと、窓が重なったまま何も直せない状態になりうる。
    """
    from retroux.ui import window_state

    def boom(*_a, **_k):
        raise OSError("読めない")

    monkeypatch.setattr(window_state.WindowState, "__init__", boom)
    assert align_windows.layout_is_remembered() is False


def test_no_saved_state_means_align_normally(monkeypatch, tmp_path):
    """★初回起動（覚えていない）では、ふつうに3枚並べる。"""
    from retroux.ui import window_state

    monkeypatch.setattr(window_state, "DEFAULT_PATH",
                        tmp_path / "window-state.json")
    assert align_windows.layout_is_remembered() is False


# --- 並べ終わったら操作先をゲームへ返す（指示書 §8 / 受入条件14）--------

def test_the_game_gets_the_focus_back_after_arranging(placements, monkeypatch):
    """★★ **キーを押してもゲームが動かない、をやらない。** ★★

    整列自体はフォーカスを奪わないが、⚠ 起動の途中で Lua Script や
    この画面が前に出ることがある。最後にゲームへ返す。
    """
    called: list = []
    monkeypatch.setattr(align_windows.window_align, "focus",
                        lambda title, **kw: called.append(title) or True)

    align_windows.arrange(UserConfig())

    assert called == ["FCEUX"], "ゲーム画面を前面へ戻していない"


def test_a_refused_focus_does_not_fail_the_arrange(placements, monkeypatch):
    """⚠ Windows は前面化を拒否することがある。**整列ごと失敗にしない。**

    ★ただし黙らない（キーが効かないときの直し方を出す）。
    """
    monkeypatch.setattr(align_windows.window_align, "focus",
                        lambda title, **kw: False)

    moved, messages = align_windows.arrange(UserConfig())

    assert moved >= 3, "前面化に失敗しただけで整列が失敗扱いになっている"
    assert any("前面にできませんでした" in m for m in messages)
