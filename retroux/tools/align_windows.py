"""FCEUX と RetroUX GUI を 1920×1080 に並べる（MVP2 Phase 1 / 指示書 5.3）。

    python -m retroux.tools.align_windows
    python -m retroux.tools.align_windows --list     # 見えているウィンドウを一覧

★**埋め込みではなく整列**です（DEV-26）。
  GUI の中に FCEUX を入れる（`SetParent`）と入力フォーカスとジョイパッドを
  壊す危険があるため、位置と大きさを合わせるだけにしてあります。
  フォーカスも奪いません（`SWP_NOACTIVATE`）。

並び（user_config.yaml で変えられます）:

```text
0        420                          1280                     1920
├─────────┼─────────────────────────────┼────────────────────────┤
│ Lua     │                             │ RetroUX GUI            │
│ Script  │   FCEUX（真ん中に置く）      │ 敵情報 / 戦闘ログ       │
│         │                             │ System Log             │
└─────────┴─────────────────────────────┴────────────────────────┘
```

★**ゲーム画面を真ん中にする**（依頼者の要望）。
  Lua Script ウィンドウは `-lua` 付き起動で必ず出るうえ、閉じると
  スクリプトが止まるので消せません。放っておくと**ゲーム画面の上に重なる**ので、
  左に居場所を作って追い出します。

★FCEUX の**大きさは変えません**（既定）。
  1280×960 を指定しても実際には 784×731 になりました。FCEUX は自分の表示倍率に
  合う大きさへ丸めるためです。通らない指定を出し続けるより、
  **実際の大きさを読んで、その真ん中に置く**ほうが確実です。
  倍率そのものを変えたいときは FCEUX 側の設定（Config > Video）で行います。

⚠ 見つからないウィンドウは**飛ばして続けます**。FCEUX だけ起動していて
  GUI がまだ立ち上がっていない、という状況が普通に起きるためです。
  ただし**何を飛ばしたかは必ず出します**（黙って何もしないのが一番困る）。
"""

from __future__ import annotations

import argparse
import sys
import time

from ..core import layout
# ★DQ2 の窓だけを探して動かす写し（RX-0145）。⚠ 題名だけで探すと、DQ3 の FCEUX・画面・
#   「ログ」窓まで動かす（`RetroUX DQ3 …` も `RetroUX` で始まる / 調査 D4）。
from ..core import dq2_window_align as window_align
from ..core.config import dq2_user_config as user_config_mod  # ★DQ2 専用の設定（RX-0147）

# ★**前方一致**で探す。「含む」で探すと、フォルダ名に RetroUX を含む
#   エクスプローラーなど**関係のないウィンドウを動かす**（実際に踏んだ / DEV-26）。
#   MainWindow が setWindowTitle しているタイトルの先頭と揃えること。
GUI_TITLE_PREFIX = "RetroUX"

#: 地図の窓（`map_window.py` の題名の前方一致）。
#  ★RetroUX 側が開く窓なので、**居るときだけ**並べる。
#  ⚠ 「見つかりません」を出すと、地図を閉じている人に毎回警告が出る。
MAP_TITLE_PREFIX = "見た地図"

#: 下段の窓（`log_window.py` の題名の前方一致 / 2026-08-09 の案1）。
#  ★地図と同じく「居るときだけ」並べます。
#  ⚠ `GUI_TITLE_PREFIX`（"RetroUX"）とは**前方一致でぶつかりません**
#    （こちらは「ログ」で始まるため）。★題名を変えるときは注意すること。
LOG_TITLE_PREFIX = "ログ"

#: FCEUX と RetroUX のあいだの隙間（px / 指示書 §7.4 は 8〜16px）。
#
# ★0 にしないこと。窓枠の影が重なって「くっついている」ように見え、
#   どちらの縁を掴めばよいのか分からなくなる。
GAP = 12


def _print_list(title_filter: str | None) -> int:
    # 一覧は「含む」でよい（動かさないので当たりすぎても害がない）
    windows = window_align.find_windows(title_filter or "", match="contains")
    if not windows:
        print("見えているウィンドウがありません。")
        return 1
    for w in windows:
        print(f"  {w.title}  ({w.x},{w.y}) {w.width}×{w.height}")
    return 0


def _wait_for(title: str, deadline: float) -> "window_align.WindowInfo | None":
    """ウィンドウが出るまで待つ。出なければ None。

    ★起動直後は**まだウィンドウが無い**。実際に踏んだ: 起動スクリプトから
      2.3 秒後に整列したが、Qt の起動が終わっておらず見つからなかった。
      固定の待ち時間で当てにいくと、速い環境では無駄に待ち、遅い環境では外す。
    """
    while True:
        found = window_align.find_windows(title, match="prefix")
        if found:
            return found[0]
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)


def layout_is_remembered() -> bool:
    """利用者が自分で配置を決めたか（`work/window-state.json` に `main` があるか）。

    ★★ **覚えているなら、自動整列は GUI を動かさない。** ★★

      ⚠⚠ これが無いと**「窓の位置を覚える」機能が無意味**になる。
        起動の手順は
          1. GUI が起動して保存した位置に復元する
          2. そのあと**手順7の自動整列が `SetWindowPos` で上書きする**
        なので、利用者から見ると「保存して終了しても位置がリセットされる」
        （2026-07-30 の実機確認 R-8 で判明）。

      ★どちらを勝たせるかの判断:
        自動整列は**初回に3枚を並べてあげる親切**であって、
        利用者が自分で動かした配置を毎回壊す権利は無い。
        だから**覚えている位置を優先**する。

    ★★ **窓ごとに扱いが違う。** ★★

      | 窓 | 自動整列で動かすか | なぜ |
      | --- | --- | --- |
      | RetroUX GUI | 覚えていれば**動かさない** | 位置を `window-state.json` に覚えている |
      | FCEUX 本体 | 覚えていれば**動かさない** | ★**FCEUX 自身が覚えている**（下記） |
      | Lua Script | **毎回動かす** | ⚠ 誰も覚えていない。放っておくと**ゲーム画面に重なる** |

      ★FCEUX は `tools/fceux/fceux.cfg` に自分で位置を書いている:
          MainWindow_wndx 425
          MainWindow_wndy 79
        つまり**こちらが毎回上書きしていた**だけで、
        動かさなければ FCEUX が自分で元の位置に戻る（2026-07-31 に確認）。

      ⚠ Lua Script の窓には対応する項目が `fceux.cfg` に**無い**ので、
        ここで並べないと毎回ゲーム画面の上に出てしまう。

      ⚠ 「整列」ボタンを押したときは**明示的な指示**なので全部動かす
        （`force=True`）。
    """
    return "main" in remembered_keys()


#: 窓ごとの下限。★`main_window.py` が `apply_to` に渡す値と揃えること。
#  ⚠ 下段のログ窓は横長で背が低いので、高さの下限だけ下げる。
_MIN_SIZE = {"main": (320, 240), "map": (320, 240), "log": (320, 120)}


def remembered_keys() -> set:
    """**使える形で**配置を覚えている窓の名前（RX-0101 / 2026-08-23）。

    ★★ 「記録がある」と「その記録で置けた」は別。 ★★

      ⚠⚠ ここは長らく `get("main")` が空でないかだけを見ていて、
        **3枚まとめて**「覚えている」と判断していた。実害:

        1. 小さすぎる記録は `apply_to` が弾き、窓は Qt の既定
           （画面中央・大きめ）で開く
        2. なのにここは True を返すので、自動整列が**全部飛ばす**
        3. ★誰も直さないまま、起動するたびに窓が重なる（依頼者の画面 / 08-23）

      ⚠ さらに、地図の記録が無くても `main` があれば地図まで飛ばしていた。
        `_ensure_map_window` は戻せなかったとき `arrange()` を呼ぶのに、
        ★その `arrange()` が同じ理由で地図を飛ばす——**歯止めどうしが
        打ち消し合っていた**。

    ⚠ 読めないときは**空**を返す（＝整列して見せる。重なったまま放置しない）。
    """
    try:
        from ..ui.window_state import WindowState
        from ..core import dq2_paths

        # ★置き場は DQ2 の resolver から（RX-0156 / ⚠ CWD に依らない）
        state = WindowState(dq2_paths.window_state())
        return {key for key, (mw, mh) in _MIN_SIZE.items()
                if state.remembers(key, min_width=mw, min_height=mh)}
    except Exception:                                  # noqa: BLE001
        return set()


def arrange(cfg, wait: float = 0.0,
            force: bool = False) -> "tuple[int, list[str]]":
    """設定どおりに3つのウィンドウを並べる。戻り値: 動かせた数, 報告の行。

    ★GUI のボタンとコマンドの**両方がここを呼ぶ**。
      同じ並びを2か所に書くと、片方だけ直したときに静かにずれる。

    ⚠ `force=False`（起動時の自動整列）では、GUI の位置を覚えている場合に
      **GUI だけ飛ばす**。`force=True`（整列ボタン）は必ず動かす。
    """
    emu = cfg.emulator
    x, y = emu.align_x, emu.align_y
    area_w, area_h = cfg.gui.width, cfg.gui.height - y

    # ★★ **作業領域を実測して使う**（2026-07-31 の指示書 §7.3）★★
    #   ⚠ 設定の座標をそのまま使うと、タスクバーの位置・DPI・モニタ構成の
    #     どれかが違うだけでずれる。実測できたときは**そちらを優先**する。
    #   ★取れないとき（Windows 以外・API 失敗）は設定の値で動く。
    measured = window_align.work_area() if window_align.available() else None
    if measured is not None:
        area_x, area_y, area_w, area_h = measured
        x, y = area_x, area_y

    lua_w = emu.lua_window_width
    panel_w = cfg.gui.panel_width
    deadline = time.monotonic() + max(0.0, wait)

    moved = 0
    messages: list[str] = []

    def size_of(title: str):
        """いまの大きさ。無ければ None。★**指定した値ではなく実寸**。"""
        found = window_align.find_windows(title, match="prefix")
        return (found[0].width, found[0].height) if found else None

    def resize(title: str, pw, ph) -> None:
        """大きさだけ当てる（位置は動かさない）。

        ⚠ 小さすぎる指定は Qt が拒否する。**拒否されてよい**。
          そのあと実寸を読んで位置を決めるので、ここは「試すだけ」。
        """
        if pw is None or ph is None:
            return
        found = window_align.find_windows(title, match="prefix")
        if not found:
            return
        try:
            window_align.align(title, x=found[0].x, y=found[0].y,
                               width=pw, height=ph)
        except window_align.WindowAlignError:
            pass                        # ⚠ 大きさは best effort（位置が本題）

    def place(title: str, px: int, py: int,
              pw: "int | None" = None, ph: "int | None" = None) -> None:
        nonlocal moved
        if _wait_for(title, deadline) is None:
            # ★飛ばすが黙らない。まだ起動していないだけのことも多い。
            messages.append(f"飛ばしました（{title}）: 見つかりません")
            return
        try:
            info = window_align.align(title, x=px, y=py, width=pw, height=ph)
        except window_align.WindowAlignError as exc:
            messages.append(f"飛ばしました（{title}）: {exc}")
            return
        moved += 1

        # ★★ **置いたあとに実測して収め直す**（2026-08-01 / 実測で判明）★★
        #
        #   ⚠⚠ **指定した大きさになるとは限らない。**
        #     Qt の窓には**最小サイズ**があり、それより小さくできない。
        #     実測: 下段の高さを 320 と指定したのに
        #       RetroUX は 932、地図は 686 になった（縮まなかった）。
        #     その結果、地図の下端が作業領域を **112px はみ出した**。
        #
        #   ★はみ出したぶんだけ**戻して収める**。計算をやり直すのではなく、
        #     実際になった大きさを見て位置を直すほうが確実。
        want_w, want_h = info.width, info.height
        fixed_x = max(x, min(info.x, x + area_w - want_w))
        fixed_y = max(y, min(info.y, y + area_h - want_h))
        if (fixed_x, fixed_y) != (info.x, info.y):
            try:
                info = window_align.align(title, x=fixed_x, y=fixed_y)
                messages.append(
                    f"収め直し: {info.title} -> ({info.x},{info.y})"
                    f" {info.width}×{info.height}"
                    "（指定より大きくなったため）")
            except window_align.WindowAlignError:
                pass                    # ⚠ 直せなくても整列は成功のまま
        messages.append(
            f"整列: {info.title} -> ({info.x},{info.y}) {info.width}×{info.height}")

    # ★★ 覚えている配置を壊さない（R-8 / 上の `layout_is_remembered`）★★
    #   ⚠ Lua Script は**あとで必ず並べる**（誰も位置を覚えていないため）。
    keep = set() if force else remembered_keys()

    def skip(title: str) -> None:
        # ⚠ 飛ばすが**黙らない**。「整列したのに動かない」と思われるため
        messages.append(
            f"飛ばしました（{title}）: "
            "配置を覚えているため動かしません（「整列」ボタンで強制できます）")

    # ★★★ 並び（2026-08-01 の指示書 §3.2）★★★
    #
    #   ┌──────────── 作業領域 ─────────────┐
    #   │           ┌──────────────┐        │  FCEUX  : 上端・横中央
    #   │           │    FCEUX     │        │  MAP    : FCEUX の下・左
    #   │           └──────────────┘        │  RetroUX: FCEUX の下・右
    #   │     ┌──────────┐ ┌──────────┐     │  Lua    : 最小化
    #   │     │   MAP    │ │ RetroUX  │     │
    #   │     └──────────┘ └──────────┘     │
    #   └──────────────────────────────────┘
    #
    # ⚠⚠ **FCEUX を先に置き、その実寸を読んでから下段を置く。**
    #   FCEUX は指定した大きさを内部倍率に合わせて丸めるので
    #   （1280×960 → 784×731）、計算で決め打ちすると重なるか隙間が空く。
    #
    # ★左右の空きは**埋めない**（指示書 §3.6）。将来の常時表示領域。

    # --- FCEUX: 上端・横中央 -------------------------------------------
    # ★★ FCEUX は**自分で位置を覚えている**（`fceux.cfg` の `MainWindow_wndx/y`）。
    #   だから動かさなければ、FCEUX が自分で元の位置に戻す。
    #   ⚠ 実機で「RetroUX の窓は覚えるのに FCEUX は戻らない」と指摘された
    #     （2026-07-31）。こちらが毎回上書きしていたのが原因だった。
    # ★★ 4区画の並べ方を利用者の設定から渡す（2026-08-18 / RX-0055）★★
    #   ⚠ 効かない値は**黙って受け取らない**（★この計画の決めごと）。
    pane = {"left_pane": getattr(cfg.layout, "left_pane", "map"),
            "side_split": getattr(cfg.layout, "side_split", 0.5)}
    messages.extend(layout.layout_complaints(pane))
    layout_cfg = {**layout.load_default(), "four_pane": pane}

    found = _wait_for(emu.window_title_contains, deadline)
    emu_size = (found.width, found.height) if found is not None \
        else (cfg.gui.emulator_width, cfg.gui.emulator_height)
    standard = layout.compute_standard((x, y, area_w, area_h), emu_size,
                                       layout_cfg)

    if "main" in keep:
        # ★FCEUX は自分で位置を覚えている（`fceux.cfg`）。本体を動かさない
        #   ときは、こちらも触らないほうが「前回のまま」になる。
        skip(emu.window_title_contains)
    elif found is None:
        messages.append(
            f"飛ばしました（{emu.window_title_contains}）: 見つかりません")
    else:
        width = cfg.gui.emulator_width if emu.resize_emulator else None
        height = cfg.gui.emulator_height if emu.resize_emulator else None
        spot = standard["emulator"]
        place(emu.window_title_contains, spot.x, spot.y, width, height)
        # ★動かしたあとを読み直し、実寸で下段を計算し直す
        after = _wait_for(emu.window_title_contains, deadline) or found
        standard = layout.compute_standard(
            (x, y, area_w, area_h), (after.width, after.height), layout_cfg)

    # --- MAP と RetroUX: FCEUX の下 ------------------------------------
    #
    # ★★★ **大きさを先に決め、実寸を読んでから位置を決める** ★★★
    #
    #   ⚠⚠ Qt の窓には**最小サイズ**がある。それより小さい指定は拒否され、
    #     ⚠ **そのとき位置の指定まで無視される**（実測で判明 / 2026-08-01）:
    #
    #       指定: (1875, 978) 700×320
    #       実際: (1875, 382) 750×916   ← y が別の値になっている
    #
    #     計算どおりに並ばない原因がこれだった。FCEUX で使っている
    #     「実寸を読んでから決める」を、こちらの窓にも同じように使う。
    if True:
        # ★★ **窓ごとに決める**（RX-0101）。⚠ まとめて飛ばすと、
        #   記録の無い窓が既定の場所（画面中央）に置き去りになる。
        has_map = ("map" not in keep) and bool(
            window_align.find_windows(MAP_TITLE_PREFIX, match="prefix"))
        # ★下段の窓は4区画のときだけ（`layout.py` が `log` を返すかで分かる）
        has_log = ("log" in standard) and ("log" not in keep) and bool(
            window_align.find_windows(LOG_TITLE_PREFIX, match="prefix"))
        has_main = "main" not in keep
        for name, title in (("main", GUI_TITLE_PREFIX),
                            ("map", MAP_TITLE_PREFIX),
                            ("log", LOG_TITLE_PREFIX)):
            if name in keep:
                skip(title)
        # 1. 大きさだけ先に当てる（位置はまだ気にしない）
        if has_main:
            resize(GUI_TITLE_PREFIX, standard["main"].width,
                   standard["main"].height)
        if has_map:
            resize(MAP_TITLE_PREFIX, standard["map"].width,
                   standard["map"].height)
        if has_log:
            resize(LOG_TITLE_PREFIX, standard["log"].width,
                   standard["log"].height)

        # 2. **実際になった大きさ**を読む
        main_size = (size_of(GUI_TITLE_PREFIX) if has_main else None) or (
            standard["main"].width, standard["main"].height)
        map_size = size_of(MAP_TITLE_PREFIX) if has_map else None
        log_size = size_of(LOG_TITLE_PREFIX) if has_log else None

        # 3. 実寸ではみ出さないように寄せるだけ
        #
        # ⚠⚠⚠ **置き場所を決めるのは `layout.py` だけ**（2026-08-07 に踏んだ）。
        #   ここには**独自の並べ直し**が残っていて、`layout.py` で
        #   「RetroUX を FCEUX の横へ」と変えても ⚠ **こちらが下段へ
        #   戻していました**。★測り方が2か所にあると、片方だけ直しても
        #   静かに効かなくなります（今日それで1周しました）。
        #   → ★`standard` の座標をそのまま使い、⚠ ここは
        #     「実寸が大きくてはみ出すぶんだけ引き戻す」ことに徹します。
        def _fit(spot, size):
            w, h = size or (spot.width, spot.height)
            px = max(x, min(spot.x, x + area_w - w))
            py = max(y, min(spot.y, y + area_h - h))
            return px, py

        if map_size:
            mx, my = _fit(standard["map"], map_size)
            place(MAP_TITLE_PREFIX, mx, my)
        if has_main:
            gx, gy = _fit(standard["main"], main_size)
            place(GUI_TITLE_PREFIX, gx, gy)
        if log_size:
            lx, ly = _fit(standard["log"], log_size)
            place(LOG_TITLE_PREFIX, lx, ly)

    # --- Lua Script: 最小化（指示書 §9）--------------------------------
    # ★★ 閉じると Lua が止まるので**閉じない**。最小化なら処理は続く。 ★★
    #   ⚠ 隠す（SW_HIDE）にはしない。タスクバーからも消えて
    #     利用者が**戻す手段を失う**。
    #   ★調査用に「Lua Script ウィンドウを出す」で戻せる（指示書 §9.2）。
    if window_align.minimize(emu.lua_window_title):
        moved += 1
        messages.append(f"最小化: {emu.lua_window_title}")
    else:
        # ⚠ 最小化できない環境では、隅へ小さく置いて避ける（逃げ道）
        lua_h = min(getattr(emu, "lua_window_height", 160) or 160, area_h)
        place(emu.lua_window_title, x, y + area_h - lua_h, lua_w, lua_h)

    # --- 最後に操作先をゲームへ返す（指示書 §8 / 受入条件14）------------
    # ★★ **並べ終わったら FCEUX を前面に。** ★★
    #   整列自体はフォーカスを奪わないが、⚠ 起動の途中で Lua Script や
    #   この画面が前に出ることがある。そのまま渡すと
    #   **キーを押してもゲームが動かない**（何が悪いのか分かりにくい）。
    #
    # ⚠ 失敗しても整列は成功扱いのまま。Windows は前面化を拒否することがあり、
    #   そこで整列ごと失敗にすると「並んだのにエラー」になる。
    if window_align.available():
        if not window_align.focus(emu.window_title_contains):
            messages.append(
                "ゲーム画面を前面にできませんでした"
                "（キーが効かないときは FCEUX を1回クリックしてください）")

    return moved, messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FCEUX と GUI を並べる")
    parser.add_argument("--config", default=None, help="user_config.yaml のパス")
    parser.add_argument("--list", action="store_true",
                        help="見えているウィンドウを一覧して終了")
    parser.add_argument("--filter", default=None, help="--list で絞り込む文字列")
    parser.add_argument("--wait", type=float, default=0.0,
                        help="ウィンドウが出るまで待つ秒数（起動直後に使う）")
    # ★既定では、位置を覚えている GUI は動かさない（R-8）。
    #   ⚠ 起動スクリプトの自動整列は**これを付けない**。
    parser.add_argument("--force", action="store_true",
                        help="覚えている位置を無視して GUI も並べ直す")
    # ★--gui-only / --emulator-only は**置かない**。
    #   3つの位置は互いの大きさから決まる（FCEUX は残りの真ん中）ので、
    #   一部だけ動かすと並びが崩れる。効かない選択肢を残すほうが害が大きい。
    args = parser.parse_args(argv)

    # ★他のアプリのウィンドウ名を出すので、**この端末で表示できない文字が来る**。
    #   実際に踏んだ: 濁点の結合文字（U+3099）を含むタイトルで
    #   `UnicodeEncodeError: 'cp932' codec ...` になり、一覧が途中で落ちた。
    #   自分が出す文字ではないので、置き換えてでも表示を続ける。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    if not window_align.available():
        print("この環境ではウィンドウ整列に対応していません（Windows のみ）",
              file=sys.stderr)
        return 1

    if args.list:
        return _print_list(args.filter)

    cfg, warnings = user_config_mod.load(args.config)
    for warning in warnings:
        print(f"警告: {warning}", file=sys.stderr)

    # ★★ **ログ基盤をここで立てる**（RX-0104 / 2026-08-23）★★
    #   ⚠⚠ 2026-08-23 に `get_logger("align")` で結果を書くようにしたのに、
    #     `work/retroux.log` には **1行も出ていませんでした**。
    #     ★このコマンドは GUI とは**別のプロセス**で走ります。
    #       立ち上げるのは `gui.py` / `record.py` / `savestate_backup.py` だけで、
    #       ここは誰も基盤を立てていないため、書き先がありませんでした。
    #   ⚠ 「ログを足した」だけで確かめないと、こうなります。
    log_handle = None
    try:
        from ..core.logging_setup import setup_logging

        log_handle = setup_logging(
            cfg.path("log"),
            level=cfg.logging.resolved()["level"],
            max_bytes=cfg.logging.max_bytes,
            backup_count=cfg.logging.backup_count,
        )
    except Exception as exc:                           # noqa: BLE001
        print(f"警告: ログを立てられません: {exc}", file=sys.stderr)

    moved, messages = arrange(cfg, wait=args.wait, force=args.force)

    # ★★ **結果をログにも残す**（RX-0101 / 2026-08-23）★★
    #   ⚠ これまで `retroux.log` には「整列します」だけが残り、
    #     **何を動かして何をなぜ飛ばしたかが1行も残っていなかった**。
    #   ★配置がおかしいと言われたときに、後から切り分けられない。
    try:
        from ..core.logging_setup import get_logger

        log = get_logger("align")
        log.info("整列: %d 枚を動かしました", moved)
        for line in messages:
            log.info("整列 %s", line)
    except Exception:                                  # noqa: BLE001
        pass          # ⚠ ログに書けなくても整列は成功のまま
    finally:
        if log_handle is not None:
            log_handle.shutdown()      # ★書き終わるまで待つ（別プロセスなので）

    for line in messages:
        if line.startswith("飛ばしました"):
            print(line, file=sys.stderr)
        else:
            print(line)
    return 0 if moved else 1


if __name__ == "__main__":
    raise SystemExit(main())
