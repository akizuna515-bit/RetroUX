"""戦況欄の**表示専用**の言い換え（2026-08-12 / 依頼者の指示 §3・§17）。

## ★★ ここは「見せ方」だけ。内部値は1つも変えません ★★

依頼者の指示:

    既存の内部英語名をUI都合で書き換えない。表示専用helperを作る。

だから `lorasia` は `lorasia` のまま流れます。**画面に出す直前**だけ「ロ」に
します。⚠ ログ・設定・DB・`state.json` のどれも触りません。

## ★ なぜ短くするのか

右の欄は横が狭く、これまで横に詰め込んでいたので**黙って切れて**いました。
★縦は4行使えるので、4行へ展開し、1行あたりの文字数を減らします。

    優勢・短期
    撃破 0.5T / 崩壊 4.2T
    戦術 省資源 5.5/+1.5
    役割 ロ:攻3.0 サ:道1.3 ム:道1.3

## ⚠⚠ 表に無い値は、そのまま出します

★知らない行動（`status_spell` など）を「？」に潰すと、**新しい行動が
増えたことに気づけません**。★短縮できないものは英語のまま出して、
「この表に足りていない」と分かるようにします。

⚠ 2026-08-12 に実コードを確認した時点の役割の行動は
`attack` / `attack_spell` / `defend` / `heal` / `item`
（`actor_roles.lua` の候補）と、`support` / `manual` です。
★指示にあった `status_spell` は**現行コードにありません**（足しておくが、
出てこない）。
"""

from __future__ import annotations

import re

from ..core.tactics.models import CHARACTER_IDS

#: 画面に出すときの1文字名。⚠ 内部IDは `CHARACTER_IDS` のまま。
SHORT_ACTORS = {"lorasia": "ロ", "samaltria": "サ", "moonbrooke": "ム"}

#: 役割・行動の1文字表示。⚠ 表に無いものは**そのまま**出す（上の説明）。
SHORT_ACTIONS = {
    "attack": "攻",
    "attack_spell": "呪",
    "heal": "回",
    "item": "道",
    "support": "補",
    "defend": "防",
    "manual": "手",
    # ★指示にあったが現行コードには無い。出てきたら短くなる。
    "status_spell": "状",
}

#: 戦況（`battle_balance`）。⚠ `unknown` を消さない（材料が無いと伝える）。
BALANCE_TEXT = {
    "advantage": "優勢", "even": "均衡", "disadvantage": "劣勢",
    "unknown": "⚠ 分からない",
}

#: ★「短期戦」→「短期」（表示だけ / 指示 §3.1）。内部値は `short` のまま。
LENGTH_TEXT = {"short": "短期", "medium": "中期", "long": "長期"}

#: 「届いていない」。⚠ 0 と混ぜない（測れていないことに気づけなくなる）。
DASH = "—"

#: `lorasia:attack(2.0)` の形。★`(?)` も拾う（点が付かないことがある）。
_ROLE_RE = re.compile(r"([A-Za-z_]+):([A-Za-z_]+)\(([^)]*)\)")


def short_actor_name(name) -> str:
    """`lorasia` → `ロ`。⚠ 知らない名前はそのまま返す。"""
    if name is None:
        return DASH
    return SHORT_ACTORS.get(str(name), str(name))


def short_action_name(action) -> str:
    """`attack` → `攻`。⚠ 知らない行動はそのまま返す（潰さない）。"""
    if action is None:
        return DASH
    return SHORT_ACTIONS.get(str(action), str(action))


def parse_roles(roles) -> list[tuple[str, str, str]]:
    """Lua が組んだ役割の1行を `(名前, 行動, 点)` へ分解する。

    ⚠⚠ **Lua 側の文字列を変えていません。** 画面のためにデータの形を
      変えると、ログと画面で別のものを見ることになります（指示 §17）。
      ★ここで読み取るだけにします。

    ⚠ 読めない部分は捨てます（★推測で補いません）。
    """
    if not roles:
        return []
    return [(m.group(1), m.group(2), m.group(3))
            for m in _ROLE_RE.finditer(str(roles))]


def format_assessment_row(balance, length, warn: bool = False) -> str:
    """1行目。`優勢・短期`（⚠ 「戦況」という語は見出しにあるので入れない）。"""
    if balance is None:
        return DASH
    text = BALANCE_TEXT.get(str(balance), str(balance))
    if length:
        text += "・" + LENGTH_TEXT.get(str(length), str(length))
    return text + (" ⚠" if warn else "")


def format_estimated_turn_row(win, lose) -> str:
    """2行目。`撃破 0.5T / 崩壊 4.2T`。

    ⚠ 片方しか出せないことがあります。★出せるものだけ出し、
      出せないほうは `—`（0 にしない）。
    """
    if win is None and lose is None:
        return DASH
    return "撃破 {} / 崩壊 {}".format(
        f"{win:.1f}T" if win is not None else DASH,
        f"{lose:.1f}T" if lose is not None else DASH)


def format_strategy_row(plan, score=None, margin=None,
                        warn: bool = False) -> str:
    """3行目。`戦術 省資源 5.5/+1.5`。

    ★次点との差は「この判断がどれくらい確からしいか」です。
      ⚠ 小さいなら次のターンに変わりうる、という意味なので消しません。
    """
    if plan is None:
        # ★戦況は取れたのに戦術が決まらない = 材料不足。⚠ 空欄にしない。
        return "戦術 ⚠ 決めていません"
    text = f"戦術 {plan}"
    if score is not None:
        text += f" {score:.1f}"
        if margin is not None:
            text += f"/+{margin:.1f}"
    return text + (" ⚠" if warn else "")


def format_role_row(roles, with_score: bool = True) -> str:
    """4行目。`役割 ロ:攻3.0 サ:道1.3 ム:道1.3`。

    ★`with_score=False` にすると `役割 ロ:攻 サ:道 ム:補`（戦闘後の要約用）。
    """
    parsed = parse_roles(roles)
    if not parsed:
        return f"役割 {DASH}"
    parts = []
    for name, action, score in parsed:
        piece = f"{short_actor_name(name)}:{short_action_name(action)}"
        if with_score and score not in ("", "?"):
            piece += score
        parts.append(piece)
    return "役割 " + " ".join(parts)


def roles_all_same(roles) -> bool:
    """★全員が同じ点なら、役割を**区別できていません**。

    ⚠ 実際 `attack(1.0)` が3人並んで「動いた」と誤認しかけました
      （攻撃力が読めていなかった）。★画面でも警告を出します。
    """
    scores = [s for _, _, s in parse_roles(roles) if s not in ("", "?")]
    return len(scores) >= 2 and len(set(scores)) == 1


def assessment_warnings(balance=None, win=None, lose=None, margin=None,
                        roles=None, tags=None) -> list[str]:
    """静かに保ちつつ、**見逃すと困るものだけ**を warn として返す（指示 §5）。

    ⚠ 依頼者の指示どおり、**新しい複雑な判定は作りません**。
      ★既にある値から素直に分かるものだけです。

    返すのは人が読む短い語の一覧（ツールチップ用）。
    """
    out: list[str] = []
    if balance == "disadvantage":
        out.append("劣勢")
    # ⚠⚠ 味方が先に崩れる見込み = いちばん見逃したくない形。
    if win is not None and lose is not None and lose < win:
        out.append("味方の崩壊が先")
    if margin is not None and margin < 0.5:
        out.append("戦術が僅差（次のターンに変わりうる）")
    if roles_all_same(roles):
        out.append("役割が全員同じ点（区別できていません）")
    if tags:
        out.append(str(tags))
    return out


def format_summary_rows(balance=None, length=None, win=None, lose=None,
                        plan=None, score=None, margin=None, roles=None,
                        tags=None) -> list[str]:
    """★戦況欄の4行を作る（指示 §4）。

    ⚠⚠ **横幅が無くても4行構造を崩しません**（指示 §4 の末尾）。
      ★1行へ戻すと、狭いときに黙って切れる元の状態に戻ります。
    """
    warns = assessment_warnings(balance, win, lose, margin, roles, tags)
    return [
        format_assessment_row(balance, length, warn=bool(warns)),
        format_estimated_turn_row(win, lose),
        format_strategy_row(plan, score, margin,
                            warn=margin is not None and margin < 0.5),
        format_role_row(roles),
    ]


#: 戦闘していないときの4行。⚠ `—` は「材料が無い」であって 0 ではない。
IDLE_ROWS = [f"{DASH}（戦闘中に出ます）", DASH, f"戦術 {DASH}", f"役割 {DASH}"]


#: ★ツールチップ先頭に出す「数字の意味」（2026-08-19 / RX-0068）。
#   ⚠ 初見では 撃破T/崩壊T/戦術/役割 の数字が何か分からないため、先頭に置く。
TOOLTIP_HELP = (
    "【見かた】\n"
    "撃破T=敵を全滅させるまでの推定ターン / 崩壊T=味方が崩れるまでの推定ターン\n"
    "　（崩壊 < 撃破 なら「味方が先に崩れる」＝危険）\n"
    "戦術=採用した戦い方。後ろの数字はスコア、/+ は次点との差（小さいほど僅差）\n"
    "役割 ロ=ローレシア サ=サマルトリア ム=ムーンブルク"
    "（攻=攻撃 補=補助 道=道具 …／後ろの数字は寄与）"
)

#: ★ツールチップに出すターン数（2026-08-19 / RX-0069）。
#   ⚠ 全ターン出すと大きくなりすぎるので上限を置く。
#   ★★ 依頼者（2026-08-19）:「今回の戦闘はなるべく複数ターン表示」。
#     → **今回の戦闘**は多め、**直前の戦闘**は控えめ。
RECENT_TURNS_CURRENT = 10
RECENT_TURNS_PREVIOUS = 3


def format_battle_review_tooltip(review, in_battle: bool,
                                 summary_rows=None) -> str:
    """★戦況欄のツールチップ＝**戦闘レビュー**（指示 §7・§8・§11）。

    戦闘中は「今回の戦闘」、終わったあとは「直前の戦闘」の全ターンを出します。

        今回の戦闘

        T1
        優勢・短期
        撃破 0.8T / 崩壊 4.5T
        戦術 通常速攻
        役割 ロ:攻3.0 サ:攻1.8 ム:補1.4
          ロ: attack
          サ: attack_spell
          ム: support

    ⚠⚠ **ログの丸写しにしません**（指示 §8 の末尾）。人が読む形に整えます。
    ⚠ 取れなかったものは書きません（★推測で埋めない）。

    ## ⚠ 指示から1つだけ変えています（`summary_rows`）

    ★先頭に**いま画面に出ている4行**を入れます。指示 §8 の例には
      ありませんが、2026-08-11 に依頼者から

          「戦況の行が切れて続きが見えない」

      という報告があり、★**切れた行の全文をツールチップで読む**という
      約束をここで守っています。⚠ 4行化で1行あたりは短くなりましたが、
      狭い窓では今後も切れます。
    """
    # ★数字の意味を先頭に（RX-0068）。⚠ 初見でも読めるように。
    #   ⚠ 2026-08-19: 「いまの戦況」の4行は**画面と被る**ので出さない（依頼者）。
    #     ★help のあとは、そのまま戦闘レビューへ。`summary_rows` は使わない。
    prefix = [TOOLTIP_HELP, "", "―" * 12, ""]

    if review is None or not review.turns:
        return "\n".join(prefix + [
            "今回の戦闘", "", "★まだ記録がありません。",
            "⚠ 倍速だと戦闘まるごとを画面が見逃すことがあります。"])

    head = "今回の戦闘" if in_battle else "直前の戦闘"
    if not in_battle:
        tail = []
        if review.result_label:
            tail.append(review.result_label)
        tail.append(f"{review.total_turns}ターン")
        head += "（" + " / ".join(tail) + "）"

    lines = prefix + [head]
    # ★ターン数の上限（RX-0069）。★今回の戦闘は多め・直前は控えめ（依頼者）。
    cap = RECENT_TURNS_CURRENT if in_battle else RECENT_TURNS_PREVIOUS
    recent = review.turns[-cap:]
    if len(review.turns) > cap:
        lines.append("")
        lines.append(f"（前略 — 直近 {cap} ターンのみ"
                     f" / 全 {len(review.turns)} ターン）")
    for turn in recent:
        lines.append("")
        lines.append(f"T{turn.turn_no}")
        lines.append(format_assessment_row(turn.balance, turn.length))
        lines.append(format_estimated_turn_row(
            turn.turns_to_win, turn.turns_to_lose))
        lines.append(format_strategy_row(
            turn.plan, turn.plan_score, turn.plan_margin))
        lines.append(format_role_row(turn.roles))
        for act in turn.actions:
            piece = (f"  {short_actor_name(act.get('name'))}: "
                     f"{act.get('action')}")
            if act.get("reason"):
                piece += f"（{act['reason']}）"
            lines.append(piece)
        # ★根拠はここへ（画面＝結果 / ツールチップ＝根拠 / 指示 §6）
        warns = assessment_warnings(turn.balance, turn.turns_to_win,
                                    turn.turns_to_lose, turn.plan_margin,
                                    turn.roles, turn.tags)
        for w in warns:
            lines.append(f"  ⚠ {w}")
        if turn.plan_reasons:
            lines.append(f"  理由: {turn.plan_reasons}")
    return "\n".join(lines)


def format_previous_rows(review) -> list[str]:
    """戦闘が終わったあとの4行（指示 §10）。

    ★★ **すぐ「—」へ戻しません。** ★★
      AUTO は戦闘が一瞬で終わるので、読む前に消えます。
      ⚠ 次の戦闘が始まるまで、直前の戦闘の結果を残します。

        直前 勝利 3T
        最終 優勢・短期
        戦術 省資源
        役割 ロ:攻 サ:道 ム:補

    ⚠ 勝敗は**分かるときだけ**書きます（`result` が無ければ書きません）。
      ★推測で「勝利」と書くと、逃げた戦闘まで勝ちに見えます。
    """
    if review is None or not review.turns:
        return list(IDLE_ROWS)
    last = review.turns[-1]
    head = "直前"
    if review.result_label:
        head += f" {review.result_label}"
    head += f" {review.total_turns}T"
    return [
        head,
        "最終 " + format_assessment_row(last.balance, last.length),
        format_strategy_row(last.plan),
        format_role_row(last.roles, with_score=False),
    ]
