"""実機 E2E の**テスト名の名簿**（RX3-0129 拡張 / 2026-09-09）。

```text
⚠ これまで   「`--scenarios survival:forbid` で回した」
             → ★何を確かめた run なのかは、コマンド行を読み解くしかない
★これから   「`battle_ai_mp_forbidden` を回した」
```

## ⚠⚠ なぜ名簿が要るのか

★fixture の台帳（`fixtures.json`）は `tests: [...]` を持ちます。
⚠ そこへ**打ち間違えた名前**が書かれても、名簿が無ければ誰も気づきません
（★「使うテストが 3 件あります」と嘘の表示になる）。

→ ★名簿と突き合わせて、⚠ **無い名前は checker が赤にします**（`check_fixtures.py`）。

## ★名簿にあるもの / 無いもの

```text
★ある   実機を起こして端から端まで通す run（⚠ pytest では回せない）
⚠ 無い  ふつうの pytest（★`tests/` の関数名がそのまま id になります）
```

⚠ 期待結果はここに置きません（★入力の意味は fixture、期待は run 側 / 指示書 §12）。
"""
from __future__ import annotations

import dataclasses

from ..battle_ai import settings as S

BATTLE_AI_RUNNER = "scripts/dq3_battle_ai_run.py"
RESTOCK_RUNNER = "scripts/dq3_restock_run.py"


@dataclasses.dataclass(frozen=True)
class E2ETest:
    """★実機で回せる 1 本（⚠ 「何を確かめるか」まで。★期待の数値は持たない）。"""

    id: str
    purpose: str
    runner: str
    #: ★戦闘 AI の run に渡す `作戦:MP制約`（⚠ 他の runner では None）
    scenario: str | None = None
    #: ★歩いてから戦う run か（⚠ フィールドの fixture が要る）
    walk: int = 0

    @property
    def strategy(self) -> str | None:
        return self.scenario.split(":")[0] if self.scenario else None

    @property
    def mp(self) -> str | None:
        return self.scenario.split(":")[1] if self.scenario else None

    def command(self, fixture_id: str | None = None) -> str:
        """★人が打てる形（⚠ 報告へそのまま貼れるように）。"""
        bits = ["PYTHONUTF8=1", "python", self.runner]
        if fixture_id:
            bits += ["--fixture", fixture_id]
        if self.scenario:
            bits += ["--scenarios", self.scenario]
        if self.walk:
            bits += ["--walk", str(self.walk)]
        return " ".join(bits)


def _battle(test_id: str, purpose: str, scenario: str, walk: int = 0) -> E2ETest:
    """⚠ 作戦・MP 制約は**製品の定義**と突き合わせる（★名簿側の打ち間違いも赤にする）。"""
    strategy, mp = scenario.split(":")
    if strategy not in S.STRATEGIES:
        raise ValueError("⚠ 知らない作戦です: %r（★%r）" % (strategy, S.STRATEGIES))
    if mp not in S.MP_POLICIES:
        raise ValueError("⚠ 知らない MP 制約です: %r（★%r）" % (mp, S.MP_POLICIES))
    return E2ETest(id=test_id, purpose=purpose, runner=BATTLE_AI_RUNNER,
                   scenario=scenario, walk=walk)


#: ★名簿（⚠ 増やすときは、★実際に回せる run だけを足す）
TESTS: dict[str, E2ETest] = {t.id: t for t in (
    _battle("battle_ai_survival", "生存優先。★瀕死を先に手当てするか", "survival:auto"),
    _battle("battle_ai_mp_forbidden", "MP 使用禁止。⚠ 呪文へ落ちないか", "survival:forbid"),
    _battle("battle_ai_economy", "リソース節約。★MP と消耗品を残すか", "economy:auto"),
    # ★★ economy の baseline を採る run（RX3-0404 / 依頼者 §22「まず 20 戦」）
    _battle("battle_ai_economy_benchmark",
            "リソース節約の baseline。★石・たて・無料の攻撃道具・MP の内訳を実機で数える",
            "economy:auto", walk=20),
    _battle("battle_ai_leveling", "最短撃破。★手数を減らして戦闘を早く終わらせるか", "leveling:auto"),
    _battle("world_walker_encounter",
            "世界地図を歩いて**自然に**遭遇し、★そのまま戦闘 AI へ渡るか",
            "survival:auto", walk=3),
    E2ETest(id="restock_buy_missing_items",
            purpose="足りない道具だけを店で買う（★計画 → 実際の所持数で確かめる）",
            runner=RESTOCK_RUNNER),
    E2ETest(id="hearing_arena_fixed_npc",
            purpose="格闘場で聞き込み。★固定の NPC（受付）の升を通らずに全員と話すか（RX3-0176）",
            runner="scripts/dq3_town_turbo_run.py"),
    E2ETest(id="hearing_counter_moving_npc",
            purpose="カザーブの酒場で聞き込み。★カウンターの奥を動く人とカウンター越しに話すか（RX3-0182）",
            runner="scripts/dq3_town_turbo_run.py"),
)}


def get(test_id: str) -> E2ETest | None:
    return TESTS.get(test_id)


def ids() -> list[str]:
    return sorted(TESTS)


__all__ = ["E2ETest", "TESTS", "get", "ids", "BATTLE_AI_RUNNER", "RESTOCK_RUNNER"]
