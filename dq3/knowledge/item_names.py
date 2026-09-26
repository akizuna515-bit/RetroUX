"""見たアイテムの名前を覚える（RX3-0041 / 2026-09-01）。

★敵の名前（`dq3/knowledge/enemies_seen.py`）と**同じ仕組み**です。

## ⚠⚠ なぜ ROM から読まないのか

★`docs/00-project-policy.md` §3「原作テキストを同梱しない」。
⚠ そのうえ DQ3 の ROM テキストは**圧縮**されていて、素のかな列がありません
（`RX3-0013` の実測）。→ ★**画面から読む**のが唯一の道です。

## ★覚え方（⚠ 敵の名前と同じ「ずれたら覚えない」）

```text
RAM の袋（$077C）    → 品の ID が**並び順**で分かる
どうぐ画面のタイル    → 名前が**同じ並び順**で読める
        ↓ 数が合うときだけ
ID → 名前 を覚える
```

⚠⚠ **数が合わないときは 1 つも覚えません。** ★ずれたまま覚えると、
別の品の名前が付きます（敵の名前で同じ守り方をしています）。

## ⚠ 画面の読み取りは、まだ繋いでいません

★`learn()` は「ID の並び」と「名前の並び」を受け取る形にしてあります。
⚠ どうぐ画面のどこに名前が出るかは**実機で見ないと決められない**ので、
そこは `RX3-0041` の残件です（★この仕組み自体は先に置きます）。
"""

from __future__ import annotations

import json
import pathlib

from .. import paths

#: ★覚えた名前の置き場（⚠ `work/` は Git の外 ＝ 成果物に焼かれない）
DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "item-names.json")


def _tidy(text) -> str:
    """⚠ 端の空白と、読めなかった印を落とす。"""
    return str(text or "").strip().strip("　")


class ItemNames:
    """★見た品の名前を覚えておく（⚠ 番号 → 名前）。"""

    def __init__(self, path=None) -> None:
        self.path = pathlib.Path(path) if path is not None else DEFAULT_PATH
        self.names: dict[int, str] = {}
        self.last_error: str | None = None
        self._dirty = False

    # --- ★覚える ---------------------------------------------------------

    def learn(self, item_ids, names) -> int:
        """★並び順で対応づけて覚える。⚠ 覚えた数を返す。

        ⚠⚠ **数が合わなければ 1 つも覚えません**（★ずれ防止）。
        """
        ids = [i for i in (item_ids or []) if i is not None]
        got_names = [_tidy(n) for n in (names or [])]
        if not ids or len(ids) != len(got_names):
            return 0
        if any(not n for n in got_names):
            return 0                       # ⚠ 1 つでも読めなければ見送る
        added = 0
        for item_id, name in zip(ids, got_names):
            key = int(item_id) & 0x7F
            if self.names.get(key) != name:
                self.names[key] = name
                self._dirty = True
                added += 1
        return added

    def label(self, item_id) -> str:
        """★画面に出す 1 行。⚠ 知らなければ**知らないと分かる形**で。"""
        from dq3rom import items as it

        if item_id is None:
            return it.label_of(None)
        from dq3.knowledge import rom_names

        # ★ROM の品名を先に（primary / RX3-0069 §8）→ ⚠ ROM が無ければ画面で読めた品名
        return it.label_of(item_id, rom_names.item(item_id) or self.names.get(int(item_id) & 0x7F))

    def knows(self, item_id) -> bool:
        return item_id is not None and (int(item_id) & 0x7F) in self.names

    # --- ★しまう・戻す ---------------------------------------------------

    def save(self, force: bool = False) -> bool:
        """⚠ 一時ファイルへ書いて置き換える（★読んでいる途中の欠けを避ける）。"""
        if not force and not self._dirty:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "game": "dq3",
                "names": {str(k): v for k, v in sorted(self.names.items())},
            }, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            self.last_error = str(exc)     # ⚠ 落とさない（★遊びを止めない）
            return False
        self._dirty = False
        return True

    @classmethod
    def load(cls, path=None) -> "ItemNames":
        got = cls(path)
        try:
            data = json.loads(got.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return got                     # ⚠ 無ければ空で始める
        for key, name in (data.get("names") or {}).items():
            try:
                got.names[int(key)] = str(name)
            except (TypeError, ValueError):
                continue                   # pragma: no cover
        return got
