"""画面レイアウトの**計算**（2026-08-01 の指示書 §3〜§4）。

★★ **2層**（★2026-08-21 / RX-0056 に実態へ直した）★★

    retroux/config/default_layout.yaml   標準（同梱・編集させない）
      ↓ ここで作業領域・FCEUX の実寸から座標を計算
    実行時の配置

⚠ 以前ここには「利用者が動かしたら `config/layout.yaml` に実座標を保存する」
  という**3層目**が書いてあり、`save()` / `load_saved()` / `clear()` も置いてあった。
  ★だがその層は**一度も動いていなかった**（2026-08-18 実測: ファイルは存在せず、
  製品コードから `save` / `load_saved` は呼ばれていない）。
  ★実際に配置を覚えているのは `retroux/ui/window_state.py`（`work/window-state.json`）。
  二重管理にしないため、ここには**計算だけ**を残す（指示書の §5〜§6 は window_state が担う）。

## ⚠⚠ **固定座標を使わない**（指示書 §3.1）

  設計の基準は 1920×1080 だが、実際には次のどれかで必ずずれる:

    ・タスクバーを除いた作業領域（上や左に置いている人もいる）
    ・DPI スケーリング（100 / 125 / 150%）
    ・複数モニター
    ・**FCEUX の実寸**（1280×960 を渡しても 784×731 に丸められる）

  だから `anchor`（どこを基準にするか）だけを設定に書き、
  **座標の計算はここに集約する**。

## 保存した配置を使わない場合（指示書 §6.2）

  ⚠ 「使えないなら全部やり直し」にしない。⚠ 軽微なはみ出しは**戻して収める**。
  ★戻せないほど違うとき（モニタ構成が変わった等）だけ標準へ落とす。
"""

from __future__ import annotations

import dataclasses
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_PATH = PROJECT_ROOT / "retroux" / "config" / "default_layout.yaml"

#: 窓の最小の大きさ（計算の下限。★掴めないほど小さい窓を作らない）。
#: 同梱 YAML の版（`default_layout.yaml` の `schema_version` / `layout_version`）。
SCHEMA_VERSION = 1
LAYOUT_VERSION = 1

MIN_WIDTH = 240
MIN_HEIGHT = 160

#: 保存・復元の対象（指示書 §5.1）。
#: ★`log` は 2026-08-09 に足した下段（戦闘ログ／出会ったモンスター）。
WINDOW_KEYS = ("emulator", "map", "main", "log")

#: ★★ 4区画（左・中・右・下）に組めるかの下限（2026-08-09 / 案1）★★
#:
#: ⚠⚠ **物理解像度ではなく、論理座標で判断します。**
#:   1920×1200 を 150% で使うと、アプリから見える作業領域は
#:   **1280×752** です（実測）。ここが配布先として一番狭い部類なので、
#:   ★この値で4区画が組めることを基準にしています。
#:
#: ⚠ 高さは「エミュレータ＋下段＋隙間」が要るので、実際に入るかは
#:   `_compute_four_pane()` が**測って**判断します。ここは足切りだけ。
FOUR_PANE_MIN_WIDTH = 1200
FOUR_PANE_MIN_HEIGHT = 700

#: 下段（ログ）の高さの目安（px）。
#: ⚠⚠ **2026-08-14 から「上限」ではありません。** ★余った高さは全部ログへ回します
#:   （`_compute_four_pane` を参照）。★設定で `windows.log.height` を書いたときだけ
#:   その値で頭を打ちます。ここは**説明と、設定を書く人のための目安**です。
LOG_DEFAULT_HEIGHT = 220
#: ⚠ 130 は「1920×1080 を 150% で使う画面（論理 1280×672）でも4区画に
#:   なる」ぎりぎりの値です（実測: そこでの下段は 136px）。
#:   ★ここを 150 にすると、配布先として一番多い構成が従来配置へ落ち、
#:     地図が 160px に潰れます。**低いほうの実害が小さい**ので 130。
LOG_MIN_HEIGHT = 130

#: 下段（ログ）の上限（px / 2026-08-18）。
#:
#: ⚠⚠ **余りを全部ログへ回すと、縦に長い画面で下段が半分を占めます。**
#:   ★1920x1080（タスクバー 48）では余り 275px で、ちょうどよい:
#:
#:       敵の札 約90px ＋ System Log 約12行
#:
#:   ⚠ ところが 1920x1440 のような画面では余りが 600px を超えます。
#:   ★そこまで要らないので、超えたぶんは**左右（地図・RetroUX）へ回します**
#:     （⚠ 地図は高いほど見やすい。ログは12〜15行あれば足ります）。
#:
#: ★この値は 1920x1080 と依頼者の画面（論理 1280x752）では**効きません**
#:   （★余りがこれより小さいため）。⚠ 縦に長い画面のためだけの歯止めです。
LOG_MAX_HEIGHT = 340


@dataclasses.dataclass
class Placement:
    """1つのウィンドウの置き場所。`width`/`height` が None なら大きさは変えない。"""

    x: int
    y: int
    width: int | None = None
    height: int | None = None

    def as_tuple(self):
        return (self.x, self.y, self.width, self.height)


def _read_yaml(path: pathlib.Path):
    import yaml

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"{path.name} を読めません: {exc}"
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"{path.name} の書き方が正しくありません: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, f"{path.name} の中身が辞書ではありません"
    return data, None


def load_default() -> dict:
    """同梱の標準レイアウト。⚠ 読めなくても落とさない（最低限の値で動く）。"""
    data, _ = _read_yaml(DEFAULT_PATH)
    if not isinstance(data, dict) or not data.get("windows"):
        # ★同梱が読めないのはこちらの落ち度。それでも並べられるようにする。
        return {
            "schema_version": SCHEMA_VERSION,
            "layout_version": LAYOUT_VERSION,
            "windows": {
                "emulator": {"anchor": "top_center", "offset_y": 8},
                "map": {"anchor": "below_emulator_left",
                        "offset_y": 10, "width": 600, "height": 320},
                "main": {"anchor": "below_emulator_right",
                         "offset_y": 10, "width": 700, "height": 320},
                "lua_script": {"visible": False, "behavior": "minimize",
                               "fallback": {"anchor": "bottom_left",
                                            "width": 240, "height": 160}},
            },
            "spacing": {"window_gap": 10, "screen_margin": 8},
        }
    return data


# --- 標準配置の計算（指示書 §3）--------------------------------------

def compute_standard(work_area, emulator_size, config=None) -> dict:
    """標準レイアウトの座標を計算する。

    引数:
        work_area: `(x, y, width, height)` 作業領域（**実測値**）
        emulator_size: `(width, height)` FCEUX の**実寸**
        config: `load_default()` の中身（省略すると読む）

    戻り値: `{"emulator": Placement, "map": ..., "main": ...}`

    ★★ **FCEUX の実寸を先に読む**（指示書 §3.3）★★
      MAP と RetroUX の縦位置は FCEUX の下端から決まるので、
      ⚠ 丸められた実寸を使わないと重なるか隙間が空く。

    ## ★★ 4区画（2026-08-09 / 依頼者の指示「案1でやる」）★★

        ┌──────────┬──────────────┬──────────┐
        │  地図    │    FCEUX     │  RetroUX │
        │          │  （ゲーム）  │  状態    │
        ├──────────┴──────────────┴──────────┤
        │   ログ / 出会ったモンスター        │
        └────────────────────────────────────┘

    ⚠ 入らない画面では**従来の配置へ落ちます**（`_compute_two_row`）。
      ★勝手に重ねたり画面外へ出したりしません。
    """
    cfg = config or load_default()
    four = _compute_four_pane(work_area, emulator_size, cfg)
    if four is not None:
        return four
    return _compute_two_row(work_area, emulator_size, cfg)


def _compute_four_pane(work_area, emulator_size, cfg) -> dict | None:
    """左・中・右・下。⚠ 入らなければ `None`（呼ぶ側が従来配置へ落とす）。

    ★★ **ゲーム画面の実寸は動かしません。** ★★
      ⚠ FCEUX は指定した大きさを内部倍率へ丸めるので、こちらで幅を決めても
        そのとおりにはなりません（`user_config.yaml` の注記）。
        ★測った実寸の**まわり**に置き場所を作ります。
    """
    windows = cfg.get("windows") or {}
    spacing = cfg.get("spacing") or {}
    gap = int(spacing.get("window_gap", 10))
    margin = int(spacing.get("screen_margin", 8))

    area_x, area_y, area_w, area_h = work_area
    emu_w, emu_h = emulator_size
    if area_w < FOUR_PANE_MIN_WIDTH or area_h < FOUR_PANE_MIN_HEIGHT:
        return None

    usable_w = area_w - margin * 2
    usable_h = area_h - margin * 2

    # --- 上段の高さ ＝ ゲーム画面の高さ（★ここが基準）
    top_h = max(emu_h, MIN_HEIGHT)
    # --- 下段: 残りから。⚠ 足りないなら4区画にしない（潰した窓を作らない）
    log_spec = windows.get("log") or {}
    room = usable_h - top_h - gap
    if room < LOG_MIN_HEIGHT:
        return None
    # ★★ **余った高さは全部ログへ**（2026-08-14 / 依頼者 / RX-0050）★★
    #
    #   > ログ・モンスター画面を極力ログとモンスターがたくさん表示される
    #   > ように直したので、画面の配置を各サブ画面の高さを見直しして
    #
    #   ⚠⚠ ここは長らく **220px で頭打ち**にしていた。★左右（地図・RetroUX）は
    #     ゲーム画面の高さに合わせて伸びるのに、下段だけ伸びない。
    #     実測（依頼者の画面 1920×1200 / FCEUX 774×752）:
    #
    #         使える高さ 1136 − 上段 752 − 隙間 10 = 余り 374px
    #         ⚠ なのにログは 220px。★**154px を黙って余らせていた**。
    #
    #   ★依頼者が手で伸ばして直したのが、まさにこの 154px 分。
    #   ⚠ 設定で `windows.log.height` を書いたときだけ、その値で頭を打つ
    #     （★同梱の `default_layout.yaml` には**書かない**）。
    want = log_spec.get("height")
    if want:
        log_h = min(int(want), room)
    else:
        # ★★ 余りはログへ。⚠ ただし `LOG_MAX_HEIGHT` で頭を打つ（2026-08-18）
        #   ⚠ 縦に長い画面で下段が半分を占めるのを防ぐ。
        #   ★超えたぶんは下の `top_h` へ回る（＝地図と RetroUX が高くなる）。
        log_h = min(room, LOG_MAX_HEIGHT)

    # ★★ **余った高さは左右（地図・RetroUX）へ**（2026-08-18）★★
    #   ⚠ `top_h` はゲーム画面の高さで始めたが、ログに回さないぶんは
    #     左右へ足してよい。★地図は高いほど見やすい。
    #   ⚠ FCEUX 自体は上端に置くので、はみ出さない。
    top_h = usable_h - log_h - gap

    # --- 左右: ゲーム画面の両脇。⚠ 二つとも掴める幅が要る
    sides = usable_w - emu_w - gap * 2
    if sides < MIN_WIDTH * 2:
        return None

    # ★★ **並び順と幅の配分は設定で決められる**（2026-08-18 / RX-0055）★★
    #
    #   依頼者の指示（推奨案 b）:
    #   ⚠ 全部を設定に出すと組み合わせが爆発して検査しきれない。
    #   ★実際に変えたくなる2つだけ出す:
    #
    #       layout:
    #         left_pane: map      # ★ゲーム画面の左に置くもの（map / main）
    #         side_split: 0.5     # ★左の割合（0.2〜0.8）
    #
    #   ⚠ 置き場は `config/user_config.yaml`。★同梱の `default_layout.yaml`
    #     は「利用者が編集する対象ではない」と書いてあるので、そこには置かない。
    pane = cfg.get("four_pane") or {}
    left_name = str(pane.get("left_pane", "map"))
    if left_name not in ("map", "main"):
        left_name = "map"           # ⚠ 知らない値は既定へ。★警告は下の関数
    left_w = _split_width(sides, pane.get("side_split", 0.5))
    right_w = sides - left_w

    left = area_x + margin
    top = area_y + margin
    emu_x = left + left_w + gap
    log_y = top + top_h + gap

    right_name = "main" if left_name == "map" else "map"
    return {
        left_name: Placement(left, top, left_w, top_h),
        "emulator": Placement(emu_x, top, None, None),
        right_name: Placement(emu_x + emu_w + gap, top, right_w, top_h),
        "log": Placement(left, log_y, usable_w, log_h),
    }


def _split_width(sides: int, want) -> int:
    """左の幅。⚠ 両方が `MIN_WIDTH` を下回らないところまでで止める。

    ★0.5 なら半分ずつ（従来どおり）。
    """
    try:
        ratio = float(want)
    except (TypeError, ValueError):
        ratio = 0.5
    ratio = max(0.2, min(0.8, ratio))
    got = int(sides * ratio)
    return max(MIN_WIDTH, min(got, sides - MIN_WIDTH))


def layout_complaints(pane: dict) -> tuple[str, ...]:
    """⚠⚠ **効かない設定を黙って受け取らない**（★この計画の決めごと）。

    ★「設定したのに効かない」が分からないのが、いちばん困る。
    """
    out = []
    left = pane.get("left_pane", "map")
    if left not in ("map", "main"):
        out.append(f"⚠ layout.left_pane に知らない値 {left!r}"
                   "（★使えるのは map / main。地図を左にします）")
    want = pane.get("side_split", 0.5)
    try:
        ratio = float(want)
    except (TypeError, ValueError):
        out.append(f"⚠ layout.side_split が数値ではありません: {want!r}"
                   "（★0.5 にします）")
    else:
        if not 0.2 <= ratio <= 0.8:
            out.append(f"⚠ layout.side_split {ratio} は範囲外"
                       "（★0.2〜0.8 に丸めます）")
    return tuple(out)


def _compute_two_row(work_area, emulator_size, config=None) -> dict:
    """⚠ 4区画が入らない画面向けの**従来配置**（2026-08-07 まで標準）。

    ★狭い画面ではこちらのほうが素直です。**消しません**。
    """
    cfg = config or load_default()
    windows = cfg.get("windows") or {}
    spacing = cfg.get("spacing") or {}
    gap = int(spacing.get("window_gap", 10))
    margin = int(spacing.get("screen_margin", 8))

    area_x, area_y, area_w, area_h = work_area
    emu_w, emu_h = emulator_size

    # --- FCEUX: 上端（横位置は anchor で決める / 指示書 §3.3）--------
    #
    # ★★ **`top_left` と `top_center` を選べる**（2026-08-01 / 依頼者の要望）★★
    #
    #   | anchor | 向いている画面 |
    #   | --- | --- |
    #   | `top_left` | **横に広い画面**。3840px で中央に置くと窓が右へ寄り、 |
    #   |            | 視線の移動が大きい。左上へ寄せるとひとかたまりになる |
    #   | `top_center` | 1920px 前後。左右の余りが少ないので中央が自然 |
    #
    #   ⚠ 下段（地図と RetroUX）も**同じ向きに寄せる**。片方だけ中央だと
    #     ちぐはぐになる。
    emu_spec = windows.get("emulator") or {}
    anchor = str(emu_spec.get("anchor", "top_center"))
    if anchor == "top_left":
        emu_x = area_x + margin
    else:
        emu_x = area_x + max(0, (area_w - emu_w) // 2)
    emu_x += int(emu_spec.get("offset_x", 0))
    emu_y = area_y + int(emu_spec.get("offset_y", 8))
    # ⚠ 画面からはみ出さない
    emu_x = max(area_x, min(emu_x, area_x + area_w - emu_w))
    emu_y = max(area_y, emu_y)

    # --- ★★★ RetroUX は**エミュレータの横**（2026-08-07 / 依頼者の指示）
    #
    #   > RetroUXのウィンドウは、エミュレータ画面の横に置いてほしい
    #
    #   ┌──────────────┬──────────────┐
    #   │    FCEUX     │              │
    #   │  ゲーム画面  │   RetroUX    │
    #   ├──────────────┤              │
    #   │     MAP      │              │
    #   └──────────────┴──────────────┘
    #
    # ⚠ 以前は「FCEUX の下に MAP と RetroUX を横並び」でした。
    #   ★横に長い画面では右が大きく余り、⚠ RetroUX が縦に潰れて
    #     戦闘ログが数行しか見えませんでした。
    map_spec = windows.get("map") or {}
    main_spec = windows.get("main") or {}
    map_w = int(map_spec.get("width", 600))
    main_w = int(main_spec.get("width", 700))

    bottom = area_y + area_h - margin
    right = area_x + area_w - margin

    # --- RetroUX: FCEUX の右。★縦は FCEUX の上端から下端いっぱいまで。
    main_x = emu_x + emu_w + gap
    main_y = emu_y
    # ⚠ 右へはみ出すなら幅を詰める（★画面外に出さない）
    main_w = max(MIN_WIDTH, min(main_w, right - main_x))
    main_h = max(MIN_HEIGHT, bottom - main_y)
    # ⚠⚠ **横に入りきらないときは、元の「下に並べる」へ戻す。**
    #   ★狭い画面で右へ押し出すと、RetroUX が画面外へ消えます。
    side_by_side = (main_x + MIN_WIDTH) <= right

    # --- MAP: FCEUX の真下（★左端をそろえる）
    map_x = emu_x
    map_y = emu_y + emu_h + gap
    map_w = max(MIN_WIDTH, min(map_w, (main_x - gap) - map_x))         if side_by_side else map_w
    # ⚠⚠ **画面外へ出さないことを最優先**（★従来からの決めごと）。
    #   FCEUX が高いと下に居場所がありません。そのときは
    #   ★重なってでも**画面の中**へ入れます（重なりは見れば分かるが、
    #     画面外は気づけない）。
    # ⚠⚠ **下いっぱいに伸ばさない**（2026-08-07 / 依頼者の指摘）。
    #   > MAP画面がすこし小さくても良い気がする。（被ってる）
    # ★設定の高さ（既定 320）を上限にします。下に余っても伸ばしません。
    map_h = max(MIN_HEIGHT, min(int(map_spec.get("height", 320)),
                                bottom - map_y))
    if map_y + map_h > bottom:
        map_y = max(area_y, bottom - map_h)
    main_h = max(MIN_HEIGHT, bottom - main_y)
    if main_y + main_h > bottom:
        main_y = max(area_y, bottom - main_h)

    if not side_by_side:
        # ⚠ 横に置けない画面。★従来どおり「FCEUX の下に横並び」。
        main_x = emu_x + map_w + gap
        main_y = map_y
        main_w = max(MIN_WIDTH, min(int(main_spec.get("width", 700)),
                                    right - main_x))
        main_h = map_h

    return {
        "emulator": Placement(emu_x, emu_y, None, None),
        "map": Placement(map_x + int(map_spec.get("offset_x", 0)),
                         map_y, map_w, map_h),
        "main": Placement(main_x + int(main_spec.get("offset_x", 0)),
                          main_y, main_w, main_h),
    }
