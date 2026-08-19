"""人が読む形に整える（時間の表示など）。

★このプロジェクトの中心指標は「削減できた待ち時間」なので、
  そこが `31285.7 秒` のままでは**どれだけ効いているのか実感できない**。
  8時間41分25秒 と出れば一目で分かる（依頼者の指摘 / 2026-07-26）。

Qt に依存しない。GUI と CLI の両方が同じ関数を使う。
"""

from __future__ import annotations


def duration(seconds: float, *, decimals: int = 1) -> str:
    """秒数を「x時間x分x秒」にする。

    ★桁を上げるほど「秒」の細かさは要らなくなる。

        45.2 秒       -> 45.2秒        （短いので小数まで見える意味がある）
        312 秒        -> 5分12秒       （分が出たら秒の小数は邪魔）
        31285.7 秒    -> 8時間41分25秒

    ★0 は「0秒」。空文字や「-」にしない。
      **数字が入る場所を空にすると、壊れているのか0なのか区別できない。**
    """
    if seconds is None:                       # 呼び出し側の nil を素通しさせない
        return "-"
    negative = seconds < 0
    total = abs(float(seconds))

    if total < 60:
        text = f"{total:.{decimals}f}秒"
    else:
        whole = int(total)                    # 分以上が出るなら秒は整数でよい
        hours, rest = divmod(whole, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            text = f"{hours}時間{minutes}分{secs}秒"
        else:
            text = f"{minutes}分{secs}秒"

    return ("-" + text) if negative else text


def compact_duration(seconds: float) -> str:
    """表の狭い列に入れる短い形（`1h02m` / `5m12s` / `45.2s`）。

    ★戦闘ログの1行あたりの値は短いので、こちらは記号のまま。
      日本語にすると列幅を食い、モンスター名を押し出してしまう。
    """
    if seconds is None:
        return "-"
    negative = seconds < 0
    total = abs(float(seconds))

    if total < 60:
        text = f"{total:.1f}s"
    else:
        whole = int(total)
        hours, rest = divmod(whole, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            text = f"{hours}h{minutes:02d}m"
        else:
            text = f"{minutes}m{secs:02d}s"

    return ("-" + text) if negative else text
