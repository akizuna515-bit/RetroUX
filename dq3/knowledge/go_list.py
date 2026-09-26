"""「行ってみる？」— 人が勇者メモから選んだ、まだ消化していない探索候補（RX3-0310 / 2026-09-20）。

依頼者の指示（2026-09-20）:

```text
会話・発見 → 勇者メモ → 行ってみる？ → 探索・確認 → 完了
```

## ★勇者メモとは分ける

```text
勇者メモ     ★過去を含む「記録」（⚠ 足しても消しても、元のメモは変えない）
行ってみる？ ★人が選んだ「未消化の行動候補」（★DONE になると一覧から消える）
```

⚠⚠ **AI が自動で候補を大量に作りません**（★依頼者「初探索は人間」）。
★人が本文の一部を選び、`add()` で足します。

## ⚠ 既にある「行ってみる？」とは別物

★勇者会議の 1 行（`reachable.collect`）は、⚠ **毎回計算する派生リスト**です
（★保存しない・id が無い・DONE が無い）。⚠ あちらの No-Spoiler の濾し器には触りません。

## ★消すのではなく DONE にする

⚠ 物理削除はしません（★依頼者 §11）。`status` を `DONE` にし、`completed_at` を入れます。

## ★元のメモへの参照を失わない（依頼者 §13）

`source_memo_id` は勇者メモの `order`（通し番号）です。

⚠⚠ ただし **`order` は identity として完全ではありません**（★実測 2026-09-20）:

```text
⚠ 本番の memos.jsonl に同じ order が 2 組ある（424 / 703）
⚠ 場所ごとの会話メモは消せる（`MemoStore.remove_conversations` / RX3-0235）
⚠ 同じ台詞は読み込みで畳まれ、表示に出ない（`_fold` / RX3-0294）
```

→ ★だから `display_text` を**実体として持ちます**。⚠ 元のメモが消えても項目は生き残ります。
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import pathlib

from .. import paths

#: ★状態（⚠ 初版はこの 2 つだけ / 依頼者 §5）
ACTIVE = "ACTIVE"
DONE = "DONE"
STATUSES = (ACTIVE, DONE)

FORMAT_VERSION = 1


def default_path() -> pathlib.Path:
    """★保存先（⚠ 関数にする。★import のときに固めると、隔離先へ切り替えても本物に書く / RX3-0215）。"""
    return paths.work("dq3-knowledge", "go-list.json")


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


@dataclasses.dataclass
class GoItem:
    """★「行ってみる？」1 件。"""

    id: str
    display_text: str
    source_memo_id: int | None = None
    source_location_id: str | None = None
    target_location_id: str | None = None
    created_at: str = ""
    status: str = ACTIVE
    completed_at: str | None = None

    @property
    def active(self) -> bool:
        return self.status == ACTIVE

    def as_json(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_json(cls, row: dict) -> "GoItem":
        got = cls(
            id=str(row["id"]),
            display_text=str(row.get("display_text") or ""),
            source_memo_id=_int_or_none(row.get("source_memo_id")),
            source_location_id=_str_or_none(row.get("source_location_id")),
            target_location_id=_str_or_none(row.get("target_location_id")),
            created_at=str(row.get("created_at") or ""),
            status=str(row.get("status") or ACTIVE),
            completed_at=_str_or_none(row.get("completed_at")),
        )
        if got.status not in STATUSES:                 # ⚠ 知らない状態は ACTIVE に寄せる
            got.status = ACTIVE
        return got


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _str_or_none(v):
    return str(v) if isinstance(v, str) and v else None


#: ★表示できる字数の上限（⚠ 長い選択をそのまま台帳に入れない）
MAX_TEXT = 200


def clean_text(text: str) -> str:
    """★選んだ文を 1 行に整える（⚠ 改行・前後の空白・かぎかっこの頭を落とす）。"""
    body = " ".join(str(text or "").split())
    for head in ("＊「", "「"):
        if body.startswith(head):
            body = body[len(head):]
            break
    return body[:MAX_TEXT]


class GoList:
    """★「行ってみる？」の台帳（⚠ 画面はここを通して読み書きする）。"""

    def __init__(self, path=None) -> None:
        self.path = pathlib.Path(path) if path is not None else default_path()
        self.items: dict[str, GoItem] = {}
        #: ★★ 自動で出た「行ってみる？」のうち、人が「もう済んだ」と言ったもの（RX3-0313）
        #:
        #:   ⚠⚠ 依頼者「勇者会議 行ってみるで既に完了している部分は…消し込みたい」。
        #:   ★自動の分（`reachable.collect`）は**毎回計算する派生**なので、⚠ 状態を持てません。
        #:   → ★「消した」という**人の判断だけ**をここに置き、⚠ 出すときに省きます。
        #:   ⚠ 中身は場所の id（`L9` など）。★名前しか無い行は消せません（後述）。
        self.dismissed: set[str] = set()
        self._dirty = False
        self.failed = 0
        self.last_error = ""

    # --- ★自動で出た分の消し込み（RX3-0313）--------------------------------

    def dismiss(self, location_id) -> bool:
        """★その場所を「もう済んだ」ことにする（⚠ 記録は消さない / 戻せる）。"""
        key = _str_or_none(location_id)
        if key is None or key in self.dismissed:
            return False
        self.dismissed.add(key)
        self._dirty = True
        return True

    def restore(self, location_id) -> bool:
        """⚠ 間違えて消したとき（★また出るようになる）。"""
        key = _str_or_none(location_id)
        if key is None or key not in self.dismissed:
            return False
        self.dismissed.discard(key)
        self._dirty = True
        return True

    def is_dismissed(self, location_id) -> bool:
        key = _str_or_none(location_id)
        return key is not None and key in self.dismissed

    def keep_rows(self, rows) -> list:
        """★消し込んでいない分だけ返す（⚠ `location_id` が無い行はそのまま残す）。

        ⚠⚠ 名前しか無い行（`location_id is None`）は**消せません**。
        ★消した印を場所の id で持つので、⚠ 同じ名前の別の場所を巻き込まないためです。
        """
        return [r for r in rows or ()
                if not self.is_dismissed(getattr(r, "location_id", None))]

    def dropped_rows(self, rows) -> list:
        """⚠ 消し込んだ分（★「済んだ分も見る」で出す）。"""
        return [r for r in rows or ()
                if self.is_dismissed(getattr(r, "location_id", None))]

    # --- ★足す・終える -----------------------------------------------------

    def next_id(self) -> str:
        n = 0
        for key in self.items:
            if key.startswith("go"):
                try:
                    n = max(n, int(key[2:]))
                except ValueError:
                    continue
        return "go%04d" % (n + 1)

    def add(self, text: str, *, source_memo_id=None, source_location_id=None,
            target_location_id=None) -> GoItem | None:
        """★1 件足す。⚠ 空文は足さない。★同じ文が ACTIVE で居れば足さない（既存を返す）。"""
        body = clean_text(text)
        if not body:
            return None
        for got in self.items.values():
            if got.active and got.display_text == body:
                return got                              # ⚠ 同じ文を二重に並べない
        made = GoItem(id=self.next_id(), display_text=body,
                      source_memo_id=_int_or_none(source_memo_id),
                      source_location_id=_str_or_none(source_location_id),
                      target_location_id=_str_or_none(target_location_id),
                      created_at=_now())
        self.items[made.id] = made
        self._dirty = True
        return made

    def edit(self, item_id: str, text: str) -> bool:
        """★あとから文を直す（RX3-0317 / 2026-09-20）。

        ⚠⚠ 依頼者「メモの一部を選択したいが、メモを全部追加しか出来ない
          → 全部追加してから、メンテできる機能があってもいい」。

        ★出典（`source_memo_id` / `source_location_id`）は**そのまま**です
        （⚠ 元の勇者メモへ戻れなくならないように）。
        """
        got = self.items.get(str(item_id))
        if got is None:
            return False
        body = clean_text(text)
        if not body or body == got.display_text:
            return False                            # ⚠ 空にはしない（★消す道は DONE）
        got.display_text = body
        self._dirty = True
        return True

    def complete(self, item_id: str) -> bool:
        """★「行った」。⚠ 消さずに `DONE` にする（依頼者 §11）。"""
        got = self.items.get(str(item_id))
        if got is None or not got.active:
            return False
        got.status, got.completed_at = DONE, _now()
        self._dirty = True
        return True

    def reopen(self, item_id: str) -> bool:
        """⚠ 間違えて終えたとき（★`completed_at` も外す）。"""
        got = self.items.get(str(item_id))
        if got is None or got.active:
            return False
        got.status, got.completed_at = ACTIVE, None
        self._dirty = True
        return True

    def complete_arrival(self, location_id: str) -> list[GoItem]:
        """★その場所へ着いたので終わる分（⚠ `target_location_id` が入っている分だけ）。

        ⚠⚠ 行き先の決まっていない項目（`target_location_id` が `None`）は**終えません**
        （★依頼者 §7「無理に Location へ紐付けない。手動完了で閉じられればよい」）。
        """
        key = _str_or_none(location_id)
        if key is None:
            return []
        out = []
        for got in self.items.values():
            if got.active and got.target_location_id == key:
                got.status, got.completed_at = DONE, _now()
                out.append(got)
        if out:
            self._dirty = True
        return out

    def set_target(self, item_id: str, location_id) -> bool:
        """★後から行き先を結び付ける（⚠ 初版は自動で推し量らない / 依頼者 §7）。"""
        got = self.items.get(str(item_id))
        if got is None:
            return False
        want = _str_or_none(location_id)
        if got.target_location_id == want:
            return False
        got.target_location_id = want
        self._dirty = True
        return True

    # --- ★出す -------------------------------------------------------------

    def active_items(self) -> list[GoItem]:
        """★まだ行っていない分（★古い順 = 足した順）。"""
        return [v for _k, v in sorted(self.items.items()) if v.active]

    def done_items(self) -> list[GoItem]:
        return [v for _k, v in sorted(self.items.items()) if not v.active]

    # --- ★読み書き（★宝箱の台帳と同じ作法 / chest_book.py）------------------

    def to_dict(self) -> dict:
        return {"game": "dq3", "format_version": FORMAT_VERSION,
                "items": {k: v.as_json() for k, v in sorted(self.items.items())},
                "dismissed": sorted(self.dismissed)}

    @classmethod
    def from_dict(cls, data: dict, path=None) -> "GoList":
        got = cls(path)
        got.dismissed = {str(x) for x in ((data or {}).get("dismissed") or []) if x}
        rows = (data or {}).get("items") or {}
        if isinstance(rows, list):                      # ⚠ 一覧で書かれていても読む
            rows = {str(r.get("id")): r for r in rows if isinstance(r, dict) and r.get("id")}
        for key, row in rows.items():
            if not isinstance(row, dict):
                got.failed += 1
                got.last_error = "壊れた記録: %s" % key
                continue
            row = dict(row)
            row.setdefault("id", key)
            try:
                got.items[str(row["id"])] = GoItem.from_json(row)
            except (KeyError, TypeError, ValueError):   # ⚠ 1 件壊れても残りは読む
                got.failed += 1
                got.last_error = "壊れた記録: %s" % key
        return got

    @classmethod
    def load(cls, path=None) -> "GoList":
        target = pathlib.Path(path) if path is not None else default_path()
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(target)
        return cls.from_dict(data, target)

    def save(self, force: bool = False) -> bool:
        """★書き出す（⚠ 変わっていなければ何もしない / 一時ファイルから置き換える）。"""
        if not force and not self._dirty:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            self.failed += 1                            # ⚠ 黙って捨てない
            self.last_error = str(exc)
            return False
        self._dirty = False
        return True


__all__ = ["ACTIVE", "DONE", "STATUSES", "GoItem", "GoList", "clean_text",
           "default_path", "FORMAT_VERSION"]
