"""利用者・環境ごとの設定（MVP2 Phase 1 / 指示書「設定を user_config.yaml へ分離」）。

★なぜ分けるか:

  `retroux/plugins/dq2/config.yaml` は**ゲームの知識**（危険状態のしきい値、
  倒す順、呪文の指定…）で、これは**プロジェクトの資産**。Git で共有し、
  実機検証の結果が積み上がっている。

  一方「ROM をどこに置いたか」「画面をどこに出すか」「FCEUX の実行パス」は
  **その人の環境の話**で、他の人と共有する意味がない。同じファイルに混ぜると
  ・環境を変えるたびにゲーム知識のファイルが汚れる
  ・検証結果の差分にパスの変更が混ざって読みにくい
  という形で効いてくる。

★見つからなくても動く。 既定値はこのファイルに持つ（config.yaml が無くても
  9割モードで動く、という mantan.lua と同じ考え方）。

ファイルは `user_config.yaml`（リポジトリ直下 / Git 管理外）。
`user_config.example.yaml` を雛形として置いてある。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
USER_CONFIG_PATH = PROJECT_ROOT / "user_config.yaml"


@dataclass
class PathsConfig:
    """work/ 配下の出力先。既定のままで動く。"""

    rom: str = "work/rom/DQ2_J.nes"
    db: str = "work/retroux.sqlite3"
    events: str = "work/events.jsonl"
    command: str = "work/command.json"
    log: str = "work/retroux.log"
    # Lua が書く「いまの状態」（表示用。消えてよい / MVP2 Phase 2）
    state: str = "work/state.json"
    lock: str = "work/event_ingestor.lock"
    # セーブステートの世代バックアップの排他。
    # ★二重に動くと世代が倍の速さで流れ、**戻りたい世代が押し出される**。
    backup_lock: str = "work/savestate_backup.lock"


@dataclass
class LoggingConfig:
    """★★ まず `mode`、細かい調整が `level` / `gui_level`（2026-08-13）★★

    ## ★ mode（指示書 §19）

        normal      … 製品利用。⚠ **DEBUG を書かない**（§20）
        diagnostic  … 不具合調査。DEBUG から（§21）

    ⚠⚠ **Lua 側もこれを見ます**（`bridge.lua` の `Bridge.resolve_log_min`）。
      これを入れるまで Lua の行は段階を持たず、`level` を上げても
      ログの 63%（実測 33,578 行）が出続けていました。

    ## ⚠ 2026-08-09 の指示との関係

        > 画面にはださないが、ログボタンで見るとあとからわかる

    ★この形（ファイル DEBUG / 画面 INFO）は **diagnostic のとき**に残ります。
    ⚠ normal では**ファイルにも DEBUG を書きません**（指示書 §20 が優先）。

    ## ★ level / gui_level の扱い

    `mode` から決まる値が既定になり、**明示された場合だけ**そちらを使います
    （⚠ 昔の設定ファイルを黙って無視しないため）。
    """

    #: normal / diagnostic
    mode: str = "normal"
    #: ⚠ None は「書かれていない」。★mode から決める
    level: str | None = None
    gui_level: str | None = None
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5
    # GUI の System Log が保持する行数
    gui_lines: int = 500

    def resolved(self) -> dict[str, int]:
        """実際に使う下限を返す（`mode` を土台に、書かれていれば上書き）。

        ⚠ 書かれていない（None）ときだけ `mode` の値を使う。
          ★昔の `level: DEBUG` を持つ設定ファイルを黙って無視しない。
        """
        from ..logging_setup import _as_level, levels_for_mode

        got = levels_for_mode(self.mode)
        if self.level is not None:
            got["level"] = _as_level(self.level)
        if self.gui_level is not None:
            got["gui_level"] = _as_level(self.gui_level)
        return got

    @property
    def diagnostic(self) -> bool:
        return str(self.mode or "").strip().lower() == "diagnostic"


@dataclass
class ResearchConfig:
    """研究用の採取（2026-08-13 / 製品版ログ整理 §22）。

    ★★ **通常運用では走らせません。** ★★
      指示書 §20・§21 は NORMAL でも DIAGNOSTIC でも
      research capture を OFF と定めています。

    ⚠ ログの段階（`logging.mode`）とは**別**にしてあります。
      ★研究は「ログを多く出す」ことではなく「別の仕事をする」ことなので、
        第3のログレベルにすると混ざります（§22）。

    ⚠ 「絵を撮るのをやめる」話ではありません。★絵は
      `python -m dq2rom monsters extract`（ROM から）で 82 体そろっています。
    """

    #: 画面からの採取（モンスターの絵）。★既定は切
    capture: bool = False


@dataclass
class GuiConfig:
    """1920×1080 を基準にした画面（指示書 5.1）。"""

    width: int = 1920
    height: int = 1080
    # 画面更新の間隔（ミリ秒）。
    #
    # ★★ **500 → 200 にした**（2026-07-31 / 指示書 §10.4 の「周期の整理」）★★
    #
    #   ⚠⚠ 「もっさり」の正体は CPU ではなく**更新が秒2回しかない**ことだった。
    #     実測（`research/probes/reusable/measure_gui.py` / 本物のデータ 1875 件）:
    #
    #       直す前  7.3 ms/回   ← state読込 5.3ms（毎回 SQLite を叩いていた）
    #       直した後 1.1 ms/回   ← 変わっていなければ作り直さない
    #
    #     1.1ms なら 200ms 間隔でも **CPU の 0.6%** で足りる。
    #
    # ⚠ これ以上速くしても表示は新しくならない。Lua 側が state.json を
    #   **0.5秒ごと**にしか書かないため（`bridge.lua` の
    #   `command_poll_interval`）。そちらを速くするかは実機で測ってから。
    interval_ms: int = 200
    # エミュレータ画面を置く領域の目安（指示書 5.2 の 1280×960）
    emulator_width: int = 1280
    emulator_height: int = 960
    # 右端に置く RetroUX パネルの幅
    panel_width: int = 640
    # 起動時に最大化するか
    maximized: bool = False


@dataclass
class LayoutConfig:
    """4区画の並べ方（2026-08-18 / RX-0055 / 依頼者の指示「推奨案で」）。

    ★★ ⚠⚠ **なぜ `user_config.yaml` に置くのか** ★★

      `retroux/config/default_layout.yaml` は**同梱ファイル**で、
      ⚠ その冒頭に「利用者が編集する対象ではありません」と書いてある。
      ★編集させたい設定を、編集するなと書いたファイルへ置けない。

    ## ⚠ 全部は設定に出さない

      ★組み合わせが増えるほど、検査しきれなくなる。
      ⚠ 実際に変えたくなるのは次の2つのはず:

        ・地図と RetroUX を**入れ替えたい**
        ・地図をもっと**広く**したい

      ★細かい調整は、窓を手で動かせば `work/window-state.json` が覚える。

    ⚠ 4区画に**ならない**画面（狭い画面）では効かない。★従来の2段配置になる。
    """

    #: ★ゲーム画面の**左**に置くもの（`map` または `main`）。
    #:  ⚠ 知らない値は無視して警告する（★黙って既定へ倒さない）。
    left_pane: str = "map"
    #: ★左右の幅の配分。**左の割合**（0.2〜0.8）。
    #:  ⚠ 0.5 で半分ずつ（従来の挙動）。
    side_split: float = 0.5


@dataclass
class EmulatorConfig:
    """FCEUX ウィンドウの扱い（指示書 5.3）。

    ★埋め込み（SetParent）は既定で行わない。入力フォーカスとジョイパッドを
      壊す危険があり、指示書も「不安定なら無理に採用しない」としている。
      既定は **自動整列**（位置とサイズを合わせるだけ）。
    """

    # ウィンドウを探すときのタイトルの**先頭**（前方一致）
    window_title_contains: str = "FCEUX"
    # 起動時に FCEUX ウィンドウを所定位置へ動かすか
    align_window: bool = False
    # 並べる領域の左上（画面座標）
    align_x: int = 0
    align_y: int = 60
    # ★FCEUX の映像倍率。起動時に fceux.cfg の winsizemulx/y へ書き込む
    #   （retroux.tools.fceux_scale）。⚠ --xscale/--yscale は窓を変えない（実測）。
    #   既定 2 = 2倍。1 で等倍。新規展開の FCEUX は既定1倍なので、ここで2倍にする
    #   （依頼者 2026-08-20 / UAT）。
    window_scale: int = 2

    # --- Lua Script ウィンドウ ---------------------------------------
    # ★FCEUX を -lua 付きで起動すると必ず出る。閉じるとスクリプトが止まる。
    #   放っておくと**ゲーム画面の上に重なる**ので、置き場を決める。
    lua_window_title: str = "Lua Script"
    # ★★ **できるだけ小さくする**（2026-07-31 の指示書 §8）★★
    #
    #   この窓に入っているのは
    #     スクリプトのパス / Browse・Edit・Stop・Restart / 引数 / 出力コンソール
    #   だけ。⚠ **遊んでいる間は読まない**ので、置き場所を取る意味がない。
    #
    #   ⚠⚠ **閉じない・隠さない。** 閉じると Lua が止まる（README）。
    #     だから「小さくして避ける」以外に手が無い。
    #
    #   ★指示書の目標は 幅 200〜300 / 高さ 120〜220。その下限側を狙う。
    #     ⚠ FCEUX 側に最小サイズの制約があるので、**指定より大きくなること
    #       がある**。そのときは縮められるところまで縮まる（実機で確認する）。
    #     以前は 420×460 で、さらにその前は縦いっぱい（1020）だった。
    lua_window_width: int = 240
    #   ⚠ 0 以下にすると並べる領域の高さに戻る（従来の動き / 古い設定との互換）。
    lua_window_height: int = 160

    # ★FCEUX の大きさは変えない（既定）。
    #   1280×960 を指定しても実際には 784×731 になった。FCEUX は
    #   自分の表示倍率に合う大きさへ丸めるため、こちらの指定どおりにならない。
    #   **通らない指定を出し続けるより、実際の大きさを前提に並べる**。
    resize_emulator: bool = False


@dataclass
class NamesConfig:
    """画面に出すキャラの名前。

    ★**ゲーム内の名前は RAM から読めていない。**
      置き場所は分かった（$0113〜。逆アセンブルに `Name first half` とある）が、
      **かなの文字コード表が未確定**なので、推測で文字を当てて出すことはしない
      （items の日本語名と同じ方針）。

      分かるまでは、ここに書いた名前を使う。書かなければ内部名
      （lorasia / samaltria / moonbrooke）がそのまま出る。
    """

    lorasia: str = ""
    samaltria: str = ""
    moonbrooke: str = ""

    def label(self, key: str) -> str:
        return getattr(self, key, "") or key


@dataclass
class ShutdownConfig:
    """「終了」ボタンの動き（MVP2 Phase 1 / 依頼者の要望）。"""

    # セーブステートの保存先スロット（1〜9）。
    # ⚠ スロット0は使えない（savestate.object(0) は FCEUX をハングさせる）。
    # ⚠ **上書きされる。** 直前の内容は世代バックアップに残るので戻せるが、
    #   押す前に必ず確認を出すこと（GUI 側で確認ダイアログを出している）。
    save_slot: int = 1
    # セーブステートを保存してから終了するのを既定にするか
    save_by_default: bool = True
    # 保存できたという返事を待つ秒数
    save_timeout_seconds: float = 5.0


@dataclass
class BattleConfig:
    """戦闘AIの判断エンジン（2026-08-07 / 戦闘AI再設計 Phase 10A）。

    ⚠⚠ **ここは「利用者の選択」です。** ゲームの知識
    （`retroux/plugins/dq2/config.yaml`）とは分けてあります。
    ★起動のたびに Lua を再生成しても、この選択は消えません。

        legacy   … これまでどおり（★既定）
        layered  … ⚠ 新しい三層AIの拒否が効きます（★挙動が変わります）

    ## ⚠ なぜここに書くのか（2026-08-08 に踏んだ）

      `generate_lua.py` は `battle.engine` を読んで Lua に流し込みますが、
      ★こちら（画面が読む側）は `battle` を**知りませんでした**。
      その結果、実機のログに毎回こう出ていました:

          [WARNING] gui user_config.yaml: 知らない項目 battle は無視されます

      ⚠⚠ **これは嘘です。** 無視されていません（★ちゃんと効いています）。
      「効いていないのでは」と疑わせるだけの警告でした。
    """

    engine: str = "legacy"


@dataclass
class GamepadConfig:
    """ゲームパッド（XBOX / XInput）の入力（RX-0076 / 検証モード RX-0078）。

    ★★ 2系統ある入力を**別々に**切り替えられるようにしてある:
      - `enabled`          … RetroUX が XInput を読むか（False で完全 OFF）
      - `inject_nes_input` … NES 標準入力を RetroUX→FCEUX へ**注入するか**
    """

    # パッドを読むか。False なら XInput を一切読まない（キーボードのみ）。
    # ⚠ 環境変数 RETROUX_NO_GAMEPAD でも OFF にできる（そちらが優先）。
    enabled: bool = True
    # NES 標準入力（十字/A/B/Start/Select）を RetroUX から FCEUX へ注入するか。
    # ⚠ False にすると RetroUX は NES 入力を送らない（`work/gamepad_input.txt` へ
    #   常に 0 を書く）。NES 操作は **FCEUX 本体のパッド割当**に任せる（検証用）。
    # ★RetroUX 独自機能（LB/RB/LT/RT/X/Y）は False でも**従来どおり効く**。
    inject_nes_input: bool = True
    # ★切り分け検証用の DEBUG ログ（フォーカス・押したボタン）。既定 OFF。
    #   環境変数 RETROUX_GAMEPAD_DEBUG でも ON にできる。
    debug: bool = False
    # ★A/B を入れ替える（RX-0081 / 2026-08-20）。★既定 ON = ファミコン準拠。
    #   ファミコンは A=右・B=左（決定＝A＝右）。XBOX は A=下・B=右なので、
    #   ON にすると XBOX B→NES A / XBOX A→NES B（右ボタン＝決定）で自然になる。
    #   ⚠ XBOX 標準（A=下=決定）にしたいときは false。
    swap_ab: bool = True


@dataclass
class UserConfig:
    paths: PathsConfig = field(default_factory=PathsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    research: ResearchConfig = field(default_factory=ResearchConfig)
    gui: GuiConfig = field(default_factory=GuiConfig)
    emulator: EmulatorConfig = field(default_factory=EmulatorConfig)
    # ★4区画の並べ方（2026-08-18 / RX-0055）
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    shutdown: ShutdownConfig = field(default_factory=ShutdownConfig)
    names: NamesConfig = field(default_factory=NamesConfig)
    battle: BattleConfig = field(default_factory=BattleConfig)
    # ★ゲームパッド（RX-0076 / 検証モード RX-0078）
    gamepad: GamepadConfig = field(default_factory=GamepadConfig)
    # 読み込んだファイル（無ければ None）。GUI に出して迷わせないため。
    source: Path | None = None

    def path(self, name: str) -> Path:
        """`paths` の項目を絶対パスで返す。"""
        value = getattr(self.paths, name)
        p = Path(value)
        return p if p.is_absolute() else PROJECT_ROOT / p


def _fill(cls: type, data: Any) -> Any:
    """dict から dataclass を作る。**知らないキーは黙って捨てない。**

    捨てると「設定したのに効かない」に気づけない（CONFIG STALE と同じ話）。
    未知のキーは呼び出し側へ返して警告に使う。
    """
    known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    if not isinstance(data, dict):
        return cls(), []
    unknown = [k for k in data if k not in known]
    kwargs = {k: v for k, v in data.items() if k in known}
    return cls(**kwargs), unknown


def load(path: Path | str | None = None) -> tuple[UserConfig, list[str]]:
    """ユーザー設定を読む。戻り値: 設定, 警告の一覧。

    ★例外を投げない。設定ファイルが壊れていても**既定値で起動できる**ほうがよい
      （記録が止まるより、設定が効いていないことを警告で伝えるほうが害が小さい）。
    """
    target = Path(path) if path is not None else USER_CONFIG_PATH
    warnings: list[str] = []
    if not target.exists():
        return UserConfig(), warnings

    try:
        with target.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except (yaml.YAMLError, OSError) as exc:
        warnings.append(f"{target.name} を読めませんでした（既定値で起動します）: {exc}")
        return UserConfig(), warnings

    if not isinstance(raw, dict):
        warnings.append(f"{target.name} の形式が違います（既定値で起動します）")
        return UserConfig(), warnings

    sections = {
        "paths": PathsConfig, "logging": LoggingConfig,
        "gui": GuiConfig, "emulator": EmulatorConfig,
        # ★4区画の並べ方（2026-08-18 / RX-0055）
        "layout": LayoutConfig,
        "shutdown": ShutdownConfig, "names": NamesConfig,
        # ★ゲームパッド（RX-0076 / 検証モード RX-0078）
        "gamepad": GamepadConfig,
        # ⚠ `generate_lua.py` が読む項目。★ここに無いと
        #   「知らない項目」と**嘘の警告**が出ます（2026-08-08）。
        "battle": BattleConfig,
        # ⚠ `generate_lua.py` が読む項目。★ここに無いと
        #   「知らない項目」と**嘘の警告**が出る（2026-08-08 の経緯）。
        "research": ResearchConfig,
    }
    values: dict[str, Any] = {}
    for key, cls in sections.items():
        obj, unknown = _fill(cls, raw.get(key, {}))
        values[key] = obj
        for name in unknown:
            warnings.append(f"{target.name}: 知らない設定 {key}.{name} は無視されます")
    for key in raw:
        if key not in sections:
            warnings.append(f"{target.name}: 知らない項目 {key} は無視されます")

    return UserConfig(source=target, **values), warnings
