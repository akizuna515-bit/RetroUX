"""まんたんの設定（2026-08-02 / 指示書 `input/260802_manatan.md` §3・§12）。

★★ **3層**（`keybindings.py` と同じ考え方）★★

    retroux/plugins/dq2/config.yaml の `mantan`   ゲームの知識（同梱）
      ↓ 書いてある項目だけ上書き
    config/mantan.yaml                            利用者の設定（各自）
      ↓
    実行時のまんたん方針

⚠ 指示書 §3.1 は `user/manten.yaml` を推していますが、
  「既存のユーザー設定ディレクトリ規則があれば、それに合わせること」とも
  書かれています。★このプロジェクトには既に規則があります:

      同梱の既定 : retroux/config/default_*.yaml
      各自の設定 : config/*.yaml（`.gitignore` 済み）

  `config/layout.yaml` と `config/keybindings.yaml` がその形なので、
  新しい `user/` を作らず **`config/mantan.yaml`** に揃えます。

## ⚠⚠ **設定が壊れていても RetroUX は起動できること**（指示書 §4.2）

  まんたんの設定が1つ間違っているだけで遊べなくなるのは筋が悪い。
  読めないときは**既定値へ落として、理由を持って画面に出す**。
  ★`problems` に理由を溜めます。**黙って捨てません。**
"""

from __future__ import annotations

import dataclasses
import pathlib

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
USER_PATH = PROJECT_ROOT / "config" / "mantan.yaml"

#: この版が読める形。★上げるときは移行のしかたも一緒に決める。
SCHEMA_VERSION = 1

# --- 選べる値 ----------------------------------------------------------

#: 道具を呪文の前に使うか、後に回すか、使わないか（指示書 §3.3）
ITEM_POLICIES = ("before_spells", "after_spells", "disabled")

#: サマルトリアとムーンブルクへの MP の配り方（指示書 §3.3・§9）
MP_POLICIES = (
    "remaining_ratio_balance",   # ★今回の既定。残存MP率をそろえる
    "spent_mp_balance",          # 消費MPの累計をそろえる
    "most_mp",                   # 現在MPが多い側（現行互換）
    "list_order",                # methods の順（現行互換）
)

#: 回復呪文の選び方。⚠ 指示書 §3.3「現時点では選択肢を増やさない」
SPELL_POLICIES = ("minimum_expected_total_mp",)

#: まんたん完了とみなす HP 割合の下限・上限（指示書 §5.2 / GUI の実用範囲）
HP_PERCENT_MIN, HP_PERCENT_MAX = 50, 100

#: MP偏りの補正の重みの上限。★これ以上は「安さ」が意味を失います
BALANCE_WEIGHT_MAX = 10.0

#: 表示名 <-> 内部値（指示書 §5.2）。★GUI と設定ファイルで二重管理しない
ITEM_POLICY_LABELS = {
    "before_spells": "呪文より先に使う",
    "after_spells": "呪文を優先する",
    "disabled": "使用しない",
}
ANTIDOTE_POLICY_LABELS = {
    "before_spells": "キアリーより先に使う",
    "after_spells": "キアリーを優先する",
    "disabled": "使用しない",
}
MP_POLICY_LABELS = {
    "remaining_ratio_balance": "残存MP率を揃える",
    "spent_mp_balance": "消費MP量を揃える",
    "most_mp": "現在MPが多い側を優先",
    "list_order": "設定順",
}


@dataclasses.dataclass(frozen=True)
class MantanSettings:
    """まんたんの方針。★既定値のままで動きます。

    ⚠ 値は**この型を通してだけ**触ります。GUI・YAML・Lua 生成が
      それぞれ別の既定値を持つと、必ず食い違います。
    """

    #: まんたん完了とみなす HP 割合（%）。指示書 §3.3 の既定は 90
    target_hp_percent: int = 90
    #: やくそうを呪文の前に使うか（指示書 §7.1）
    herb_policy: str = "after_spells"
    #: どくけしそうをキアリーの前に使うか（指示書 §7.2）
    antidote_policy: str = "after_spells"
    #: サマルトリアとムーンブルクへの MP の配り方（指示書 §9）
    mp_policy: str = "remaining_ratio_balance"
    #: ★偏りをどれだけ嫌うか（`remaining_ratio_balance` のときだけ効く）
    #
    #  ⚠⚠ 2026-08-03、依頼者の実機で「残存MP率を揃える」が効いていませんでした。
    #    サマル 27/91(30%) / ムーン 82/135(61%) でも、**安いホイミ**（サマル）が
    #    毎回選ばれ続けたためです。総消費MPだけで比べていたのが原因。
    #
    #    実効MP = 総消費MP × (1 + (平均率 - 唱える人の率) × 重み)
    #
    #    重み 2.0 だと、率の差が **およそ 3 割** を超えたところで
    #    高いほうの呪文に切り替わります（★上のログの数字で確認済み）。
    #    0 にすると、これまでどおり純粋に安い呪文を選びます。
    mp_balance_weight: float = 2.0
    #: 回復呪文を使うか（指示書 §5.2）
    healing_spells_enabled: bool = True
    #: 回復呪文の選び方（指示書 §8）
    spell_policy: str = "minimum_expected_total_mp"
    #: 解毒するか
    poison_cure_enabled: bool = True
    #: 戦術プロフィールの最低残存MPを使うか（指示書 §5.2・§10）
    use_tactics_reserve: bool = True

    @property
    def target_ratio(self) -> float:
        """Lua と同じ割合（指示書 §6.1）。"""
        return self.target_hp_percent / 100

    def to_yaml_dict(self) -> dict:
        """`config/mantan.yaml` に書く形（指示書 §3.2）。"""
        return {
            "schema_version": SCHEMA_VERSION,
            "target_hp_percent": self.target_hp_percent,
            "items": {
                "herb": {"policy": self.herb_policy},
                "antidote": {"policy": self.antidote_policy},
            },
            "mp_allocation": {
                "policy": self.mp_policy,
                "balance_weight": self.mp_balance_weight,
            },
            "healing_spells": {
                "enabled": self.healing_spells_enabled,
                "selection_policy": self.spell_policy,
            },
            "poison_cure": {"enabled": self.poison_cure_enabled},
            "mp_reserve": {"use_tactics_profile": self.use_tactics_reserve},
        }

    def to_lua_dict(self) -> dict:
        """`work/generated/config.lua` の `mantan` へ足す形（指示書 §13）。

        ★Lua 側が読む名前はここだけで決めます。
        ⚠ 既存の `mode` / `modes` / `methods` は**消しません**（§14）。
        """
        return {
            "target_hp_percent": self.target_hp_percent,
            "herb_policy": self.herb_policy,
            "antidote_policy": self.antidote_policy,
            "mp_policy": self.mp_policy,
            "mp_balance_weight": self.mp_balance_weight,
            "healing_spells_enabled": self.healing_spells_enabled,
            "spell_policy": self.spell_policy,
            "poison_cure_enabled": self.poison_cure_enabled,
            "use_tactics_reserve": self.use_tactics_reserve,
        }


def summary_lines(s: MantanSettings) -> list[str]:
    """実行開始時にログへ出す概要（指示書 §11.1）。"""
    herb = ITEM_POLICY_LABELS.get(s.herb_policy, s.herb_policy)
    anti = ANTIDOTE_POLICY_LABELS.get(s.antidote_policy, s.antidote_policy)
    mp = MP_POLICY_LABELS.get(s.mp_policy, s.mp_policy)
    return [
        f"まんたん開始: 目標{s.target_hp_percent}%",
        f"回復手段: {'呪文を使う' if s.healing_spells_enabled else '呪文は使わない'}"
        f"／やくそうは{herb}",
        f"解毒手段: {'キアリーを使う' if s.poison_cure_enabled else '解毒しない'}"
        f"／どくけしそうは{anti}",
        f"MP配分: {mp}",
        "最低残存MP: "
        + ("戦術プロフィールを使用" if s.use_tactics_reserve else "使用しない"),
    ]
