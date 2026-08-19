"""Lua が書く「いまの状態」を読む（MVP2 Phase 2 / Lua -> Python）。

    work/state.json … いまの値（上書き・表示用）

★events.jsonl と役割が違う:

| ファイル | 中身 | 書き方 | 消えると |
| --- | --- | --- | --- |
| `events.jsonl` | **起きたこと** | 追記 | 記録が失われる（DB へ入る前なら） |
| `state.json` | **いまの値** | 上書き | 次の 0.5 秒で書き直される（困らない） |

毎秒の HP/MP を events.jsonl に流すと、記録が現在値で埋まって
「戦闘の履歴」という意味が変わるうえ、ファイルも DB も肥大化する。

★読めないときは**前回の値を返す**。書き換えの一瞬に当たることがあるため。
  そのたびに画面が「-」へ落ちると、正常なのに壊れて見える。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Member:
    name: str
    index: int = 0
    hp: int = 0
    max_hp: int = 0
    mp: int = 0
    max_mp: int = 0
    level: int = 0
    exp: int | None = None
    """経験値。**None は「届いていない」**（0 とは違う）。

    ★古い FCEUX 側がまだ動いていると、この項目が state.json に無い。
      そのとき 0 として扱うと、LV20 のキャラが「経験値 0 = 最大レベル」に
      見えてしまう（実際に画面でそうなった）。**無いことは無いと出す。**
    """
    next_level: int | None = None
    exp_to_next: int | None = None
    attack: int | None = None
    """こうげきりょく。**None は「届いていない」**（0 とは違う）。

    ⚠ 古い FCEUX 側がまだ動いていると、この項目が state.json に無い。
      0 として扱うと「攻撃力 0」という**ありえない値**を出してしまう。
      ★経験値で同じ間違いをしているので、同じ形にしてある（上の `exp` 参照）。
    """
    defense: int | None = None
    """しゅびりょく。**None は「届いていない」**（0 とは違う）。"""
    strength: int | None = None
    """ちから。⚠ **こうげき力とは別物**（こうげき力 = ちから + 武器）。"""
    agility: int | None = None
    """すばやさ。★2026-07-31 に「つよさ」の画面のキャプチャから特定した。"""
    alive: bool = True
    poisoned: bool = False
    status: int = 0

    @property
    def hp_ratio(self) -> float:
        return (self.hp / self.max_hp) if self.max_hp else 0.0

    @property
    def mp_ratio(self) -> float:
        return (self.mp / self.max_mp) if self.max_mp else 0.0


@dataclass
class EnemyGroup:
    id: int
    count: int = 1
    name: str = ""


@dataclass
class Enemy:
    """戦闘に出ている敵1体。

    ★`hp_start` は**戦闘開始時のHP**。最大HPではない。
      DQ2 の敵HPは最大HPの75〜100%でばらつき、最大HPは RAM に無い。
      画面の分母には「その戦闘で満タンだった値」を使うのが正しい。
    """

    index: int
    id: int
    name: str = ""
    hp: int = 0
    hp_start: int = 0
    max_hp: int | None = None
    status: int = 0
    threat_hits: int | None = None
    """この敵の一撃を、いちばん危ない味方が**あと何発**耐えられるか。

    ★点数ではなく発数にしてある。点数は基準が無いと読めないが、
      「あと2発」は誰でも分かる。
    ⚠ ダメージは**目安**（公開されている式による近似）。ROM の計算そのものは
      追っていないので、実際とはずれる。
    """
    threat_damage: int | None = None
    threat_target: str | None = None

    @property
    def hp_ratio(self) -> float:
        """★分母は**種族の最大HP**（ROM 由来）。

        DQ2 の敵は最大HPの75〜100%で出てくるので、満タンでも
        バーが 8 割ということがある。**それが実際の状態**なので、
        戦闘開始時のHPを 100% に見せない。

        最大HPが分からない敵（表に無い）だけ、戦闘開始時のHPで割る。
        """
        base = self.max_hp or self.hp_start
        return (self.hp / base) if base else 0.0

    @property
    def hp_denominator(self) -> int:
        return self.max_hp or self.hp_start


@dataclass
class GameState:
    """Lua が見ている現在の状態。読めていないときは `fresh=False`。"""

    frame: int = 0
    time: float = 0.0
    in_battle: bool = False
    speed: float = 1.0
    danger: bool = False
    danger_reason: str | None = None
    auto_input: bool = False
    force_auto: bool = False
    turbo_enabled: bool | None = None
    """高速化（戦闘中の倍速）の状態。**None は「届いていない」**。

    ★状態を持っているのは Lua 側。画面はここを見て追従する。
    ⚠ 既定を False にしないこと。古い Lua が繋がっているときに
      「切ってある」と誤って表示し、ボタンが勝手に OFF へ動く。
    """
    auto_enabled: bool | None = None
    """AUTO（AI に操作を任せるか）の状態。**None は「届いていない」**。

    ★★ `turbo_enabled` とは**独立した軸**（2026-07-31 の指示書 §2）★★
      片方から他方を推測しない。「速いなら AUTO だろう」は成り立たない。

    ⚠ `auto_input`（いま実際に AI が操作しているか）とも別物。
      `auto_enabled=True` でも危険状態なら `auto_input=False` になる。
      **設定と、その結果**を混ぜない。
    """
    requested_action: str | None = None
    """キーで頼まれた画面側のアクション（2026-08-01）。

    ★★ **キーを拾えるのは Lua だけ。** ★★
      遊んでいる間フォーカスは FCEUX にあるので、画面はキーを見られない。
      Lua が「押された」と書き、画面がここを見て実行する。
    """
    requested_action_seq: int = 0
    """★通し番号。⚠ 名前だけだと**同じキーの2回目**を取りこぼす。"""
    manual_latched: bool = False
    caution: bool = False
    gold: int | None = None
    """所持ゴールド。**None は「届いていない」**（0 とは違う）。

    ★パーティ共通なので人ごとの表には入れない（上段に出す）。
    """
    party: list[Member] = field(default_factory=list)
    enemy_groups: list[EnemyGroup] = field(default_factory=list)
    enemies: list[Enemy] = field(default_factory=list)
    actor: str | None = None
    ai_action: str | None = None
    ai_reason: str | None = None
    ai_decisions: list = field(default_factory=list)
    """★**3人ぶん**の判断（2026-07-31 / 依頼者の指摘）。

    ⚠ 以前は1つしか無かったので、**最後に入力した人の判断で上書き**され、
      他の2人が見えなかった（「行動者ごとに切り替わる」の正体）。

    要素は `{"index", "name", "action", "reason", "turn"}`。
    ★判断がまだ無い人も**行は出す**（消えると状態が読めない）。
    """
    # --- ★★★ 推論の4段（2026-08-07 / 戦闘AI再設計 Phase 9）------------
    #
    #     目的 -> 戦況 -> 戦術 -> 役割
    #
    # ⚠⚠ **どれも「届いていない」は None。** ★0 や "" で埋めないこと。
    #   0 を入れると画面が「測った結果ゼロ」と表示し、
    #   ⚠ **測れていないことに永久に気づけません**。
    battle_engine: str | None = None
    """どの判断で動いているか。`legacy` / `layered`。

    ★★ **画面に必ず出すこと。** ⚠ これが無いと「省資源と書いてあるのに
      MPを使っている」に見え、**必ず誤解されます**。
      Phase 1〜9 は判断を変えていません（`legacy` のあいだは説明だけ）。
    """
    battle_balance: str | None = None
    """戦況。`advantage` / `even` / `disadvantage` / `unknown`。

    ⚠ `unknown` は**値が来ている**（材料が無いと分かった）。
      None は**そもそも届いていない**。★この2つは別物です。
    """
    battle_length: str | None = None
    battle_turns_to_win: float | None = None
    battle_turns_to_lose: float | None = None
    battle_tags: str | None = None
    battle_plan: str | None = None
    """選ばれた戦術の名前（★「通常速攻」など）。"""
    battle_plan_score: float | None = None
    battle_plan_margin: float | None = None
    """次点との差。⚠ 小さいなら**次のターンに変わりうる**。

    ★「この判断がどれくらい確からしいか」を人が見るための数字です。
    """
    battle_plan_reasons: str | None = None
    battle_roles: str | None = None
    """誰が何をしようとしているか。

    ⚠⚠ **全員が同じなら、役割を区別できていません。**
      ★実際 `attack(1.0)` が3人並んで「動いた」と誤認しかけました
        （攻撃力が読めていなかった）。
    """

    # --- いまどこに居るか（2026-07-29 / 地図）---------------------------
    # ⚠ **戦闘中は None**（Lua が書かない）。戦闘中の座標は歩いた足跡ではない。
    map_id: int | None = None
    map_x: int | None = None
    map_y: int | None = None
    map_data_pointer: int | None = None
    # ゲーム内で付けたキャラ名の生バイト列（16進）。
    # ★文字にするのは `retroux/core/text.py`。**Lua は表を持たない。**
    party_name_bytes: str | None = None
    # 画面に出ている色を1マス1色（RGB444 の16進3文字）で並べたもの。
    # ★地図を「画面と同じ色」で描くため。読めないマスは "___"。
    map_colors: str | None = None
    map_cells: str | None = None
    """★見たマスの **4枚＋パレット組**（1マス9文字 / 2026-08-02 / 課題 #65）。

    タイルID 2文字 × 4（左上・右上・左下・右下）＋ パレット組 1文字。
    読めないマスは `_________`（9文字）。

    ⚠⚠ **`map_tiles`（左上だけ）では 16×16 の絵が組めません。**
      残り3枚の決まり方がマップごとに違うと実測で分かりました
      （ダンジョン `+4/-1/+3` / 街 `+2/-1/+1`、しかも街には例外あり）。
      ★規則を1つに決めると街の飾りで間違えます。

    ★これがあると、ROM から作った絵をそのまま当てられます
      （`retroux/core/bgmap/rom_assets.py`）。
      ⚠ 絵が用意できても、**見ていないマスは描きません**（指示書 §2.2）。
    """
    map_tiles: str | None = None
    """★見たマスの**タイルID**（1マス2文字の16進 / 2026-08-01）。

    ⚠ 色（`map_colors`）は各マスの中心1画素なので、
      ・洞窟の床（黒地に赤い点）がほぼ黒になる
      ・**主人公自身の色**を地形として拾う
    ★タイルIDならぶれず、スプライトも混ざらない（課題 #65）。
    """
    map_view_radius: int | None = None
    # いま押されている方向（"up"/"down"/"left"/"right"）。
    # ★「進もうとして進めなかった」を観測するために要る（座標だけでは分からない）。
    input_direction: str | None = None
    # --- 戦闘の通し番号（2026-07-29）------------------------------------
    # ★★ 倍速だと GUI が戦闘まるごと1回を見逃す（0.5秒に収まる）。
    #   Lua が数えた番号が変わったことで「新しい戦闘」だと分かる。
    battle_seq: int | None = None
    battle_species: list = field(default_factory=list)

    fresh: bool = False
    """一度でも読めたか。False なら画面には「エミュレータ未接続」を出す。"""


class StateReader:
    """`state.json` を読む。壊れていたら前回の値を返す。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.state = GameState()
        self._mtime: float | None = None

    def read(self) -> GameState:
        try:
            stat = self.path.stat()
        except OSError:
            return self.state          # まだ無い（FCEUX が起動していない）

        # ★更新されていなければ読まない。0.5秒ごとに JSON を読み直すより、
        #   更新時刻を見るほうがずっと軽い。
        if self._mtime is not None and stat.st_mtime == self._mtime:
            return self.state

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # ★書き換えの一瞬に当たることがある。前回の値を返して静かに待つ。
            #   ここで例外を投げると、正常な運用中に画面が落ちる。
            return self.state

        self._mtime = stat.st_mtime
        self.state = _parse(raw)
        return self.state


def _parse(raw: dict) -> GameState:
    members = [
        Member(
            name=str(m.get("name", "?")),
            index=int(m.get("index", 0)),
            hp=int(m.get("hp", 0)), max_hp=int(m.get("max_hp", 0)),
            mp=int(m.get("mp", 0)), max_mp=int(m.get("max_mp", 0)),
            level=int(m.get("level", 0)),
            exp=(int(m["exp"]) if m.get("exp") is not None else None),
            next_level=(int(m["next_level"])
                        if m.get("next_level") is not None else None),
            exp_to_next=(int(m["exp_to_next"])
                         if m.get("exp_to_next") is not None else None),
            attack=(int(m["attack"]) if m.get("attack") is not None else None),
            defense=(int(m["defense"])
                     if m.get("defense") is not None else None),
            strength=(int(m["strength"])
                      if m.get("strength") is not None else None),
            agility=(int(m["agility"])
                     if m.get("agility") is not None else None),
            alive=bool(m.get("alive", True)),
            poisoned=bool(m.get("poisoned", False)),
            status=int(m.get("status", 0)),
        )
        for m in raw.get("party", []) or []
    ]
    groups = [
        EnemyGroup(id=int(g.get("id", 0)), count=int(g.get("count", 1)),
                   name=str(g.get("name", "")))
        for g in raw.get("enemy_groups", []) or []
    ]
    enemies = [
        Enemy(
            index=int(e.get("index", 0)), id=int(e.get("id", 0)),
            name=str(e.get("name", "")), hp=int(e.get("hp", 0)),
            hp_start=int(e.get("hp_start", 0)),
            max_hp=(int(e["max_hp"]) if e.get("max_hp") is not None else None),
            status=int(e.get("status", 0)),
            threat_hits=(int(e["threat_hits"])
                         if e.get("threat_hits") is not None else None),
            threat_damage=(int(e["threat_damage"])
                           if e.get("threat_damage") is not None else None),
            threat_target=e.get("threat_target") or None,
        )
        for e in raw.get("enemies", []) or []
    ]
    return GameState(
        frame=int(raw.get("frame", 0)),
        time=float(raw.get("time", 0) or 0),
        in_battle=bool(raw.get("in_battle", False)),
        speed=float(raw.get("speed", 1) or 1),
        danger=bool(raw.get("danger", False)),
        danger_reason=raw.get("danger_reason") or None,
        auto_input=bool(raw.get("auto_input", False)),
        force_auto=bool(raw.get("force_auto", False)),
        # ⚠ 無いときは None のまま（bool() で False にしない）。
        #   届いていないのか「切ってある」のかを混ぜない。
        turbo_enabled=(None if raw.get("turbo_enabled") is None
                       else bool(raw.get("turbo_enabled"))),
        auto_enabled=(None if raw.get("auto_enabled") is None
                      else bool(raw.get("auto_enabled"))),
        requested_action=raw.get("requested_action") or None,
        requested_action_seq=int(raw.get("requested_action_seq") or 0),
        manual_latched=bool(raw.get("manual_latched", False)),
        caution=bool(raw.get("caution", False)),
        gold=(int(raw["gold"]) if raw.get("gold") is not None else None),
        party=members,
        enemy_groups=groups,
        enemies=enemies,
        actor=raw.get("actor") or None,
        ai_action=raw.get("ai_action") or None,
        ai_reason=raw.get("ai_reason") or None,
        ai_decisions=[d for d in (raw.get("ai_decisions") or [])
                      if isinstance(d, dict)],
        # ⚠ `or None` を使わない。**0 は正しい座標**なので落としてはいけない
        #   （playbook「0 と 不明 を混ぜない」）。
        map_id=_opt_int(raw.get("map_id")),
        map_x=_opt_int(raw.get("map_x")),
        map_y=_opt_int(raw.get("map_y")),
        map_data_pointer=_opt_int(raw.get("map_data_pointer")),
        party_name_bytes=(str(raw["party_name_bytes"])
                          if raw.get("party_name_bytes") else None),
        map_colors=(str(raw["map_colors"]) if raw.get("map_colors") else None),
        map_tiles=(str(raw["map_tiles"]) if raw.get("map_tiles") else None),
        map_cells=(str(raw["map_cells"]) if raw.get("map_cells") else None),
        map_view_radius=_opt_int(raw.get("map_view_radius")),
        input_direction=(str(raw["input_direction"])
                         if raw.get("input_direction") else None),
        # ★★★ 推論の4段（2026-08-07 / Phase 9）★★★
        #   ⚠⚠ **`or None` を使わない。** 0.0 は「測った結果ゼロ」で、
        #     ★「届いていない」とは別物です。
        battle_engine=_opt_str(raw.get("battle_engine")),
        battle_balance=_opt_str(raw.get("battle_balance")),
        battle_length=_opt_str(raw.get("battle_length")),
        battle_turns_to_win=_opt_float(raw.get("battle_turns_to_win")),
        battle_turns_to_lose=_opt_float(raw.get("battle_turns_to_lose")),
        battle_tags=_opt_str(raw.get("battle_tags")),
        battle_plan=_opt_str(raw.get("battle_plan")),
        battle_plan_score=_opt_float(raw.get("battle_plan_score")),
        battle_plan_margin=_opt_float(raw.get("battle_plan_margin")),
        battle_plan_reasons=_opt_str(raw.get("battle_plan_reasons")),
        battle_roles=_opt_str(raw.get("battle_roles")),
        battle_seq=_opt_int(raw.get("battle_seq")),
        battle_species=[v for v in
                        (_opt_int(x) for x in (raw.get("battle_species") or []))
                        if v],
        fresh=True,
    )


def _opt_float(value) -> float | None:
    """数として読めれば float、読めなければ None。

    ⚠⚠ **0.0 を None にしない。** ★「測った結果ゼロ」と
      「届いていない」は別物です（2026-08-07 / Phase 9 の観点2）。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_str(value) -> str | None:
    """文字として読めれば str、無ければ None。

    ⚠ 空文字は None にします（★画面に空欄を出しても何も伝わらない）。
    """
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value) -> int | None:
    """数として読めれば int、読めなければ None。**0 を None にしない。**"""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
