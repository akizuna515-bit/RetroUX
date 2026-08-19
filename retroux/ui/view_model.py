"""GUI の ViewModel（P6）。

**Qt に依存しない。** View から分離しておくことで、画面を起動せずに
表示ロジックを検証できる（指示書の「将来拡張を考慮し ViewModel を分離する」）。

View は `poll()` が返す `UiState` を描画するだけにする。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from ..core.bridge.state_reader import GameState, StateReader
from ..core.db.database import Database
from ..core.recorder import Recorder



def _to_local(iso: str) -> str:
    """UTC で保存している時刻を、見る人の地域の時刻へ直す。

    ★画面に 05:03 と出ていたが、実際に戦ったのは 14:03（JST）だった。
      保存は UTC のままでよい（機械が比べるため）。**表示だけ**直す。
    """
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso).astimezone().isoformat()
    except ValueError:
        return iso


# --- 見せ方の「調子」（2026-08-01 の分割 / 指示書 §7.2）------------------
#
# ★★ **色そのものは持たない。** ★★
#   ⚠ 色は画面の都合であって、状態の意味ではない。ここが `#8fd18f` を
#     知っていると、配色を変えるたびに ViewModel を直すことになる。
#   ★意味だけを返し、`main_window.py` が色へ直す。

TONE_OK = "ok"
"""思ったとおりに動いている。"""
TONE_INFO = "info"
"""ふだんと違うが、問題ではない（戦闘中・高速化中など）。"""
TONE_MUTED = "muted"
"""とくに言うことがない。"""
TONE_CAUTION = "caution"
"""⚠ 止まっている・解除されている。**気づいてほしい**。"""
TONE_DANGER = "danger"
"""⚠⚠ 本当に危ない。"""


@dataclass(frozen=True)
class Badge:
    """画面に出す1つの値と、その調子。"""

    text: str
    tone: str = TONE_MUTED


@dataclass(frozen=True)
class BattleRow:
    """戦闘ログ1行ぶんの表示用データ。"""

    battle_id: int
    started_at: str
    monsters: str
    is_first_encounter: bool
    is_boss: bool
    speed_applied: float | None
    duration_seconds: float | None
    saved_seconds: float | None
    """等速で戦っていた場合と比べて何秒縮んだか。"""
    drops: str = "-"
    """この戦闘に出た敵が**落としうる**もの（ROM の表 / 確率つき）。

    ⚠ **実際に落ちたものではない。** 何を拾ったかは記録していない
      （検知手段が未特定）。「落ちる可能性がある物」であることを
      画面の見出しでも分かるようにする。
    """


@dataclass(frozen=True)
class UiState:
    """画面に出す内容のスナップショット。"""

    in_battle: bool = False
    speed: float = 1.0
    danger: bool = False
    current_monsters: str = "-"
    battles_recorded: int = 0
    warnings: list[str] = field(default_factory=list)
    rows: list[BattleRow] = field(default_factory=list)
    saved_seconds_total: float = 0.0
    average_speed: float = 0.0
    read_only: bool = False
    """閲覧専用（別の取り込みプロセスが動いている / 指示書 6.3）。"""
    danger_reason: str | None = None
    """危険と判断した理由。「読めていない」と本当の危険を区別するために出す。"""
    game: GameState = field(default_factory=GameState)
    """Lua が見ている**いまの値**（パーティHP・敵・AI判断 / MVP2 Phase 2）。

    ★記録（DB）とは別の経路で来る。DB は「起きたこと」、これは「いまの値」。
    """

    # ★パーティを読めないときの理由（Lua の is_danger のフェイルセーフ）。
    #   タイトル画面ではパーティ領域がまだ意味を持たないため、ここに落ちる。
    UNREADABLE = "パーティ状態を読めない"

    @property
    def state_label(self) -> str:
        if self.danger:
            # ★「危険状態」と「まだ読めていない」を混ぜない。
            #   タイトル画面で赤い『危険状態』が出っぱなしになり、
            #   壊れているように見えていた（実際は安全側へ正しく倒れている）。
            if self.danger_reason and self.UNREADABLE in self.danger_reason:
                return "待機中（セーブ未読込）"
            return "危険状態"
        return "戦闘中" if self.in_battle else "フィールド"

    @property
    def is_real_danger(self) -> bool:
        """本当に危ない状態か（読めていないだけ、を除く）。"""
        if not self.danger:
            return False
        return not (self.danger_reason and self.UNREADABLE in self.danger_reason)

    # --- 画面に出す値（2026-08-01 に main_window.py から移した / §7.2）----
    #
    # ★★ **同じ state なら同じ結果になる**（指示書 §7.3）★★
    #   widget も Windows API も SQLite も触らない。だから画面を建てずに試せる。

    @property
    def state_tone(self) -> str:
        """状態欄の調子。

        ⚠ 「読めていない」を赤くしない。タイトル画面で赤い『危険状態』が
          出っぱなしになり、壊れて見えた（安全側へ正しく倒れていただけ）。
        """
        if self.is_real_danger:
            return TONE_DANGER
        return TONE_INFO if self.in_battle else TONE_MUTED

    @property
    def speed_badge(self) -> Badge:
        """速度は**言葉でも出す**（仕様書 7.3「等速 / Turbo」）。

        ⚠ 「×1」だけだと、倍速が効いているのか等速なのか読み取りにくい。
        """
        speed = self.speed or 0
        if speed <= 1.01:
            return Badge("等速", TONE_MUTED)
        return Badge(f"Turbo ×{speed:g}", TONE_INFO)

    @property
    def gold_text(self) -> str:
        """所持ゴールド。

        ⚠ 届いていないときは **`-`**。0 と書くと「無一文」に見える
          （★0 と 不明 を混ぜない）。
        """
        gold = getattr(self.game, "gold", None)
        return "-" if gold is None else f"{gold:,}"

    @property
    def auto_badge(self) -> Badge:
        """★★ AUTO の状態（仕様書 7.3）★★

        ⚠ 「手動に戻った」ことが分からないと、利用者は
          「自動戦闘が壊れた」と思う。**理由まで出す。**

        ★★ **止まった理由まで出す**（2026-07-31 の指示書 §6.3）★★
          「OFF」とだけ出ていると、切ってあるのか安全機構で止まったのか
          区別が付かない。⚠ **切ってあるとき**と**止められたとき**は別物。
        """
        game = self.game
        reason = getattr(game, "danger_reason", None)
        if getattr(game, "force_auto", False):
            # ★「強制AUTO」は第3のモードとして見せない（指示書 §4）。
            #   AUTO の一形態＝安全停止をこの戦闘だけ外している、と書く。
            return Badge("ON（この戦闘は安全停止を解除）", TONE_CAUTION)
        if getattr(game, "auto_enabled", None) is False:
            return Badge("OFF（自分で操作）", TONE_MUTED)
        if getattr(game, "manual_latched", False):
            return Badge(f"停止（{reason}）" if reason else "停止（この戦闘は手動）",
                         TONE_CAUTION)
        if getattr(game, "auto_input", False):
            return Badge("ON", TONE_OK)
        # ★AUTO は入っているのに動いていない＝安全機構で止まっている。
        return Badge(f"停止（{reason}）" if reason else "停止", TONE_CAUTION)

    @property
    def mode_text(self) -> str:
        """★閲覧専用は「壊れている」ではなく「別プロセスが記録中」。

        ⚠ 区別できないと、直せる問題を直せない問題だと思ってしまう。
        """
        return ("閲覧専用（別プロセスが記録中）" if self.read_only
                else "このGUIが記録中")

    @property
    def monsters_text(self) -> str:
        """出ている敵。★数が分かるなら `名前×2` の形で出す。"""
        groups = getattr(self.game, "enemy_groups", None)
        if not groups:
            return self.current_monsters
        return ", ".join(f"{g.name}×{g.count}" if g.count > 1 else g.name
                         for g in groups)

    @property
    def warning_text(self) -> str | None:
        """警告。**無ければ None**（呼ぶ側が欄ごと隠せるように）。"""
        if not self.warnings:
            return None
        return "⚠ " + "\n⚠ ".join(self.warnings)


class ViewModel:
    """Recorder と DB から、画面に出す状態を組み立てる。"""

    def __init__(self, recorder: Recorder, db: Database, rom_hash: str,
                 monsters: Mapping[int, str] | None = None,
                 *, log_limit: int = 50, read_only: bool = False,
                 state_path=None, monster_stats: Mapping[int, dict] | None = None,
                 monster_behavior: Mapping[int, dict] | None = None,
                 monster_actions: Mapping[int, str] | None = None,
                 action_rates: Mapping[int, list] | None = None,
                 items: Mapping[int, str] | None = None,
                 art_dir=None, art_raw_dir=None, art_rom_dir=None,
                 map_meta=None, view_radius: int = 7,
                 overworld_size=None, map_zoom=None,
                 charset=None, name_length: int = 4, name_overrides=None,
                 navigation=None, location_resolver=None,
                 floor_estimator=None, tactics=None,
                 live_metatiles=None, map_render=None,
                 ) -> None:
        self.recorder = recorder
        # ★★ 地図の描き方の設定（2026-08-12 / 監査 P0-A）★★
        #   ⚠⚠ `config.yaml` の `map.rom_master` は、**書いても効いて
        #     いませんでした**（読む口はあったが誰も呼んでいなかった）。
        #   ⚠ 渡らなければ既定（＝いまの挙動 = ROM の地図）で動きます。
        self.map_render = map_render
        self.db = db
        self.rom_hash = rom_hash
        # ★見たマスの絵を ROM から用意する係（2026-08-02 / 課題 #65）。
        #   ⚠ 無くても動く。無ければこれまでどおり「色とタイルID」だけ。
        self.live_metatiles = live_metatiles
        self.monsters = dict(monsters or {})
        # ROM 由来の静的データ（memory_map の monster_stats）
        self.monster_stats = dict(monster_stats or {})
        # --- 図鑑で使う ROM 由来データ（2026-07-27）------------------------
        # ★どれも「無くても動く」ようにする。memory_map が古い環境で
        #   画面が落ちるより、その欄が空になるほうがよい。
        self.monster_behavior = dict(monster_behavior or {})
        self.monster_actions = dict(monster_actions or {})
        self.action_rates = dict(action_rates or {})
        self.items = dict(items or {})
        # モンスターの絵の置き場。**無ければ「未撮影」と出す**（実機で撮る）
        self.art_dir = art_dir
        # ★撮ったままの画面。ここから切り出して art_dir に置く
        self.art_raw_dir = art_raw_dir
        # ★ROM から展開した絵（2026-07-29 / `dq2rom monsters install`）。
        #   82体そろっていて実機の撮影と画素まで一致しているので**こちらを先に見る**。
        self.art_rom_dir = art_rom_dir
        # ★マップの大きさ等（`dq2rom maps export` の maps.json）。
        #   ★**地形は入っていない**。⚠ 2026-08-12 訂正: 理由を「日本版では**未解読**」と
        #   書いていましたが、地形は 2026-08-02〜03 に解読済みです
        #   （非ワールド 108/108・世界地図 65536/65536）。`maps.json` に無いのは
        #   ★`dq2rom maps export` が大きさ等しか出していないからで、無くても動く。
        self.map_meta = dict(map_meta or {})
        # ★地図に記録する「画面に映る範囲」の半径（マス）。
        #   画面 256×240 ÷ 1マス16px = 16×15 マスなので、その半分。
        #   ⚠ 実機で測った値ではない。ずれていたら設定で直せる
        #     （`config.yaml` の `map.view_radius`）。
        self.view_radius = max(0, int(view_radius))
        # ★ワールドマップの大きさ（ROM のヘッダ表では $FF,$FF で読めない）。
        #   実測で 256×256（`config.yaml` の `map.overworld_*`）。
        self.overworld_size = tuple(overworld_size) if overworld_size else None
        # ★地図の拡大倍率 (通常, ワールドマップ)。**整数倍だけ**。
        #   0 は「枠に収まる最大の整数倍」（`config.yaml` の `map.zoom`）。
        self.map_zoom = tuple(map_zoom) if map_zoom else None
        # --- ゲーム内で付けたキャラ名（2026-07-29）---------------------------
        # ★文字コード表は `memory_map.yaml` の `text:`。コードに複製しない。
        from ..core.text import Charset

        self.charset = charset if charset is not None else Charset(None)
        self.name_length = int(name_length)
        # ★利用者が明示した名前が最優先（`user_config.yaml` の `names`）
        self.name_overrides = dict(name_overrides or {})
        # --- 移動知識ログ（2026-07-30）---------------------------------------
        # ★★ **判定は Observer の中。** ViewModel は状態を渡すだけ、
        #   View は表示だけ（指示書 10章の責務分離）。
        # ⚠ 閲覧専用のときは作らない（別プロセスと二重に書かない）。
        self.navigation = None if read_only else navigation
        # --- 地名（2026-07-30 / マッパー仕様 4章）-----------------------------
        # ★★ **名前は表示だけに使う。** ★★ 自動移動が使うのは map_id と階層
        #   （どちらも ROM 由来）なので、名前が間違っていても経路は壊れない。
        # ⚠ 無ければ地名が出ないだけ（`where_am_i` が従来の表示に落ちる）。
        self.location_resolver = location_resolver
        # ★階層は**自動移動が使う**情報（名前とは違う）。
        #   人の指定 > ROM 由来 > 上下移動からの推定 の順で決める。
        #   ⚠ 食い違ったら黙って片方に丸めず、画面に出す。
        self.floor_estimator = floor_estimator
        # --- キャラクター別戦術プロフィール（2026-07-30 / 仕様書 17.2）--------
        # ★★ **利用者が設計した戦術。** ★★ AI はこれをそのまま実行する。
        # ⚠ 判断そのものは Lua（`bridge.lua`）。ここは設定を作って渡すだけ。
        self.tactics = tactics
        self.log_limit = log_limit
        # ★閲覧専用（指示書 6.3）。**イベントを取り込まない**。
        #   別の record プロセスが取り込んでいる最中に GUI も取り込むと、
        #   すべての戦闘が二重に記録される（single_instance.py の説明を参照）。
        #   DB を読んで表示することだけは安全なので、それは続ける。
        self.read_only = read_only
        # ★ユーザー指定戦略（custom_1）が有効か（2026-08-11 / Phase 4）。
        #   ⚠ 目的から導けないので覚えておく。None なら通常のAI／手動。
        self._active_strategy = None
        # ★状態は取り込みと関係なく読む。**閲覧専用でも画面は動く**
        #   （記録しないだけで、いま何が起きているかは見せたい）。
        self.state_reader = StateReader(state_path) if state_path else None

        # ★★ エミュレータへの指示は `CommandService` を通す（指示書 §5.2）★★
        #   ⚠ ここで `write_command` を直に呼ばない。呼ぶと
        #     JSON のキー名と `request_id` の規則が画面の層へ漏れる。
        from ..application.command_service import CommandService
        self.commands = CommandService(
            command_path=recorder.command_path,
            encountered=lambda: recorder.stats.current_monsters or [],
            read_only=read_only)

    def _apply_party_names(self, game) -> None:
        """役割名（lorasia 等）を**ゲーム内で付けた名前**に差し替える。

        ★★ 依頼者の指摘（2026-07-29）: 「自キャラ名が日本語名にできてない」★★

        RAM の `$0113` から読んだ生バイトを、`memory_map.yaml` の文字コード表で
        文字にする。表は 2026-07-29 に CHR-RAM の字形から起こした
        （`docs/how-to-read-rom.md` 5章）。

        ⚠ 優先順:
          1. `user_config.yaml` の `names`（利用者が明示した名前）
          2. RAM から読んだ名前
          3. 役割名（読めないとき）

        ⚠ 読めない文字が混ざった名前は**使わない**。半端に化けた名前を出すより、
          役割名のままのほうがまし（`Charset.decode_names` が空文字を返す）。
        """
        if not self.charset.usable or not game.party:
            return
        raw_hex = game.party_name_bytes
        if not raw_hex:
            return
        try:
            raw = bytes.fromhex(raw_hex)
        except ValueError:
            return
        names = self.charset.decode_names(raw, self.name_length, len(game.party))
        for member, name in zip(game.party, names):
            override = self.name_overrides.get(member.name)
            if override:
                member.name = override
            elif name:
                member.name = name

    def monster_book(self, stats: dict | None = None) -> list:
        """モンスター図鑑の行（MVP2 Phase 4）。

        ★**呼ばれたときだけ**作る。全戦闘を走査するので、
          0.5秒ごとの更新で回すと重い（指示書の禁止事項）。
          画面側はタブを開いたときと、戦闘が終わったときだけ引く。
        """
        from ..core.db.monsters import build

        return build(self.db, self.rom_hash, self.monsters,
                     stats if stats is not None else self.monster_stats,
                     behavior=self.monster_behavior)

    def trim_new_art(self) -> list:
        """撮ったままの画面から敵の絵を切り出す（新しいものだけ）。

        ★Lua は**画面全体**を `raw` に保存する。切り出しはここでやる:
          ・Lua に画像処理を書かない（Qt の力を使う）
          ・**raw を残せる**ので、切り出しの規則を直しても撮り直さずに済む

        ⚠ 失敗しても本体は止めない（図鑑に「未撮影」と出るだけ）。
          表示用の処理で本体を止めない（playbook の原則10）。
        """
        if self.art_dir is None or self.art_raw_dir is None:
            return []
        try:
            from ..core.art.trim import trim_new

            return trim_new(self.art_raw_dir, self.art_dir)
        except Exception:
            return []

    # 絵の出どころ。**画面に出す順**でもある（前が優先）
    ART_SOURCE_ROM = "rom"
    ART_SOURCE_CAPTURE = "capture"

    def monster_art(self, monster_id: int) -> tuple:
        """その敵の絵と、その出どころ。無ければ `(None, None)`。

        ★★ 探す順（2026-07-29）★★

          1. **ROM から展開した絵**（`dq2rom monsters install`）
             … 82体そろっていて、実機の撮影10枚と**画素まで一致**している
          2. 実機で撮った絵（`work/monster-art/`）
             … ROM 展開を入れていない環境のための受け皿

        ⚠ 1 と 2 を**同じフォルダに混ぜない**。混ぜると
          「いま出ているのはどちらか」が分からなくなり、
          `dq2rom monsters validate` の材料も壊れる。

        ★どちらから来たかを返すのは、**画面にそう書くため**。
          出どころの分からない絵を見せない。
        """
        import pathlib

        for source, base in ((self.ART_SOURCE_ROM, self.art_rom_dir),
                             (self.ART_SOURCE_CAPTURE, self.art_dir)):
            if base is None:
                continue
            path = pathlib.Path(base) / f"{monster_id:02X}.png"
            if path.exists():
                return path, source
        return None, None

    def monster_art_path(self, monster_id: int):
        """その敵の絵のファイル。**無ければ None**（画面は「未撮影」と出す）。"""
        return self.monster_art(monster_id)[0]

    # --- 歩いた地図（2026-07-29）--------------------------------------

    def map_size(self, map_id: int) -> tuple:
        """そのマップの大きさ `(幅, 高さ)`。分からなければ `(None, None)`。

        ★★ **ここが大きさの唯一の出口** ★★
          記録（`note_position`）と描画（地図の窓）が別々に判断すると、
          ワールドマップだけ食い違って**座標がずれた地図**になる。

        ⚠ ワールドマップは ROM のヘッダ表で `$FF,$FF` になっていて読めない。
          そこだけ設定から補う（実測 256×256 / `config.yaml` の `map.overworld_*`）。
        """
        meta = self.map_meta.get(map_id) or {}
        if meta.get("type") == "overworld" and self.overworld_size:
            return self.overworld_size
        return meta.get("width"), meta.get("height")

    def map_type(self, map_id: int) -> str | None:
        meta = self.map_meta.get(map_id) or {}
        return meta.get("type")

    def map_matches_pointer(self, map_id: int, map_ptr: int) -> bool:
        """`map_id` と、いま読み込んでいるマップのデータ位置が矛盾しないか。

        ★★ 実データで見つかった不具合（2026-07-30）★★
          記録の中に **`map_id`=01（ワールドマップ）なのに町のポインタ**という
          組が3つあり、それぞれ **ちょうど 225 マス（15×15 = 記録1回ぶん）**
          だった。つまり**マップの切り替わりの瞬間に1回だけ**、
          `$31` と `$23-$24` が食い違ったまま記録されていた。
          結果、地図の一覧に**幽霊のような項目**が並んでいた（依頼者の画面で確認）。

        → ROM のヘッダ表が「そのマップのデータはここ」と言っている値と
          突き合わせて、違えば記録しない。

        ⚠ 表に無いマップは判断できないので **True（通す）**。
          分からないことを理由に、正しい記録まで捨てない。
        """
        meta = self.map_meta.get(map_id) or {}
        want = meta.get("data_pointer")
        if not want:
            return True
        try:
            return int(str(want), 16) == map_ptr
        except (TypeError, ValueError):
            return True

    def note_position(self, state) -> int:
        """いまの周りを「見た」として記録する。**新しく記録したマス数**を返す。

        ★★ 記録するのは「立ったマス」ではなく「**画面に映る範囲**」 ★★
          依頼者の指摘（2026-07-29）:

          > マップは、歩いた所じゃなくて、画面に映った所は表示するほうがいいね
          > 定義は、そんなに難しく考えなくて良くて、真ん中からｘキャラ分とかで良いよ

          → **主人公を中心とした ±`view_radius` マスの四角**を記録する。
            画面（256×240）÷ 1マス16px ＝ 16×15 マスなので、既定は半分の 7。

        ⚠ 暗いダンジョンでは、実際には見えていない所まで入る。
          気になるなら `map.view_radius` を小さくすれば減る（設定で変えられる）。

        ★★ 記録するのは**戦闘していないとき**だけ ★★
          Lua は戦闘中に座標を書かない。ここでも二重に守る。

        ⚠ 閲覧専用のときは書かない（取り込みプロセスと二重書きしない）。
        """
        if self.read_only or state is None or state.in_battle:
            return 0
        if state.map_id is None or state.map_x is None or state.map_y is None:
            return 0
        ptr = state.map_data_pointer
        # ★★ マップのデータ位置は必ず切り替えバンクの窓 `$8000-$BFFF` にある。
        #   外なら「まだマップを読み込んでいない」（タイトル画面など）。
        #   ⚠ 実データに `map_ptr = 0` の記録が 64 マスあった（2026-07-30）。
        if ptr is None or not (0x8000 <= ptr <= 0xBFFF):
            return 0

        # ★半径は Lua が色を拾った範囲に合わせる。食い違うと色がずれる
        radius = (state.map_view_radius
                  if state.map_view_radius is not None else self.view_radius)
        # ★★ 切り替わりの瞬間の食い違いを弾く（2026-07-30）★★
        #   `map_id` と `$23-$24` が矛盾する組が実データに3つ（各225マス）あった。
        if not self.map_matches_pointer(state.map_id, ptr):
            return 0

        colors = self._color_grid(state.map_colors, radius)
        # ★タイルID（1マス2文字）。★色よりこちらを優先して記録する
        tiles = self._packed_grid(state.map_tiles, radius, width=2)
        # ★★ 16×16 の絵（2026-08-02 / 課題 #65）★★
        #   ⚠ `map_cells` は Lua が**止まっているときだけ**出す
        #     （スクロールが 16 の倍数のとき）。動いている最中の絵は来ない。
        #   ★絵そのものは ROM から作るので、採取したセーブステートの
        #     周りに限られない。⚠ 描くのは**見たマス**だけ（指示書 §2.2）。
        metatiles = {}
        if self.live_metatiles is not None and state.map_cells:
            try:
                metatiles = self.live_metatiles.keys_for_view(
                    state.map_id, state.map_cells, radius)
            except Exception:            # noqa: BLE001
                # ⚠ 絵が作れなくても地図の記録は続ける（欠けるだけ）
                metatiles = {}
        # ★大きさは `map_size` に一本化する（ワールドマップは設定から補う）
        width, height = self.map_size(state.map_id)
        added = 0
        try:
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    x, y = state.map_x + dx, state.map_y + dy
                    # ★マップの外は記録しない。大きさを知っているときだけ切る
                    # ★★ **ROM の大きさで切らない**（2026-08-02）★★
                    #
                    #   ⚠⚠ 依頼者「save3では表示されない（印）」。
                    #     ここで切っていたのが元でした。
                    #   ★実測（遷移の記録は切っていないので信用できる）:
                    #       map $3D  ROM 15×17  ->  実際 29/33
                    #       map $3E  ROM 17×19  ->  実際 32/37
                    #     **ROM の値のほうが小さい**のです。
                    #     ⚠ 正しい読み方は未解明（おおむね2倍だが $39 で
                    #       合わない）。★分からないので切りません。
                    #
                    #   ⚠ 一度これで「DB の記録は全部枠に収まっている」と
                    #     測ってしまいました。**切った後を見ていた**ので
                    #     当たり前でした（測り方が循環していた）。
                    #
                    #   ★座標は 1 バイトなので、そこだけは守る。
                    if x < 0 or y < 0 or x > 255 or y > 255:
                        continue
                    color = colors.get((dx, dy)) if colors else None
                    tile = tiles.get((dx, dy)) if tiles else None
                    if self.db.mark_visited(self.rom_hash, state.map_id,
                                            ptr, x, y, color, tile):
                        added += 1
                    # ★16×16 の絵は、マスを記録した**後**に結びつける
                    #   （`record_metatile` は既にある行を見にいくため）。
                    key = metatiles.get((dx, dy))
                    if key:
                        self.db.record_metatile(
                            self.rom_hash, state.map_id, ptr, x, y, key)
        except Exception:
            # ⚠ 記録に失敗しても本体は止めない（地図が欠けるだけ）
            return added
        return added

    @staticmethod
    def _packed_grid(packed: str | None, radius: int, width: int) -> dict:
        """1マス `width` 文字で並んだものを `{(dx, dy): 値}` にする。

        ★色（3文字）とタイルID（2文字）で同じ形なので、1つにまとめた。
        ⚠ 長さが合わなければ**何も使わない**（ずれた値を地図に塗らない）。
        ⚠ 「読めなかった」印（`_`）は None にする（0 と 不明を混ぜない）。
        """
        if not packed:
            return {}
        side = radius * 2 + 1
        if len(packed) != side * side * width:
            return {}
        out = {}
        i = 0
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                chunk = packed[i:i + width]
                i += width
                if "_" not in chunk:
                    out[(dx, dy)] = chunk
        return out

    @staticmethod
    def _color_grid(packed: str | None, radius: int) -> dict:
        """Lua が並べた色（1マス3文字）を `{(dx, dy): "RGB"}` にする。

        ⚠ 長さが合わなければ**何も使わない**。ずれた色を地図に塗ると、
          陸と海が入れ替わった嘘の地図になる（**分からないほうがまし**）。
        """
        if not packed:
            return {}
        side = radius * 2 + 1
        if len(packed) != side * side * 3:
            return {}
        out = {}
        i = 0
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                chunk = packed[i:i + 3]
                i += 3
                if chunk != "___":
                    out[(dx, dy)] = chunk
        return out

    def visited_maps(self) -> list:
        try:
            return self.db.visited_maps(self.rom_hash)
        except Exception:
            return []

    def visited_tiles(self, map_id: int, map_ptr: int) -> list:
        try:
            return self.db.visited_tiles(self.rom_hash, map_id, map_ptr)
        except Exception:
            return []

    def visited_tile_ids(self, map_id: int, map_ptr: int) -> dict:
        """`{(x, y): タイルID}`（2026-08-01 / 課題 #65）。

        ★絵で描くのに要る。⚠ 古い記録には無いので空になることがある。
        """
        try:
            return self.db.visited_tile_ids(self.rom_hash, map_id, map_ptr)
        except Exception:
            return {}

    def visited_metatiles(self, map_id: int, map_ptr: int) -> list:
        """`[(x, y, メタタイル鍵, 回数, 確度)]`（2026-08-02 / マップ指示書）。

        ★背景キャラクタで描くのに要る。
        ⚠ 古い記録には無いので**空になることがある**。そのときは
          描画側が現行表示へ落ちる（勝手に黒で埋めない）。
        """
        try:
            return self.db.visited_metatiles(self.rom_hash, map_id, map_ptr)
        except Exception:
            return []

    def map_label(self, map_id, map_ptr=0) -> str:
        """一覧に出す1マップぶんの見出し。**辞書が無ければ ID だけ**。

        例: `ローレシア B1 [$04]` / `マップ 7F`

        ★人が名前を指定していれば**それを使う**（辞書より強い）。
          日本語名の大半は ROM から取っていないので、直せるようにしている。
        """
        override = self.map_override(map_id, map_ptr) or {}
        name = (override.get("display_name") or "").strip()
        floor = self.floor_of_map(map_id, map_ptr)
        if name:
            tail = f" {floor.label}" if floor is not None and floor.known else ""
            return f"{name}{tail} [${map_id:02X}]"
        resolved = self.location_of_map(map_id)
        if resolved is None or not resolved.registered:
            return f"マップ {map_id:02X}"
        return f"{resolved.display} [${map_id:02X}]"

    def location_of_map(self, map_id):
        """`map_id` だけで引いたロケーション。⚠ 地域名は付かない（座標が無い）。"""
        if self.location_resolver is None:
            return None
        return self.location_resolver.resolve_map(map_id)

    def floor_of_map(self, map_id, map_ptr=0):
        """そのマップの階層（`FloorEstimate`）。**分からなければ None**。"""
        if self.floor_estimator is None:
            return None
        return self.floor_estimator.estimate(map_id, map_ptr)

    def map_override(self, map_id, map_ptr=0):
        """人がそのマップについて決めたこと（名前・階層）。無ければ None。"""
        repo = self._repo()
        if repo is None:
            return None
        try:
            return repo.map_override(int(map_id), int(map_ptr))
        except Exception:                              # noqa: BLE001
            return None

    def set_map_override(self, map_id, map_ptr, *, floor_index=None,
                         display_name=None) -> bool:
        """人が名前と階層を決める。★**最優先**として保存する。

        ⚠ `None` は「指定しない」。前の値を残すのではなく**消す**
          （窓で空にしたのに前の値が残ると、消せないことになる）。
        """
        repo = self._repo()
        if repo is None:
            return False
        try:
            from ..core.navigation.floor_estimator import label_for

            # ★`note`（なぜそう決めたか）は窓で編集しないので**持ち越す**。
            #   持ち越さないと、名前を直すたびに理由が消える。
            previous = repo.map_override(int(map_id), int(map_ptr)) or {}
            repo.set_map_override(
                int(map_id), int(map_ptr),
                floor_index=floor_index, floor_label=label_for(floor_index),
                display_name=display_name, note=previous.get("note"),
                keep_missing=False)
            return True
        except Exception:                              # noqa: BLE001
            return False

    def clear_map_override(self, map_id, map_ptr=0) -> bool:
        repo = self._repo()
        if repo is None:
            return False
        try:
            repo.clear_map_override(int(map_id), int(map_ptr))
            return True
        except Exception:                              # noqa: BLE001
            return False

    def set_map_floor(self, map_id, map_ptr, floor_index, note=None) -> bool:
        """人が階層を決める。★**最優先**として保存する。

        戻り値は保存できたか。

        ⚠ 閲覧専用のときは書かない。★守っているのは `__init__` の
          `self.navigation = None if read_only else navigation`
          （**観測役ごと切る**ので、ここで `read_only` を見る必要はない。
          見ても必ず通らない枝になり、試せないコードが増えるだけ）。

        ★下の `if` は読みやすさのための早期 return。
          実際に守っているのは try/except（外しても同じ結果になる）。
        """
        if self.navigation is None:
            return False
        try:
            from ..core.navigation.floor_estimator import label_for

            self.navigation.repo.set_floor_override(
                int(map_id), int(map_ptr),
                None if floor_index is None else int(floor_index),
                label_for(floor_index), note)
            return True
        except Exception:                              # noqa: BLE001
            # ⚠ 保存できなくても画面は止めない
            return False

    # --- 人が入れるもの（フェーズ6）------------------------------------
    #
    # ★★ **これは人の言葉。観測が上書きしない。** ★★
    #   メモ（自由文）は人が読むためのもの、目印（種類つき）は
    #   あとで「宝箱まで自動で行く」に使えるもの。
    #
    # ⚠ 閲覧専用のときは書かない（`self.navigation` が None になる）。

    def _repo(self):
        return getattr(self.navigation, "repo", None)

    def set_note(self, place, body) -> bool:
        """メモを置く／書き直す／（空文字なら）消す。戻り値は**書けたか**。"""
        repo = self._repo()
        if repo is None or place is None:
            return False
        try:
            repo.set_note(place, body)
            return True
        except Exception:                              # noqa: BLE001
            return False

    def note(self, place):
        repo = self._repo()
        if repo is None or place is None:
            return None
        try:
            return repo.note(place)
        except Exception:                              # noqa: BLE001
            return None

    def notes(self, map_id, map_ptr) -> list:
        repo = self._repo()
        if repo is None:
            return []
        try:
            return repo.notes(int(map_id), int(map_ptr))
        except Exception:                              # noqa: BLE001
            return []

    def set_landmark(self, place, kind, label=None) -> bool:
        """目印を置く。⚠ 種類が読めなければ**置かない**（False）。"""
        repo = self._repo()
        if repo is None or place is None:
            return False
        try:
            return bool(repo.set_landmark(place, kind, label))
        except Exception:                              # noqa: BLE001
            return False

    def delete_landmark(self, place, kind) -> bool:
        repo = self._repo()
        if repo is None or place is None:
            return False
        try:
            return bool(repo.delete_landmark(place, kind))
        except Exception:                              # noqa: BLE001
            return False

    def landmarks(self, map_id, map_ptr, kind=None) -> list:
        repo = self._repo()
        if repo is None:
            return []
        try:
            return repo.landmarks(int(map_id), int(map_ptr), kind)
        except Exception:                              # noqa: BLE001
            return []

    # --- 戦術プロフィール（2026-07-30）----------------------------------

    def active_tactics(self):
        """いま使っている戦術プロフィール。無ければ None。"""
        if self.tactics is None:
            return None
        try:
            return self.tactics.active()
        except Exception:                              # noqa: BLE001
            return None

    def push_tactics(self) -> bool:
        """選んでいる戦術を Lua へ渡す。戻り値は**渡せたか**。

        ★2段でやる:
          1. `work/generated/tactics.lua` を書く（Lua が読む表）
          2. `command.json` に版を入れる（Lua が「変わった」と気づく）

        ⚠ 反映は**次の戦闘から**（Lua 側で戦闘の始まりに固定する / 仕様書 15.3）。
          ここで即座に効かせると、戦闘の途中で戦術が入れ替わる。

        ⚠ 閲覧専用のときは渡さない（別プロセスと取り合う）。
        """
        if self.read_only or self.tactics is None:
            return False
        prof = self.active_tactics()
        if prof is None:
            return False
        try:
            from ..core.tactics import lua_bridge

            rev = lua_bridge.write(prof, mission=self.mission(),
                                   strategy=self._active_strategy_lua())
            if rev is None:
                return False
            # ★版そのものが「変わった」の目印なので `request_id` は要らない
            #   （`request_id` は単発の操作要求＝`action` 用）。
            return self.commands.set_tactics_revision(rev) is None
        except Exception:                              # noqa: BLE001
            return False

    # --- ★★ 作戦の切り替え（2026-08-04 / 指示書 §6・§14）------------------
    #
    # ★★ **切り替えの入口はここ1つだけ。** ★★
    #
    #   指示書 §6:
    #   > メイン画面と戦術設定画面が個別に設定ファイルを読み書きする構造には
    #   > しない。作戦状態を一元管理するクラスまたは既存管理クラスを用いる。
    #
    #   ⚠ 新しい `StrategyManager` は作りません（§6 の「既存構造へ統合してよい」）。
    #     `TacticsRepository` が既に `active_id` / `set_active` / `active` を
    #     持っており、**そこが唯一の出典**です。ここはその上に
    #     「検証・重複除け・Luaへの通知・ログ」を1か所でまとめる薄い層です。

    #: 切り替えの結果。★画面は**これを見て**表示を決める（各自で判断しない）
    class TacticsSwitch:
        """`set_active_tactics` の戻り値。

        ⚠ 例外を投げません。**画面が落ちるより、理由を出して続くほうがよい**。
        """

        def __init__(self, ok: bool, changed: bool, profile_id=None,
                     name: str = "", message: str = "",
                     pushed: bool = False) -> None:
            self.ok = ok              # ★切り替えとして成立したか
            self.changed = changed    # ★実際に変わったか（同じなら False）
            self.profile_id = profile_id
            self.name = name
            self.message = message    # ★画面にそのまま出せる文
            self.pushed = pushed      # ★Lua まで届いたか

    def tactics_choices(self) -> list:
        """作戦リストに出す `(id, 表示名)`。★見本も自分のものも同じ並び。"""
        if self.tactics is None:
            return []
        try:
            profiles = self.tactics.list_profiles()
        except Exception:                              # noqa: BLE001
            return []
        out = []
        for prof in profiles:
            mark = "（見本）" if getattr(prof, "preset", False) else ""
            out.append((prof.id, f"{prof.name}{mark}"))
        return out

    def set_active_tactics(self, profile_id, source: str = "unknown",
                           in_battle: bool | None = None):
        """作戦を切り替える。★**画面はここだけを呼ぶ**。

        引数:
          `profile_id` … 選ばれた作戦の id
          `source`     … どこから切り替えたか（`main_window` / `tactics_window`）
                         ★ログに残す。⚠ 「誰が変えたか」が分からないと追えない。
          `in_battle`  … 戦闘中か。★省略すると自分で調べる。
                         指示書 §4.2「戦闘外では『次のターンから』の表示は不要」

        ⚠⚠ **同じ作戦の再選択では何もしません**（§6 必須要件・§15）。
          保存もLuaへの通知もログも出しません。⚠ 画面の初期化で
          リストへ現在値を入れたときに誤発火しても、これが最後の砦になります。
        """
        from ..core.logging_setup import get_logger

        log = get_logger("tactics")
        if self.tactics is None:
            return self.TacticsSwitch(
                False, False, message="⚠ 戦術プロフィール機能が無効です。")

        before = None
        try:
            before = self.tactics.active_id()
        except Exception:                              # noqa: BLE001
            pass

        # ⚠ 不正な作戦IDは**安全な既定作戦へフォールバック**（§6・§15）
        wanted = str(profile_id) if profile_id is not None else None
        found = None
        if wanted:
            try:
                found = self.tactics.get(wanted)
            except Exception:                          # noqa: BLE001
                found = None
        if found is None:
            fallback = self.active_tactics()
            name = getattr(fallback, "name", "バッチリ戦う")
            log.warning("[TACTICS] unknown strategy %r -> fallback %r",
                        wanted, getattr(fallback, "id", "balanced"))
            return self.TacticsSwitch(
                False, False, getattr(fallback, "id", None), name,
                f"⚠ 作戦『{wanted}』が見つかりません。"
                f"『{name}』のまま続けます。")

        # ★★ 同じものを選び直しただけなら、何もしない ★★
        if before == found.id:
            return self.TacticsSwitch(
                True, False, found.id, found.name,
                f"作戦は『{found.name}』のままです。")

        if not self.tactics.set_active(found.id):
            # ⚠ §15「設定保存失敗時も、メモリ上の作戦変更は可能な範囲で維持」
            #   ★保存できなくても Lua へは渡す（今の戦闘には効かせる）。
            log.error("[TACTICS] could not persist strategy %r", found.id)
            pushed = self.push_tactics()
            return self.TacticsSwitch(
                True, True, found.id, found.name,
                f"⚠ 作戦『{found.name}』に変えましたが、"
                "次回起動時には戻ります（選択を保存できませんでした）。",
                pushed)

        pushed = self.push_tactics()

        # ★★ 1イベント1責務（2026-08-13 / 製品版ログ整理 §24）★★
        #
        #   ⚠⚠ **以前は INFO を3行出していました**:
        #
        #       [TACTICS] strategy changed: balanced -> life_first
        #       [TACTICS] source: main_window
        #       [TACTICS] effective_from: next_action_plan
        #
        #   ★これは `input/RetroUX_戦術切替_いのちをだいじに実装指示書.md`
        #     （472-474行）が指定した形でした。⚠ 今回の指示書 §24 が
        #     **この箇所を統合対象の例として名指し**しているため、
        #     意図的に上書きします（`deviations-from-instruction.md` に記録）。
        #
        #   ★人が読む行は1行。⚠ `source` と `effective_from` は
        #     機械が使うものなので、構造化イベント側へ回します。
        log.info("戦術変更: %s → %s", before or "(なし)", found.name)
        # ★詳細は DEBUG（diagnostic のときだけ出ます）
        log.debug("[TACTICS] id=%s source=%s effective_from=next_action_plan",
                  found.id, source)

        if in_battle is None:
            # ⚠ 戦闘中かは `recorder.stats` が持っています。
            #   ★読めなくても切り替えは止めません（表示の文が変わるだけ）。
            in_battle = bool(getattr(
                getattr(self.recorder, "stats", None), "in_battle", False))
        # ⚠ §4.2「戦闘外では『次のターンから』の表示は不要」
        tail = "\n次のターンから適用します" if in_battle else ""
        message = f"作戦を「{found.name}」に変更しました{tail}"
        if not pushed:
            message = (f"作戦を「{found.name}」に変更しました\n"
                       "⚠ エミュレータへは渡せていません"
                       "（閲覧専用か、書けない状態です）")
        return self.TacticsSwitch(True, True, found.id, found.name,
                                  message, pushed)

    # --- ★★ 大目的（2026-08-05 / 戦闘AI再設計 Phase 3）--------------------
    #
    # ★★ **大目的は「価値基準」であって命令ではありません**（指示書 §5）。
    #
    #     誤: レベル上げ -> 常に速攻 -> 常にMP温存しない
    #     正: レベル上げ -> **時間の価値が高く、MP の価値が低い**
    #
    # ⚠ 作戦（戦術プロフィール）とは**別のもの**です。並存させます。
    #   目的  = 何を重んじるか（レベル上げ / ダンジョン / ボス）
    #   作戦  = どう戦うか（バッチリ / いのちをだいじに / 呪文を使わない）

    #: ⚠⚠ **テストから差し替えるための置き場**（2026-08-05）。
    #
    #   ★これが無いと、テストが**利用者の `config/mission.yaml` を
    #     書き換えます**（実際に踏んだ: 既定が「ダンジョン攻略」のはずが
    #     テストの書いた「レベル上げ」で起動するようになった）。
    #   `_tactics_lua_path` と同じ流儀です。
    _mission_path = None
    #: ★最後に読めた状態（Phase 9 の表示用）。⚠ 読めていなければ None。
    _last_game = None

    @property
    def battle_review(self):
        """直前戦闘レビューの記録係（2026-08-12 / 指示 §13）。

        ⚠⚠ **クラス変数にしないこと。** ★`_last_game` と違って中身が
          育つので、クラスに置くと**複数の ViewModel で履歴が混ざります**
          （テスト同士が干渉します）。★インスタンスごとに作ります。
        """
        got = self.__dict__.get("_battle_review")
        if got is None:
            from .battle_review import BattleReviewRecorder

            got = BattleReviewRecorder()
            self.__dict__["_battle_review"] = got
        return got

    def mission(self):
        """いまの大目的。⚠ 読めなければ既定（ダンジョン攻略）。"""
        if getattr(self, "_mission", None) is None:
            from ..core.mission import load

            got, problems = load(self._mission_path)
            self._mission = got
            self._mission_problems = problems
        return self._mission

    def mission_choices(self) -> list:
        """画面に出す `(値, 表示名, 説明)`。"""
        from ..core.mission.settings import MISSION_LABELS, MISSION_NOTES

        return [(m.value, MISSION_LABELS[m], MISSION_NOTES.get(m, ""))
                for m in MISSION_LABELS]

    def set_mission(self, value, source: str = "unknown"):
        """大目的を切り替える。★戻り値は `TacticsSwitch` と同じ形。

        ⚠⚠ **同じ目的の選び直しでは何もしません**（作戦と同じ）。
        ⚠ 保存できなくても、メモリ上の変更と Lua への通知は行います
          （指示書 §15）。
        """
        from ..core.logging_setup import get_logger
        from ..core.mission import MissionSettings, Mission, save

        log = get_logger("tactics")
        want = Mission.parse(value, None)
        if want is None:
            # ⚠ 知らない値で黙って別の目的にしない
            now = self.mission()
            log.warning("[MISSION] unknown mission %r -> keep %r",
                        value, now.mission.value)
            return self.TacticsSwitch(
                False, False, now.mission.value, now.mission.value,
                f"⚠ 知らない目的『{value}』です。今のまま続けます。")

        now = self.mission()
        if now.mission == want:
            return self.TacticsSwitch(True, False, want.value, want.value,
                                      "目的は変わっていません。")

        from ..core.mission.settings import MISSION_LABELS

        made = MissionSettings(mission=want, risk=now.risk)
        self._mission = made
        ok, why = save(made, self._mission_path)
        pushed = self.push_tactics()

        name = MISSION_LABELS[want]
        # ★1イベント1責務（§24）。⚠ 以前は INFO を3行出していた
        log.info("目的変更: %s → %s",
                 MISSION_LABELS.get(now.mission, now.mission.value), name)
        log.debug("[MISSION] id=%s source=%s effective_from=next_action_plan",
                  want.value, source)
        message = f"目的を「{name}」に変更しました"
        if not made.auto_enabled:
            # ★★ ボス目的は AUTO を既定 OFF（Phase 3 完了条件）
            message += "\n★AUTO は既定で OFF です（自分で戦うため）"
        if not ok:
            message += f"\n⚠ 次回起動時には戻ります（{why}）"
        elif not pushed:
            message += "\n⚠ エミュレータへは渡せていません"
        return self.TacticsSwitch(True, True, want.value, name, message,
                                  pushed)

    def mission_label(self) -> str:
        """メイン画面に出す1行。"""
        from ..core.mission.settings import label

        return label(self.mission())

    # --- ★★ 戦略（2026-08-10 / UI整理 Phase 3）----------------------------
    #
    #   > 利用者が通常操作するものは、原則として戦略だけとする（指示書§2）。
    #
    #   ★2軸（目的×作戦）を1つの戦略に畳む。ここは既存の `set_mission` と
    #     `set_active_tactics` を**束ねるだけ**（薄い被せもの / §15）。
    #
    # ⚠ 下の2つの表は DQ2 の作戦IDと Mission値を指す（暫定）。
    #   ★将来はプラグインの設定へ（§13）。いまはここに置いて動かす。
    _STRATEGY_TACTICS = {          # 戦略 → 束ねる作戦プロファイルID
        "leveling": "balanced",    # レベル上げ（作戦名も「レベル上げ」）
        "dungeon": "life_first",   # ダンジョン探索（作戦名も「ダンジョン探索」）
        # ⚠ 2026-08-11: 手動戦略は廃止（AUTO ボタン OFF）。manual 見本も廃止。
    }
    _STRATEGY_MISSION = {          # AUTO 戦略 → 束ねる Mission
        "leveling": "grinding",
        "dungeon": "dungeon",
    }

    def strategy_choices(self) -> list:
        """戦略の `(値, 表示名, 説明)`（指示書§2・§7）。

        ★★ 2026-08-11: **3戦略だけ**（レベル上げ／ダンジョン探索／亀の子）。
          手動は画面から外した（AUTO ボタン OFF が手動）。⚠ enum の MANUAL は
          旧設定の移行のため残すが、★ここには出さない。
        """
        from ..core.strategy.models import (STRATEGY_LABELS, STRATEGY_NOTES,
                                            Strategy)

        shown = (Strategy.LEVELING, Strategy.DUNGEON, Strategy.CUSTOM_1)
        return [(s.value, STRATEGY_LABELS[s], STRATEGY_NOTES.get(s, ""))
                for s in shown]

    def current_strategy(self, auto_on: bool) -> str:
        """いまの状態から戦略を導く（★保存はせず、状態を見る）。

        ★★ 2026-08-11: 手動戦略は無くした。★戦略は「AI が何をするか」を表し、
          AUTO の入切（AI を動かすか）は別軸（AUTO ボタン）。だから AUTO が
          OFF でも、選んでいる戦略（レベル上げ／ダンジョン探索／亀の子）を返す。
        ⚠ 亀の子（custom_1）だけは目的から導けないので**覚えて**おく。
        """
        if getattr(self, "_active_strategy", None) == "custom_1":
            return "custom_1"
        return ("leveling" if self.mission().mission.value == "grinding"
                else "dungeon")

    def _active_strategy_lua(self):
        """実行中の Lua へ渡す戦略の目印。⚠ 固定戦略のときだけ返す。

        ★中身（誰が何を）は config.lua の `user_strategies` にある。ここは
          「どれが有効か」だけ（薄い被せもの / Phase 4）。
        """
        if getattr(self, "_active_strategy", None) == "custom_1":
            return {"id": "custom_1", "type": "fixed"}
        return None

    def set_strategy(self, value, source: str = "unknown"):
        """戦略を適用する。★`set_mission` ＋ `set_active_tactics` を束ねる。

        戻り値は `TacticsSwitch`。⚠ `auto_enabled` 属性を足して返す
        （画面が AUTO の入切に使う）。
        """
        from ..core.strategy.models import (STRATEGY_LABELS, STRATEGY_TYPES,
                                            Strategy, StrategyType)
        from ..core.logging_setup import get_logger

        strat = Strategy.parse(value)
        if strat is None:
            sw = self.TacticsSwitch(False, False, value, value,
                                    "⚠ その戦略は選べません")
            sw.auto_enabled = True
            return sw

        # ★★ ユーザー指定（固定行動 / 2026-08-11 / Phase 4）★★
        #   ⚠ 目的・作戦は変えない。★「固定戦略が有効」を覚えて Lua へ渡す
        #     （固定行動の中身は config.lua の user_strategies）。
        if strat is Strategy.CUSTOM_1:
            self._active_strategy = "custom_1"
            self.push_tactics()          # ★strategy 目印を Lua へ
            get_logger("tactics").debug("[STRATEGY] strategy: custom_1 (fixed)"
                                       " (source=%s)", source)
            sw = self.TacticsSwitch(
                True, True, "custom_1", STRATEGY_LABELS[strat],
                f"戦略を「{STRATEGY_LABELS[strat]}」にしました")
            sw.auto_enabled = True       # ★AIループは回す（固定行動が横取り）
            return sw

        # ★AUTO / 手動 は固定戦略を解除
        self._active_strategy = None

        # ★作戦（戦術プロファイル）を束ねる
        tid = self._STRATEGY_TACTICS.get(strat.value)
        if tid is not None:
            self.set_active_tactics(tid, source=source)
        # ★目的（Mission）を束ねる（AUTO 戦略のみ）
        mid = self._STRATEGY_MISSION.get(strat.value)
        if mid is not None:
            self.set_mission(mid, source=source)

        get_logger("tactics").debug("[STRATEGY] strategy: %s (source=%s)",
                                   strat.value, source)

        auto = STRATEGY_TYPES[strat] is not StrategyType.MANUAL
        sw = self.TacticsSwitch(True, True, strat.value,
                                STRATEGY_LABELS[strat],
                                f"戦略を「{STRATEGY_LABELS[strat]}」にしました")
        sw.auto_enabled = auto
        return sw

    #: ★戦況の日本語。⚠ `unknown` を消さない（**材料が無い**と伝える）。
    _BALANCE_LABELS = {
        "advantage": "優勢", "even": "均衡", "disadvantage": "劣勢",
        "unknown": "⚠ 分からない",
    }
    _LENGTH_LABELS = {"short": "短期戦", "medium": "中期戦", "long": "長期戦"}

    def assessment_label(self) -> str:
        """戦況と戦術を1行で（2026-08-07 / Phase 9）。

        ⚠⚠ **「届いていない」と「0」を分ける。**
          ★`—` は材料が無いこと。数字は測った結果です。
          両方を 0 で出すと、⚠ **測れていないことに永久に気づけません**。

        ★次点との差も出します。⚠ 小さいなら**次のターンに変わりうる**
          ということで、「この判断がどれくらい確からしいか」が分かります。
        """
        game = self._last_game
        if game is None or getattr(game, "battle_balance", None) is None:
            return "戦況: —（戦闘中に出ます）"

        parts = []
        balance = game.battle_balance
        parts.append("戦況: " + self._BALANCE_LABELS.get(balance, balance))

        length = getattr(game, "battle_length", None)
        if length:
            parts[-1] += "・" + self._LENGTH_LABELS.get(length, length)

        win = getattr(game, "battle_turns_to_win", None)
        lose = getattr(game, "battle_turns_to_lose", None)
        # ⚠ 片方しか出せないこともある。★出せるものだけ出す。
        if win is not None or lose is not None:
            parts.append("敵撃破 {}／味方崩壊 {}".format(
                f"{win:.1f}ターン" if win is not None else "—",
                f"{lose:.1f}ターン" if lose is not None else "—"))

        plan = getattr(game, "battle_plan", None)
        if plan is None:
            # ★★ 戦況は取れたのに戦術が決まらない = **材料不足**。
            #   ⚠ 空欄にせず、そう書きます。
            parts.append("戦術: ⚠ 決めていません")
        else:
            score = getattr(game, "battle_plan_score", None)
            margin = getattr(game, "battle_plan_margin", None)
            text = f"戦術: {plan}"
            if score is not None:
                text += f"（適合度 {score:.1f}"
                if margin is not None:
                    # ⚠ 僅差は「次のターンに変わりうる」の合図
                    warn = " ⚠僅差" if margin < 0.5 else ""
                    text += f" / 次点との差 {margin:.1f}{warn}"
                text += "）"
            parts.append(text)

        tags = getattr(game, "battle_tags", None)
        if tags:
            parts.append(tags)
        return "　".join(parts)

    # --- ★★ 戦況欄の4行と、戦闘レビュー（2026-08-12 / 依頼者の指示）------
    #
    #   ★画面 = 結果（4行） / ツールチップ = 根拠（全ターン）
    #   ⚠ `assessment_label()` / `roles_label()` は**残します**。ログや
    #     他の表示が使っており、こちらの都合で消すと巻き添えになります
    #     （指示 §17: 4行表示用に別 Formatter を作るほうが安全）。

    def assessment_rows(self) -> list[str]:
        """戦況欄に出す**4行**（指示 §4）。

        ★★ 戦闘が終わっても「—」へ戻しません（指示 §9）★★
          AUTO は一瞬で終わるので、読む前に消えます。
          ⚠ 次の戦闘が始まるまで、直前の戦闘の要約を残します。
        """
        from . import battle_format as bf

        game = self._last_game
        if game is not None and getattr(game, "battle_balance", None) is not None:
            return bf.format_summary_rows(
                balance=game.battle_balance,
                length=getattr(game, "battle_length", None),
                win=getattr(game, "battle_turns_to_win", None),
                lose=getattr(game, "battle_turns_to_lose", None),
                plan=getattr(game, "battle_plan", None),
                score=getattr(game, "battle_plan_score", None),
                margin=getattr(game, "battle_plan_margin", None),
                roles=getattr(game, "battle_roles", None),
                tags=getattr(game, "battle_tags", None))
        # ★戦闘中でない → 直前の戦闘（無ければ「戦闘中に出ます」）
        self._fill_battle_result()
        return bf.format_previous_rows(self.battle_review.previous)

    def battle_review_tooltip(self) -> str:
        """戦況欄のツールチップ＝全ターンのレビュー（指示 §7・§18）。"""
        from . import battle_format as bf

        rec = self.battle_review
        in_battle = rec.current is not None
        if not in_battle:
            self._fill_battle_result()
        # ★先頭に4行を入れる理由は `format_battle_review_tooltip` の説明を参照
        #   （⚠ 狭い窓で切れた行の全文をここで読めるようにするため）。
        return bf.format_battle_review_tooltip(
            rec.active(), in_battle, summary_rows=self.assessment_rows())

    def battle_review_revision(self) -> tuple:
        """★履歴が変わったかの鍵。⚠ 変わっていなければ作り直しません。"""
        return self.battle_review.revision()

    def _fill_battle_result(self) -> None:
        """直前戦闘の勝敗を DB から**分かるときだけ**入れる（指示 §10）。

        ⚠⚠ **ここは当てに行っています。** `state.json` に勝敗は来ないので、
          DB の `BattleLog` のいちばん新しい行を見ています。取り込みは
          遅れることがあり、★**別の戦闘の結果を拾う可能性があります**。
          だから「戦闘が終わってから記録が1件増えたとき」だけ入れます。

        ⚠ 分からなければ **None のまま**にします（推測で「勝利」と書かない）。

        ⚠⚠ **毎回 DB を叩かないこと**（指示 §20）。戦闘していない間ずっと
          呼ばれる場所なので、★安い合図（`battle_count`）が変わったときだけ
          問い合わせます（実測 `recent_battles` 2.68ms / `battle_count` 0.1ms未満）。
        """
        rec = self.battle_review
        review = rec.previous
        if review is None or review.result_label is not None:
            return
        try:
            count = self.db.battle_count(self.rom_hash)
            if count == getattr(self, "_result_probe_count", None):
                return                                 # ★増えていない＝まだ来ない
            self._result_probe_count = count
            rows = self.db.recent_battles(self.rom_hash, 1)
        except Exception:                              # noqa: BLE001
            return
        if not rows:
            return
        from .battle_review import RESULT_LABELS

        got = rows[0]["result"]
        if got:
            rec.set_result(RESULT_LABELS.get(str(got), str(got)))

    def roles_label(self) -> str:
        """誰が何をしようとしているか（2026-08-07 / Phase 9）。

        ⚠⚠ **全員が同じなら、役割を区別できていません。**
          ★実際 `attack(1.0)` が3人並んで「動いた」と誤認しかけました
            （攻撃力が読めていなかった）。★画面でも警告を出します。
        """
        game = self._last_game
        roles = getattr(game, "battle_roles", None) if game else None
        if not roles:
            return "役割: —（戦闘中に出ます）"

        # ★★ 数字が全部同じなら、区別できていない合図。
        import re as _re

        scores = _re.findall(r"\(([-\d.]+)\)", roles)
        same = len(scores) >= 2 and len(set(scores)) == 1
        tail = "　⚠⚠ 全員同じ点です（役割を区別できていません）" if same else ""

        reasons = getattr(game, "battle_plan_reasons", None)
        why = f"　理由: {reasons}" if reasons else ""
        return f"役割: {roles}{tail}{why}"

    def tactics_label(self) -> str:
        """メイン画面に出す1行。**分からないときはそう書く**。"""
        if self.tactics is None:
            return "戦術: —（プロフィール機能が無効）"
        prof = self.active_tactics()
        if prof is None:
            return "戦術: —（読めていません）"
        from ..core.tactics import models as tactics_models

        off = [tactics_models.CHARACTER_LABELS[cid]
               for cid in tactics_models.CHARACTER_IDS
               if not prof.get(cid, "root", "enabled")]
        # ★AI操作OFF の人は**必ず出す**。出さないと
        #   「その人だけ動かない」を不具合だと思われる。
        tail = f"　⚠ 手動: {'・'.join(off)}" if off else ""
        # ★★ 大目的も同じ行に出す（2026-08-05 / Phase 3）★★
        #   ⚠⚠ 操作直後の一言（`_align_status`）は、AUTO の ON/OFF などに
        #     **上から塗りつぶされます**（実際に踏んだ）。
        #   ★いま何で戦っているかは**常時見える場所**に置くこと。
        from ..core.mission.settings import MISSION_LABELS

        try:
            mission = MISSION_LABELS[self.mission().mission]
        except Exception:                              # noqa: BLE001
            mission = "—"
        return f"目的: {mission}　戦術: {prof.name}{tail}"

    # --- 遷移の種類を人が直す（フェーズ4）------------------------------

    def transitions_at(self, place) -> list:
        """そのマスから出る遷移。★立っている所を直すために使う。"""
        repo = self._repo()
        if repo is None or place is None:
            return []
        try:
            return repo.transitions_at(place)
        except Exception:                              # noqa: BLE001
            return []

    def set_transition_type(self, transition_id, kind) -> bool:
        """遷移の種類を人が決める。⚠ 読めない種類なら False（入れない）。"""
        repo = self._repo()
        if repo is None:
            return False
        try:
            return bool(repo.set_transition_type(transition_id, kind))
        except Exception:                              # noqa: BLE001
            return False

    def set_transition_type_here(self, place, kind) -> int:
        """いま立っているマスから出る遷移**すべて**の種類を決める。

        戻り値は直した本数。**0 なら「ここに遷移の記録が無い」**。

        ⚠ 同じマスから2つ以上の遷移が出ていることはある（船の乗り降りなど）。
          1本だけ直して「直した」と言わない。
        """
        rows = self.transitions_at(place)
        return sum(1 for row in rows
                   if self.set_transition_type(row.get("id"), kind))

    def request_tile_shot(self) -> bool:
        """いま立っているタイルの写真を撮るよう Lua へ頼む。

        ★★ **なぜ人が押すのか** ★★
          遷移に気づいたときには画面はもう次のマップ。だから
          「踏んだタイル」は自動では撮れない。
          その上に立っているうちに押してもらう。

        ⚠ 座標は **Lua が読む**（こちらの値は最大0.5秒古い）。
        """
        if self.read_only:
            return False
        try:
            # ★`request_id` は `CommandService` が採番する（指示書 §5.2）。
            #   ⚠ 同じ値だと Lua が無視する。採番の規則を1か所に置く。
            return self.commands.request("capture_tile") is None
        except Exception:                              # noqa: BLE001
            return False

    # --- つながり（フェーズ7）------------------------------------------

    def world_graph(self):
        """マップとマップのつながり。★節は `(map_id, map_ptr)`。

        ⚠ 毎回作り直す（遊んでいる間に増えるので、溜め込むと古くなる）。
          遷移の記録は数百行なので作り直しは軽い。
        """
        repo = self._repo()
        if repo is None:
            return None
        try:
            from ..core.navigation.graph import WorldGraph

            return WorldGraph.load(repo)
        except Exception:                              # noqa: BLE001
            return None

    def location_graph(self):
        """ロケーションのつながり（人に見せる段）。

        ⚠ **これで歩かせない**（同じロケーションの別の階をまとめてしまう）。
        """
        repo = self._repo()
        if repo is None or self.location_resolver is None:
            return None
        try:
            from ..core.navigation.graph import LocationGraph

            return LocationGraph.load(repo, self.location_resolver.dictionary)
        except Exception:                              # noqa: BLE001
            return None

    def connections(self, map_id, map_ptr) -> list:
        """そのマップから**行けたと観測した**先の一覧。

        戻り: `[(見出し, どこに立てば移れるか, 種類), ...]`
        """
        graph = self.world_graph()
        if graph is None:
            return []
        found = []
        for link in graph.links.get((int(map_id), int(map_ptr)), []):
            found.append((self.map_label(link.target[0], link.target[1]),
                          link.from_xy, link.kind))
        return found

    def current_place(self, state):
        """状態から `Place` を作る。**1つでも読めなければ None**。

        ★判定は Observer と同じ条件にしたい（別々にすると食い違う）。
          ここでは表示用なので `map_ptr` が読めなくても場所は作る
          （ポインタは名前の判断に使っていない）。
        """
        if state is None or not getattr(state, "fresh", False):
            return None
        if state.map_id is None or state.map_x is None or state.map_y is None:
            return None
        from ..core.navigation.models import Place

        return Place(state.map_id, state.map_data_pointer or 0,
                     state.map_x, state.map_y)

    def current_location(self, state):
        """いま居る場所の名前（`ResolvedLocation`）。**分からなければ None**。

        ⚠ 辞書が無い環境では常に None。呼ぶ側は座標だけの表示に落とす。
        """
        if self.location_resolver is None:
            return None
        return self.location_resolver.resolve(self.current_place(state))

    def location_search_terms(self, state) -> list:
        """いま居る場所の攻略を調べるときの語（仕様 4.7）。

        ★名前が分からないときは**空**を返す。間違った語で調べさせない。
        """
        resolved = self.current_location(state)
        if resolved is None:
            return []
        return resolved.search_terms()

    def where_am_i(self, state) -> str:
        """メイン画面に出す1行。**分からないときはそう書く**。"""
        if state is None or not state.fresh:
            return "いまどこ: —（エミュレータ未接続）"
        if state.in_battle:
            return "いまどこ: 戦闘中"
        if state.map_id is None or state.map_x is None:
            return "いまどこ: —（位置を読めていません）"
        meta = self.map_meta.get(state.map_id) or {}
        size = ("" if not meta.get("width")
                else f" / {meta['width']}×{meta['height']}")
        # ★地名が引けたら先に出す。引けなければ従来どおり ID だけ
        #   （**名前を推測して埋めない**）。
        # ⚠ ここに「要確認」の印は付けない。日本語名の大半は ROM 由来でないので
        #   ほぼ全部に印が付き、**印が意味を持たなくなる**。
        #   確認が必要な名前は地図ウィンドウ側でまとめて出す。
        resolved = self.current_location(state)
        head = f"マップ {state.map_id:02X}"
        if resolved is not None and resolved.registered:
            head = f"{resolved.display} [${state.map_id:02X}]"
        return f"いまどこ: {head}（{state.map_x}, {state.map_y}）{size}"

    def battle_events(self, battle_id: int) -> list:
        """その戦闘の出来事（Phase 3）。

        ★選ばれたときだけ引く。毎回 50 戦闘ぶん引くと、
          行数が増えるほど描画が重くなる（指示書の禁止事項）。
        """
        return self.db.battle_events(battle_id)

    def format_drops(self, monster_ids) -> str:
        """その戦闘の敵が**落としうる**ものを1行にする（2026-07-29）。

        ★★ 依頼者の指摘: 「戦闘ログでドロップも表示させたい」

        ⚠ **実際に落ちたものではない。** 何を拾ったかは記録していない
          （検知手段が未特定なので、憶測でイベントを作らない）。
          出しているのは ROM のドロップ表そのもの。

        ★同じ敵が複数いても1回だけ出す（幅を食わないように）。
        """
        from ..core.db.behavior import format_drop

        seen: list[str] = []
        for mid in dict.fromkeys(monster_ids or []):
            stat = self.monster_stats.get(mid) or {}
            text = format_drop(stat.get("drop"), self.items)
            if text and text not in seen:
                seen.append(text)
        return " / ".join(seen) if seen else "なし"

    def monster_name(self, monster_id: int) -> str:
        return self.monsters.get(monster_id, f"未知(0x{monster_id:02X})")

    def format_monsters(self, ids: list[int]) -> str:
        """[1,1,2] を「スライム×2, おおナメクジ」のように整形する。"""
        if not ids:
            return "-"
        counts: dict[int, int] = {}
        order: list[int] = []
        for monster_id in ids:
            if monster_id not in counts:
                order.append(monster_id)
            counts[monster_id] = counts.get(monster_id, 0) + 1
        parts = []
        for monster_id in order:
            name = self.monster_name(monster_id)
            n = counts[monster_id]
            parts.append(f"{name}×{n}" if n > 1 else name)
        return ", ".join(parts)

    def _battle_view(self):
        """戦闘の要約と一覧。**戦闘が増えたときだけ作り直す**（2026-07-31）。

        ## ★実測（`research/probes/reusable/measure_gui.py` / 本物のデータ 1875 件）

            recorder.poll()             0.28 ms
            db.speedup_summary()        0.60 ms
            db.recent_battles(50)       2.68 ms   ← いちばん重い
            poll() 全体                 5.87 ms

        ⚠⚠ **この5msは、戦闘が起きていない間もずっと払っていた。**
          戦闘の一覧が変わるのは**戦闘が記録されたときだけ**なのに、
          0.5秒ごとに SQLite を叩いて 50 行を組み直していた。

        ★合図は `battle_count`（1本のクエリ）。★ここは安い（実測 0.1ms 未満）。
          ⚠ 「最後の id」ではなく件数にする。id は消しても減らないので、
            消したときに一覧が更新されない。

        ⚠ 名前や落とし物の表示を変えたときも作り直す必要があるが、
          それは起動時に決まる（`format_monsters` は ROM 由来）ので考えない。
        """
        count = self.db.battle_count(self.rom_hash)
        cached = getattr(self, "_battle_cache", None)
        if cached is not None and cached[0] == count:
            return cached[1], cached[2]

        import json

        summary = self.db.speedup_summary(self.rom_hash)
        rows = []
        for row in self.db.recent_battles(self.rom_hash, self.log_limit):
            ids = json.loads(row["monster_ids"])
            frames = row["duration_frames"]
            actual_ms = row["duration_ms"]
            baseline_s = (frames / 60.0) if frames else None
            actual_s = (actual_ms / 1000.0) if actual_ms is not None else None
            saved = None
            if baseline_s is not None and actual_s is not None:
                saved = max(0.0, baseline_s - actual_s)
            rows.append(BattleRow(
                battle_id=int(row["id"]),
                started_at=_to_local(str(row["started_at"])),
                monsters=self.format_monsters(ids),
                is_first_encounter=bool(row["is_first_encounter"]),
                is_boss=bool(row["is_boss"]),
                speed_applied=row["speed_applied"],
                duration_seconds=actual_s,
                saved_seconds=saved,
                drops=self.format_drops(ids),
            ))
        self._battle_cache = (count, summary, rows)
        return summary, rows

    def poll(self) -> UiState:
        """新着イベントを取り込み、現在の表示内容を返す。

        閲覧専用のときは**取り込まない**（DB の内容を映すだけ）。
        """
        if not self.read_only:
            self.recorder.poll()
        stats = self.recorder.stats
        summary, rows = self._battle_view()

        # ★★ 同じ画面に真実の源を2つ置かない ★★
        #
        #   状態には2つの経路がある:
        #     events.jsonl -> Recorder … **起きたこと**の積み重ね。遅れうる
        #     state.json               … Lua が 0.5 秒ごとに書く**いまの値**
        #
        #   両方を別々に表示していたら、ヘッダーが「フィールド ×1」なのに
        #   パーティ欄は戦闘中、という食い違いが出た（実際に画面で確認）。
        #   **いまの値がある間はそちらを正とする。**
        #   Recorder 側は、FCEUX が動いていないときの受け皿として残す。
        game = self.state_reader.read() if self.state_reader else GameState()
        self._apply_party_names(game)
        # ★推論の4段を画面に出すために取っておく（2026-08-07 / Phase 9）。
        #   ⚠ 別経路で読み直すと「真実の源が2つ」になります（上の注意参照）。
        self._last_game = game
        # ★★ 直前戦闘レビューの記録（2026-08-12 / 依頼者の指示 §14）★★
        #   ⚠ **毎回呼んでよい**。中で「ターンが変わった／内容が増えた」
        #     ときだけ1件足します（同じターンを polling 回数ぶん増やしません）。
        self.battle_review.observe(game)
        # ★移動知識の観測。**毎回呼んでよい**（何か分かったときだけ DB に触る）。
        #   ⚠ 失敗しても本体は止めない（Observer が内側で握っている）。
        if self.navigation is not None:
            self.navigation.observe(game)
        if game.fresh:
            in_battle, speed = game.in_battle, game.speed
            danger, danger_reason = game.danger, game.danger_reason
        else:
            in_battle, speed = stats.in_battle, stats.current_speed
            danger, danger_reason = stats.danger, stats.danger_reason

        return UiState(
            in_battle=in_battle,
            speed=speed,
            danger=danger,
            current_monsters=self.format_monsters(stats.current_monsters),
            battles_recorded=int(summary["battles"]),
            warnings=list(stats.warnings),
            danger_reason=danger_reason,
            game=game,
            rows=rows,
            saved_seconds_total=float(summary["saved_ms"]) / 1000.0,
            average_speed=float(summary["avg_speed"]),
            read_only=self.read_only,
        )
