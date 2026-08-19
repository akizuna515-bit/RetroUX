"""敵の「行動と確率」「ドロップ」を人が読める形にする（Qt に依存しない）。

★ここを画面から切り離す理由:
  行動の確率は**0x1E（選び直し）を除いて正規化する**という決まりがあり、
  それを画面のコードに書くと、テストのために Qt を起動する必要が出る。
  純粋な関数にしておけば、値だけで検証できる。

出典と根拠は `docs/design/monster-book-spec.md` 3章。
仕組みは ROM の実コード（`bank4.asm:8078`）から確定し、
**全82体で公開データと一致**している（`research/probes/archived/solve_actions.py --verify`）。
"""

from __future__ import annotations

# ★有効な行動ではない値。引いたら選び直す（`memory_map` の monster_actions 0x1E）。
#   ⚠ **確率を出すときは必ず除いて正規化する。**
#     混ぜると「アンデッドマンは12.5%で何もしない」と出てしまう
#     （公開データは通常攻撃 100%）。
REROLL_ACTION = 0x1E

# ドロップ確率の分母 -> 人が読む表記。
#   ★「1/128」のように**分数で出す**。パーセントにすると 0.8% になり、
#     「ほぼ落ちない」ことが伝わりにくい。


def action_breakdown(behavior: dict | None, action_names: dict | None,
                     rates: dict | None) -> list[tuple[str, float]]:
    """その敵の「行動名と確率(%)」を、確率の高い順に返す。

    戻り値が空リストなら「データが無い」。**0% の行を作らない。**

    ★計算の順番（順番を変えると値が変わる）:
      1. 8つの枠それぞれに、賢さごとの確率を割り当てる
      2. 同じ行動が複数の枠にあれば**足す**
      3. **選び直し（0x1E）を除く**
      4. 残りを合計100%になるよう**正規化する**

    ⚠ 3 と 4 を飛ばすと公開データと合わない。
      アンデッドマンは ROM 上「通常攻撃 87.5% + 選び直し 12.5%」だが、
      実際には**通常攻撃 100%**（選び直しは引き直すだけなので表に出ない）。
    """
    if not behavior or not action_names or not rates:
        return []
    actions = behavior.get("actions") or []
    wisdom = behavior.get("wisdom")
    slot_pct = rates.get(wisdom)
    if not actions or not slot_pct:
        return []
    if len(actions) != len(slot_pct):
        # ★枠の数が合わないなら前提が崩れている。**推測で埋めずに何も返さない。**
        return []

    totals: dict[int, float] = {}
    for aid, pct in zip(actions, slot_pct):
        totals[aid] = totals.get(aid, 0.0) + float(pct)

    live = {aid: pct for aid, pct in totals.items() if aid != REROLL_ACTION}
    total = sum(live.values())
    if total <= 0:
        return []

    out = [(str(action_names.get(aid, f"不明(0x{aid:02X})")), pct / total * 100.0)
           for aid, pct in live.items()]
    # 確率の高い順。同率は名前順にして、実行するたびに並びが変わらないようにする
    out.sort(key=lambda kv: (-kv[1], kv[0]))
    return out


def format_actions(breakdown: list[tuple[str, float]]) -> str:
    """「ホイミ 88.3% / 通常攻撃 11.7%」の形にする。"""
    if not breakdown:
        return ""
    return " / ".join(f"{name} {pct:.1f}%" for name, pct in breakdown)


def format_drop(drop: dict | None, items: dict | None) -> str:
    """「やくそう（1/128）」の形にする。ドロップが無ければ空文字。

    ⚠ 「落とさない」と「まだ分からない」を混ぜないため、
      **ドロップを持たない敵には drop キー自体が無い**（memory_map の方針）。
      ここで空文字を返し、呼び出し側が「落とさない」と書く。
    """
    if not drop:
        return ""
    item_id = drop.get("item")
    denom = drop.get("denominator")
    name = (items or {}).get(item_id)
    label = str(name) if name else f"不明な道具(0x{item_id:02X})"
    if not denom:
        return label
    return f"{label}（1/{denom}）"


def resist_label(value: int | None) -> str:
    """耐性値を「効き方」の言葉にする。

    ★成功率 = (7 - 値) / 7（ROM の実コードから確定）。
      数値だけ出しても意味が分からないので、言葉を添える。
    """
    if value is None:
        return "-"
    if value <= 0:
        return "必ず効く"
    if value >= 7:
        return "効かない"
    return f"{(7 - value) / 7 * 100:.0f}%"
