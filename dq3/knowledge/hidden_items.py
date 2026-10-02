"""「しらべる」で手に入れた隠し道具を覚える（RX3-0281 / 2026-09-18）。

★依頼者（2026-09-18）「いのちのきのみを見つける前（save1）でまちから隠しアイテム手に入れたが、勇者メモに追加されない」。
⚠ 宝箱は残る（`chest_book` / RX3-0261）のに、★しらべるの升は**別の表**なので拾えていなかった。

```text
升     `dq3rom.search_spots`（bank12 $9ECF / 27 升 / うち道具 8）★map / x / y / 品番
印     `dq3rom.chest_flags`（WRAM $608E〜 の同じ並び）★通し番号 200〜207 = 隠し道具
渡し   Lua の `state.json` の `chest_bits`（★26 バイト目に 200〜207 / `dev.lua`）
```

## ⚠⚠ 「前から取ってあった分」をメモに流さない

★初めて印を見たとき、既に立っているものは `before_seen` として**黙って**覚えます（メモにしない）。
⚠ そのあと新しく立ったものだけが「いま取った」です（★宝箱の `opened_before_seen` と同じ考え）。

## ⚠ セーブを読み直しても増えない

★一度覚えた通し番号は記録に残ります（⚠ 印が 0 に戻っても消しません / RX3-0167 と同じ）。
→ ★同じ升で 2 度メモが出ることはありません。
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib

from .. import paths

#: ★保存先（⚠ `work/` は Git の外）
DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "hidden-items.json")
FORMAT_VERSION = 1


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def taken_serials(bits_hex) -> list[int] | None:
    """★`chest_bits`（16 進）→ 取った隠し道具の通し番号。⚠ 読めない / 26 バイト目が無ければ `None`。

    ⚠⚠ 25 バイトしか来ない古い Lua では `None`（★「取っていない」と混ぜない）。
    """
    from dq3rom import chest_flags as _cf

    try:
        raw = bytes.fromhex(str(bits_hex or ""))
    except ValueError:
        return None
    if len(raw) < _cf.ARRAY_BYTES:
        return None
    return _cf.hidden_taken(bytes(_cf.BASE) + raw)


#: ★1 度だけ起こす（⚠ ROM を毎回読まない / `chest_book.rom_spots` と同じ形）
_ROM: dict = {"spots": None}


def spots() -> dict:
    """★通し番号 → 升（⚠ ROM が読めなければ空）。"""
    if _ROM["spots"] is not None:
        return _ROM["spots"]
    try:
        from dq3rom import profile as _dq3
        from dq3rom import search_spots as _ss

        from .terrain import DEFAULT_ROM

        ident = _dq3.load_and_identify(DEFAULT_ROM)
        got = {s.serial: s for s in _ss.read_spots(ident) if s.kind == "item"}
    except Exception:                                      # noqa: BLE001 ★ROM が無い環境でも落ちない
        return {}
    _ROM["spots"] = got
    return got


def memo_text(item_name: str | None, place: str | None = None) -> str:
    """★勇者メモの 1 行（★宝箱と同じ形 / `chest_book.memo_text`）。

    ```text
    場所　しらべる：<道具の名前> を入手
    ```
    ⚠ 場所の名前が無ければ「しらべる：…」だけ（★名前を推測しない）。

    ⚠⚠ **見本に原作の道具名を書きません**（RX3-0433 / 2026-10-01）。
      ★`docs/00-project-policy.md` §3 で「原作テキストを配布物に焼かない」と
      決めており、⚠ この docstring は配布物に入ります。
    """
    what = "しらべる：%s を入手" % (item_name or "？")
    return ("%s　%s" % (place, what)) if place else what


class HiddenItemBook:
    """★取った隠し道具の記録（`work/dq3-knowledge/hidden-items.json`）。"""

    def __init__(self, path=None) -> None:
        self.path = pathlib.Path(path) if path is not None else DEFAULT_PATH
        self.records: dict[str, dict] = {}
        self.initialized = False
        self._dirty = False
        self.failed = 0
        self.last_error: str | None = None
        #: ★いま取った分（★`take_new` で受け取る / ⚠ 初めて見たときの分は入らない）
        self.just_taken: list[dict] = []

    def take_new(self) -> list[dict]:
        got, self.just_taken = self.just_taken, []
        return got

    def update(self, bits_hex) -> int:
        """★印を見て記録する。戻り値: ★増えた数（⚠ 印が読めなければ 0）。"""
        got = taken_serials(bits_hex)
        if got is None:
            return 0
        first = not self.initialized
        changed = 0
        for serial in got:
            key = str(serial)
            if key in self.records:
                continue
            rec = {"serial": int(serial), "taken_at": _now()}
            if first:
                rec["taken_before_seen"] = True         # ⚠ 前から取ってあった（★メモにしない）
            self.records[key] = rec
            changed += 1
            if not first:
                self.just_taken.append(dict(rec))
        if first:
            self.initialized = True
            changed += 1                                 # ★「見た」ことを残す（⚠ 次の起動で前の分を流さない）
        if changed:
            self._dirty = True
        return changed

    # --- ★しまう・戻す --------------------------------------------------

    def to_dict(self) -> dict:
        return {"version": FORMAT_VERSION, "game": "dq3", "initialized": self.initialized,
                "hidden_items": dict(sorted(self.records.items(), key=lambda kv: int(kv[0])))}

    @classmethod
    def from_dict(cls, data, path=None) -> "HiddenItemBook":
        got = cls(path)
        data = data or {}
        got.initialized = bool(data.get("initialized"))
        for key, row in (data.get("hidden_items") or {}).items():
            if isinstance(row, dict) and "serial" in row:
                got.records[str(key)] = dict(row)
            else:
                got.failed += 1
                got.last_error = "壊れた記録: %s" % key
        return got

    def save(self, force: bool = False) -> bool:
        if not force and not self._dirty:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            self.failed += 1                             # ⚠ 黙って捨てない
            self.last_error = str(exc)
            return False
        self._dirty = False
        return True

    @classmethod
    def load(cls, path=None) -> "HiddenItemBook":
        p = pathlib.Path(path) if path is not None else DEFAULT_PATH
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(p)
        return cls.from_dict(data, p)


__all__ = ["DEFAULT_PATH", "FORMAT_VERSION", "HiddenItemBook", "memo_text", "spots", "taken_serials"]
