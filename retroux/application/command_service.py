"""エミュレータへの指示を組み立てて渡す（指示書 §5.2「command_service」）。

★★ **画面は JSON の形を知らない。** ★★

    画面: 「AUTO を入れて」
      ↓
    CommandService: request_id を採番し、形を整え、原子的に書く
      ↓
    command.json
      ↓
    Lua

⚠⚠ **なぜ画面から直接書かせないか**

  `main_window.py` が `write_command(...)` を直に呼んでいた（Phase 0 で確認）。
  そのため:
    ・`request_id` の採番規則が呼ぶ側に散らばる
    ・書き込みの失敗をボタンごとに処理することになる
    ・JSON のキー名を画面が知っている＝**契約が2か所にある**

  ★ここを通せば、契約の変更は**このファイルだけ**で済む。

## 状態の指示と、一度きりの指示

  | 種類 | 例 | `request_id` |
  | --- | --- | --- |
  | **状態** | AUTO を入れる / 高速化を切る | 要らない（同じ値が続いても害がない） |
  | **一度きり** | セーブする / まんたん | **要る**（command.json は消えないため） |

  ⚠ 一度きりの指示に `request_id` が無いと、Lua が巡回のたびに
    **同じ操作を何度も実行する**。
"""

from __future__ import annotations

import dataclasses
import itertools
import pathlib
import time
from typing import Any

#: 一度きりの指示に付ける通し番号。★プロセス内で必ず増える。
#
# ⚠ 時刻（秒）だけだと、**同じ秒に2回**押されたとき同じ値になり、
#   2回目が「もう処理した」と無視される。時刻＋連番にする。
_counter = itertools.count(1)


def next_request_id() -> int:
    return int(time.time() * 1000) * 1000 + (next(_counter) % 1000)


@dataclasses.dataclass(frozen=True)
class EmulatorCommand:
    """エミュレータへの1つの指示（指示書 §5.2）。"""

    action: str = ""
    payload: dict = dataclasses.field(default_factory=dict)
    request_id: int | None = None


class CommandService:
    """`command.json` への書き込みを一手に引き受ける。

    ★依存は**コンストラクタで注入**する（指示書 §18）。
      ⚠ 中でグローバルを掴むと、テストが本物のファイルを触ることになる。
    """

    def __init__(self, command_path, encountered=None, read_only: bool = False,
                 logger=None) -> None:
        self.command_path = pathlib.Path(command_path)
        #: いま出会っている敵を渡すための取り出し口（呼ぶたびに評価する）
        self._encountered = encountered or (lambda: [])
        self.read_only = bool(read_only)
        self._log = logger
        #: 最後に書いた内容（診断・テスト用）
        self.last: EmulatorCommand | None = None

    # --- 状態の指示 -------------------------------------------------

    def set_auto(self, enabled: bool):
        """AUTO（誰が操作するか）を切り替える。"""
        return self._write("AUTO", auto_enabled=bool(enabled))

    def set_turbo(self, enabled: bool):
        """高速化（どの速度で動かすか）を切り替える。

        ⚠ AUTO には触らない（2026-07-31 の指示書 §2.1 の不変条件）。
        """
        return self._write("高速化", turbo_enabled=bool(enabled))

    def set_tactics_revision(self, revision: int):
        return self._write("戦術プロフィール",
                           tactics_revision=int(revision))

    # --- 一度きりの指示 ---------------------------------------------

    def request(self, action: str, **payload):
        """一度きりの操作を頼む。★`request_id` はここが採番する。"""
        return self._write(action or "操作", action=action,
                           request_id=next_request_id(), **payload)

    def save_state(self, slot: int):
        """セーブステートの保存を頼む。"""
        return self.request("save_state", save_slot=int(slot))

    def load_state(self, slot: int):
        """セーブステートの読み込みを頼む（★ゲームパッドの LB など）。

        ⚠ 保存と対で使う（同じ slot）。読み込みは**入力を伴わない**ので、
          Lua 側は `_load_state` で即座に `savestate.load` する。
        """
        return self.request("load_state", save_slot=int(slot))

    # --- 中身 -------------------------------------------------------

    def _write(self, label: str, **fields):
        """戻り値は**失敗の理由**（成功なら None）。

        ⚠ 閲覧専用のときは書かない。**黙って無視しない**（理由を返す）。
        """
        if self.read_only:
            return f"閲覧専用なので{label}は変えられません"
        try:
            from ..core.bridge.writer import write_command

            write_command(self.command_path,
                          encountered=self._encountered() or [], **fields)
        except Exception as exc:                       # noqa: BLE001
            if self._log is not None:
                self._log.warning("command を書けません（%s）: %s", label, exc)
            # ⚠ 書けなかったときは**元の状態のまま**（指示書 §15.2）
            return f"{label}を変えられません: {exc}"
        self.last = EmulatorCommand(
            action=str(fields.get("action") or ""),
            payload={k: v for k, v in fields.items()
                     if k not in ("action", "request_id")},
            request_id=fields.get("request_id"))
        return None
