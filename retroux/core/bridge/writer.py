"""command.json を書く（Python -> Lua）。

ファイルベースIPC（D-3 / DEV-3）の書き側。Lua 側は 30 フレームごとに
このファイルをポーリングする。

Lua は完全な JSON パーサを持たず、必要なフィールドだけを正規表現で拾う。
そのため **1行・素直な形** で書く（ネストや余計な空白を増やさない）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable


def write_command(path: Path | str, *, encountered: Iterable[int],
                  battle_multiplier: float | None = None,
                  action: str | None = None,
                  request_id: int | None = None,
                  reset_encountered: bool = False,
                  mantan_mode: str | None = None,
                  save_slot: int | None = None,
                  tactics_revision: int | None = None,
                  turbo_enabled: bool | None = None,
                  auto_enabled: bool | None = None) -> None:
    """遭遇済みIDと倍率、単発の操作要求を Lua へ渡す。

    書き込みは一時ファイル経由の置換で行う。Lua 側が読んでいる最中に
    半端な内容を掴むのを避けるため。

    encountered は Lua 側の集合に**合併**される（上書きではない）。
    Lua は戦闘開始の瞬間に登録するのに対し、こちらは events.jsonl の
    取り込みを経てから DB に入るため常に遅れうる。上書きすると Lua の
    登録が消え、同じモンスターが何度も「初遭遇」になって自動入力が
    無効化され続ける（実際にドラキー・アイアンアントで発生した）。

    意図的に忘れさせたい場合だけ reset_encountered=True を渡す。
    Lua 側はリセットしてから encountered を取り込む。

    action は「まんたん」のような単発操作の要求。
    **request_id を必ず添えること。** command.json は消えずに残るため、
    Lua 側は request_id が前回と同じなら無視する。これが無いと
    30フレームごとに同じ操作を繰り返し、やくそうを使い切ってしまう。
    request_id を省略した場合はここで単調増加する値（現在時刻）を入れる。
    """
    # ★★ **書かなかった項目を消さない**（2026-07-30 / P-3 の原因）★★
    #
    #   `command.json` は**複数の書き手が共有する状態ファイル**である。
    #   それなのに毎回 payload を作り直していたので、
    #   `encountered` だけを渡す `Recorder.push_encountered()` が
    #   **`action` と `request_id` を消していた**。
    #
    #   ⚠⚠ しかも自己破壊的だった。保存を待つループがこうなっていた:
    #       while 期限内:
    #           recorder.poll()      # ← イベントが1件でもあれば push_encountered()
    #                                #    が走り、待っている action を消す
    #   Lua は 30 フレーム（0.5秒）ごとに読むので、その前に消えると
    #   **保存が実行されないまま5秒待って諦める**。
    #   実機で「保存して終了 → スロット1 に古い状態しか無い」が起きた。
    #
    # ★だから既にある内容を読んで、**渡された項目だけを更新**する。
    #   ⚠ `reset_encountered` は**引き継がない**（一度きりの指示。
    #     Lua 側は毎ポーリングで見るので、残すと延々リセットしてしまう）。
    keep = ("battle_multiplier", "mantan_mode", "save_slot",
            "tactics_revision", "action", "request_id", "turbo_enabled",
            # ★AUTO と 高速化 は独立した2軸。片方を書いたときに
            #   もう片方を巻き添えで消さないよう、両方とも残す。
            "auto_enabled")
    payload: dict[str, object] = {}
    try:
        existing = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            payload.update({k: v for k, v in existing.items() if k in keep})
    except (OSError, ValueError):
        # ⚠ 読めなくても書き込みは続ける（初回は存在しない）
        pass
    payload["encountered"] = sorted({int(i) for i in encountered})
    if battle_multiplier is not None:
        payload["battle_multiplier"] = float(battle_multiplier)
    if reset_encountered:
        # Lua 側は '"reset_encountered"%s*:%s*true' を探すため小文字の true で書く
        payload["reset_encountered"] = True
    if mantan_mode is not None:
        # まんたんの回復目標モード（config の mantan.modes のキー）。
        # ★モード名だけを渡す。割合そのものを渡さないのは、
        #   画面に出す名前と実際の挙動をずれさせないため。
        payload["mantan_mode"] = str(mantan_mode)
    if save_slot is not None:
        # ★セーブステートの保存先スロット（action="save_state" と一緒に使う）。
        #   Lua 側は '"save_slot"%s*:%s*(%d+)' で拾う。
        payload["save_slot"] = int(save_slot)
    if tactics_revision is not None:
        # ★戦術プロフィールの版（2026-07-30 / 仕様書 15.3）。
        #   値が変わったら Lua が `work/generated/tactics.lua` を読み直す。
        #   ⚠ 効かせるのは**次の戦闘から**（Lua 側で戦闘の始まりに固定する）。
        #   Lua 側は '"tactics_revision"%s*:%s*(%d+)' で拾うため整数で書く。
        payload["tactics_revision"] = int(tactics_revision)
    if turbo_enabled is not None:
        # ★戦闘の倍速の入切（2026-07-31）。状態の変更なので request_id は要らない。
        #   ⚠ Lua は '"turbo_enabled"%s*:%s*(%a+)' で拾うため true/false で書く。
        payload["turbo_enabled"] = bool(turbo_enabled)
    if auto_enabled is not None:
        # ★AUTO（誰が操作するか）。⚠ 速度とは別の軸なので別のキーで持つ。
        payload["auto_enabled"] = bool(auto_enabled)
    if action is not None:
        payload["action"] = str(action)
        # Lua 側は '"request_id"%s*:%s*(%d+)' で拾うため整数で書く
        payload["request_id"] = int(request_id if request_id is not None
                                    else time.time() * 1000)

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
