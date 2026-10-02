"""画面から Lua へ頼む（RX3-0019 / 2026-08-29）。

★★ 向きに注意 ★★

    state.json         Lua → 画面（★いまの値）
    dq3-command.json   画面 → Lua（★頼みごと。ここ）

⚠ DQ2 も同じ形（`DEV-3` ファイル IPC）。

## ⚠⚠ Lua に JSON パーサは無い

★Lua 側は**必要な項目だけを正規表現で拾い**ます。
⚠ だから **1 行・素直な形**で書きます（ネストや余計な空白を増やさない）。

## ⚠ 同じ頼みを 2 回きかせない

★通し番号（`seq`）で見分けます。⚠ 「押されたボタンの名前」だけだと、
**同じボタンの 2 回目**を取りこぼします（DQ2 で踏んだ形）。
"""

from __future__ import annotations

import json
import pathlib

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_COMMAND = paths.lazy_work("dq3-command.json")

#: ★頼めること（⚠ Lua 側が知っている名前と揃えること）
#:   navigate / nav_stop は街ナビ（RX3-0058 / `dq3/phase0/nav_v0.lua`）
#:   load_state は開発用（★実機確認の driver がセーブを読むだけ / 書かない）
#:   walk_stop / screenshot は管理画面（RX3-0059）: 止めるだけ / ゲーム画面を撮る（証跡）
#:   town_end は街の自動操作の終わり（RX3-0170）: ★Turbo を切り、動いている nav / restock も止める
#:   save_state はパッドの RB（RX3-0486）: ★人のスロットへ保存（`dq3/phase0/human_state.lua`）
#:   ⚠ load_state はパッドの LB でも使う（★同じ入口 = `nav_v0.lua` / 止める・`HOST.loaded`）
ACTIONS = ("auto", "turbo", "mantan", "navigate", "nav_stop", "load_state", "walk", "walk_stop",
           "screenshot", "restock", "restock_stop", "ai_reload", "use_item", "town_end",
           "save_state")


class CommandWriter:
    """頼みごとを 1 行の JSON で書く。"""

    def __init__(self, path=None) -> None:
        self.path = pathlib.Path(path or DEFAULT_COMMAND)
        self.seq = self._last_seq()
        #: ★最後に書いた頼み（⚠ 同じ番号で書き直すために覚える / RX3-0130）
        self.last: tuple | None = None

    def _last_seq(self) -> int:
        """★前回の続きから数える。

        ⚠ 0 から数え直すと、Lua 側が「古い頼み」と見て**無視する**
        （★向こうは `seq <= 覚えている番号` を捨てる）。
        """
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return int(raw.get("seq", 0))
        except (OSError, ValueError, TypeError):
            return 0

    def send(self, action: str, **params) -> int:
        """★頼みを 1 つ書く。★`params` は文字列の項目として添える（⚠ Lua は `"key":"value"` だけ拾う）。"""
        if action not in ACTIONS:
            raise ValueError("⚠ 知らない頼み: %r（★%s のどれか）"
                             % (action, " / ".join(ACTIONS)))
        self.seq += 1
        return self._write(self.seq, action, params)

    def resend(self) -> int:
        """★★ 同じ頼みを**同じ番号のまま**書き直す（RX3-0130 / 2026-09-08）。

        ⚠⚠ 新しい番号にしてはいけません。★Lua は `seq <= 読んだ番号` を捨てるので、
        同じ番号なら**二重実行になりません**（★届いていなければ 1 回だけ効く）。
        """
        if self.last is None:
            raise ValueError("⚠ まだ 1 つも送っていません")
        action, params = self.last
        return self._write(self.seq, action, params)

    def _write(self, seq: int, action: str, params: dict) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = {"seq": seq, "action": action}
        for key, value in params.items():
            if value is None:
                continue
            text_value = str(value)
            if '"' in text_value or "\n" in text_value:
                raise ValueError("⚠ 引数に引用符や改行は入れられません: %s" % key)
            body[key] = text_value
        # ⚠ 1 行で書く（★Lua が正規表現で拾うため）
        text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        # ★一時ファイルへ書いてから置き換える（⚠ 読んでいる途中を見せない）
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(text, encoding="utf-8")
        try:
            tmp.replace(self.path)
        except OSError:
            # ⚠ 置き換えられなくても落ちない（★次の押しでやり直せる）
            self.path.write_text(text, encoding="utf-8")
        self.last = (action, dict(params))
        return seq
