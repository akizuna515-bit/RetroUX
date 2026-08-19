"""選んだ戦術プロフィールを Lua へ渡す（2026-07-30 / 仕様書 15.3）。

★★ **判断は Lua、設定は Python。** ★★
  戦闘の判断は実時間なので `bridge.lua` に閉じている（D-1）。
  だから設定を Lua が読める形にして渡すしかない。

## 渡し方（既存のやり方に合わせる）

    config.yaml   -> work/generated/config.lua    （起動時に読む）
    プロフィール  -> work/generated/tactics.lua   ← ここ

★`config.lua` と同じ「Lua のテーブルを返すファイル」にする。
  すでに `generate_lua.py` が同じ形を作っているので、変換はそれを使う。

## 切り替えをどう伝えるか

⚠ 起動時に1度読むだけでは、画面でプロフィールを変えても効かない。
→ ファイルに **`revision`**（書いた時刻）を入れ、`command.json` にも同じ値を入れる。
  Lua は 30 フレームごとに `command.json` を見ているので、
  値が変わったら `tactics.lua` を読み直す。

★★ **反映は「次のターンから」**（仕様書 15.3 の推奨）★★
  戦闘の途中で設定が入れ替わると、同じターンの中で
  前半と後半が別の戦術で動く。**その挙動は説明できない。**

## ⚠ プロフィールが無い環境では何も変えない

`tactics.lua` が無ければ Lua はこれまでどおり `config.yaml` の値だけで動く。
「入れたら壊れた」を起こさないための線（仕様書 2.4）。
"""

from __future__ import annotations

import pathlib
import time

#: 生成物の置き場（`config.lua` と同じ）
DEFAULT_PATH = pathlib.Path("work/generated/tactics.lua")

HEADER = """-- 自動生成ファイル。直接編集しないこと。
-- 生成元: 選んでいる戦術プロフィール（work/tactics/profiles/*.yaml）
-- 生成: retroux/core/tactics/lua_bridge.py
--
-- ★★ **これは「利用者が設計した戦術」。** ★★
--   bridge.lua は、この表をキャラクターごとに引いて判断する。
--   ここに無い項目は config.yaml の値をそのまま使う（これまでの挙動）。
--
-- ⚠ `revision` が変わったら Lua は読み直す（画面で切り替えたとき）。
--   反映は**次のターンから**（戦闘の途中で戦術が入れ替わらないように）。
"""


def revision() -> int:
    """いまの版。★単調増加すればよい（ミリ秒）。

    ⚠ 内容のハッシュにしない。「同じ内容に戻した」ときに
      値が戻り、Lua が「変わっていない」と判断してしまう。
    """
    return int(time.time() * 1000)


def to_lua_table(payload: dict, indent: int = 0) -> str:
    """Python の値を Lua のリテラルへ。★`generate_lua.py` のものを使う。

    ⚠ 同じ変換を2つ書かない（片方だけ直したときに黙って食い違う /
      playbook「順番や対応の表は写さない」）。
    """
    from ..config.generate_lua import to_lua

    return to_lua(payload, indent)


def render(prof, rev: int | None = None, mission=None, strategy=None) -> str:
    """プロフィールから `tactics.lua` の中身を作る。

    `mission` … 大目的（`core/mission` の `MissionSettings`）。
    `strategy` … いま有効な戦略の目印（2026-08-11 / UI整理 Phase 4）。
      ★`{"id": "custom_1", "type": "fixed"}` のような辞書。⚠ 固定行動の
        **中身**は config.lua の `user_strategies` にあるので、ここでは
        「どれが有効か」だけを渡す（薄い被せもの）。None なら通常のAI。

    ★★ **大目的も同じファイルに載せます**（2026-08-05 / Phase 3）★★
      ⚠ 別ファイルにすると、版の管理と読み直しの仕組みが**もう1組**要ります。
        `tactics.lua` は既に 30 フレームごとの読み直しが通っているので、
        そこへ相乗りさせます。
      ★大目的と戦術は**別のもの**です（§5「大目的から戦術を直接固定しない」）。
        同じ便に乗せるだけで、意味は混ぜていません。
    """
    payload = prof.for_ai()
    payload["revision"] = rev if rev is not None else revision()
    if mission is not None:
        payload["mission"] = mission.to_lua_dict()
    if strategy is not None:
        payload["strategy"] = strategy
    return (HEADER
            + f"local DATA = {to_lua_table(payload)}\n"
            + "return DATA\n")


def write(prof, path=None, rev: int | None = None, mission=None,
          strategy=None) -> int | None:
    """`tactics.lua` を書く。戻り値は書いた `revision`（失敗なら None）。

    ★**一時ファイル経由で置き換える。** Lua が 30 フレームごとに読むので、
      書きかけを掴まれると**その瞬間だけ戦術が消える**。
    """
    target = pathlib.Path(path or DEFAULT_PATH)
    rev = rev if rev is not None else revision()
    body = render(prof, rev, mission, strategy)
    temp = target.with_suffix(target.suffix + ".tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(body, encoding="utf-8")
        # ★「書いた」と「書けた」は別。読み直して確かめる
        if temp.read_text(encoding="utf-8") != body:
            temp.unlink(missing_ok=True)
            return None
        import os

        os.replace(temp, target)
        return rev
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def clear(path=None) -> bool:
    """`tactics.lua` を消す（プロフィールを使わない状態に戻す）。

    ★消すと Lua は `config.yaml` の値だけで動く＝**これまでの挙動**。
    """
    target = pathlib.Path(path or DEFAULT_PATH)
    try:
        target.unlink(missing_ok=True)
        return True
    except OSError:
        return False
