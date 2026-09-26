"""宝箱を覚える（RX3-0207 / 2026-09-12 依頼者「DQ3 ダンジョン探索MAP v1」Phase C）。

★★ 決め方（指示書 §7〜§9 / §13 No-Spoiler）★★

```text
見つけた   宝箱の升が「探索済み」になった（RX3-0205 / ★勇者と同じ層として見えた）
開けた     ゲームの「宝箱を開けた印」（WRAM $608E〜 / 193 ビット）が立っている
中身       開けた後だけ（★ROM の中身 → 道具の辞書 `item_info` で名前にする）
```

⚠⚠ 探索していない宝箱は**記録にも入れません**（★ROM から先回りで出さない）。
⚠ 開ける前の中身は記録しません（★見つけた宝箱の中身も、開けるまでは知らないはず）。
⚠ セーブを読み直して印が 0 に戻っても、★開けた記録は消しません（RX3-0167 / 記録はプレイの知識）。
★最初に見つけた時点で印が立っていたら「前に開けた」（`opened_before_seen`）。

## ★材料

- ROM: `dq3rom/chests.py`（位置と中身 / 193 個）
  ★座標の分からない 5 個（⚠ map 23 のパープルオーブ など / RX3-0283）は、**印が立った瞬間だけ**拾う
  （⚠ 地図の印にも「見つけた数」にも出さない）
- 印: `dq3rom/chest_flags.py` と同じ並び（★MSB から / `$608E + (n >> 3)` の `bit 7 - (n & 7)`）
  ★Lua が `state.json` の `chest_bits`（25 バイトの 16 進）で渡す（`dq3/phase0/dev.lua`）。
- ⚠ UI は dq3rom を読まない決まり（`tests/test_dq3_ui.py`）→ ★ROM とのつなぎはここ（dq3/knowledge）。
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import pathlib

from .. import paths

#: ★保存先（⚠ `work/` は Git の外）
DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "chests.json")

#: ★状態（指示書 §7）
DISCOVERED = "DISCOVERED"
OPENED = "OPENED"
#: ★座標の分からない宝箱を見張っている（RX3-0283）。⚠ 「見つけた」ではない（★地図にも一覧にも出さない）
WATCHED = "WATCHED"

#: ★印のバイト数（⚠ `dq3rom/chest_flags.NBYTES` と同じ / 193 ビット）
FLAG_BYTES = 25

FORMAT_VERSION = 1


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


@dataclasses.dataclass(frozen=True)
class Spot:
    """★ROM の宝箱 1 つ（⚠ 中身を含む = 画面へは出さない / 開けた後だけ使う）。"""

    object_id: str
    index: int                  #: ★通し番号（= 印のビット）
    map_id: int
    x: int
    y: int
    reward: str                 #: item / gold / mimic / empty
    item_id: int | None = None
    amount: int | None = None


_ROM = {"spots": None}


def rom_spots() -> list[Spot]:
    """★ROM の宝箱（★座標が分からないものも入れる / ROM が無ければ空）。★1 度だけ起こす。

    ⚠⚠ 2026-09-18（RX3-0283 / 依頼者「ジパング宝箱でパープルオーブを手に入れたが、勇者メモにでない」）:
      ★以前は**座標の無い 5 個を捨てて**いた（193 → 188）。⚠ その 1 つがパープルオーブ（map 23）で、
      開けても記録にも勇者メモにも出なかった。→ ★**入れて**、地図の印だけ出さない（`marks` が外す）。
    """
    if _ROM["spots"] is not None:
        return _ROM["spots"]
    got: list[Spot] = []
    try:
        from dq3rom import area_maps as am
        from dq3rom import chests as C
        from dq3rom import profile

        from .terrain import DEFAULT_ROM

        ident = profile.load_and_identify(DEFAULT_ROM)
        for c in C.build(ident, am.decode_all(ident)):
            got.append(Spot(c.object_id, c.global_index, c.map_id, c.x, c.y,
                            c.reward.type, c.reward.item_id, c.reward.amount))
    except Exception:                                   # noqa: BLE001 ★ROM が無い環境
        got = []
    _ROM["spots"] = got
    return got


def is_opened(bits_hex, index: int) -> bool | None:
    """★その宝箱の印（⚠ 読めなければ None / ★MSB から = `dq3rom/chest_flags.bit_of` と同じ）。"""
    try:
        raw = bytes.fromhex(str(bits_hex or ""))
    except ValueError:
        return None
    off = int(index) >> 3
    if off >= len(raw):
        return None
    return bool(raw[off] & (1 << (7 - (int(index) & 7))))


def reward_label(spot: Spot) -> str:
    """★開けた宝箱の中身の呼び名（★道具は `item_info` の名前 / 指示書 §8）。"""
    if spot.reward == "item" and spot.item_id is not None:
        try:
            from .item_info import info

            got = info(spot.item_id)
        except Exception:                               # noqa: BLE001
            got = None
        return got.label if got is not None else "品 %d" % spot.item_id
    if spot.reward == "gold":
        return "%d ゴールド" % int(spot.amount or 0)
    if spot.reward == "mimic":
        return "魔物"
    return "からっぽ"


def memo_text(rec: dict, place: str | None = None) -> str:
    """★勇者メモの 1 行（RX3-0261 / 依頼者「ロマリア城 / 宝箱：てつのやり を入手」）。

    ```text
    品       場所　宝箱：てつのやり を入手
    ゴールド 場所　宝箱：120 ゴールド を入手   ★呼び名は `reward_label` と同じ（⚠ 2 か所で作らない）
    人食い箱 場所　宝箱：魔物だった           ⚠ 品として扱わない
    からっぽ 場所　宝箱：からっぽだった
    ```
    ⚠ 場所の名前が無ければ「宝箱：…」だけ（★名前を推測しない / 場所はメモの location_id に残る）。
    """
    reward = rec.get("reward")
    if reward == "mimic":
        what = "宝箱：魔物だった"
    elif reward in ("item", "gold"):
        what = "宝箱：%s を入手" % (rec.get("item_name") or "？")
    else:
        what = "宝箱：からっぽだった"
    return "%s　%s" % (place, what) if place else what


class ChestBook:
    """★見つけた宝箱・開けた宝箱の記録（`work/dq3-knowledge/chests.json`）。"""

    def __init__(self, path=None, spots=None) -> None:
        self.path = pathlib.Path(path) if path is not None else DEFAULT_PATH
        #: ⚠ 検査は偽の宝箱を渡す（★None なら ROM から）
        self._spots = spots
        self.records: dict[str, dict] = {}
        self._dirty = False
        self.failed = 0
        self.last_error: str | None = None
        #: ★いま開いた宝箱（RX3-0261 / ★勇者メモへ渡す / `take_opened` で受け取る）。
        #   ⚠ 見つけたときにもう開いていた宝箱・読み込んだ記録（過去に開けた分）は入らない
        self.just_opened: list[dict] = []

    def take_opened(self) -> list[dict]:
        """★いま開いた宝箱を受け取る（★受け取ったら空にする = 1 つの宝箱は 1 回だけ）。"""
        got, self.just_opened = self.just_opened, []
        return got

    def spots(self, map_id) -> list[Spot]:
        every = self._spots if self._spots is not None else rom_spots()
        return [s for s in every if s.map_id == int(map_id)]

    def update(self, map_id, explored, bits_hex) -> int:
        """★見つけた / 開けたを記録する。戻り値: ★変わった数。

        `explored`: その地図の探索済みの升（★`ExploredMap.cells`）。`bits_hex`: state.json の `chest_bits`。
        """
        changed = 0
        for spot in self.spots(map_id):
            rec = self.records.get(spot.object_id)
            fresh = False
            if rec is None:
                # ★★ 座標の分からない宝箱（RX3-0283 / 5 個）は「探索済み」で測れない。
                #   ⚠ 中身は出さず、★**印が立った瞬間**だけ拾う（= 開けたことは分かる / No-Spoiler は保つ）。
                if spot.x is None or spot.y is None:
                    if is_opened(bits_hex, spot.index):
                        # ⚠ 見はじめた時にはもう開いていた → 黙って覚える（★勇者メモには流さない）
                        self.records[spot.object_id] = {
                            "object_id": spot.object_id, "map_id": spot.map_id, "x": None, "y": None,
                            "state": OPENED, "opened_at": _now(), "opened_before_seen": True,
                            "reward": spot.reward, "item_id": spot.item_id, "item_name": reward_label(spot)}
                        changed += 1
                        continue
                    self.records[spot.object_id] = {
                        "object_id": spot.object_id, "map_id": spot.map_id, "x": None, "y": None,
                        "state": WATCHED, "seen_at": _now()}   # ★まだ開いていない（⚠ 地図にも一覧にも出さない）
                    changed += 1
                    continue
                if (spot.x, spot.y) not in explored:
                    continue                          # ⚠⚠ 探索していない宝箱は記録しない（No-Spoiler）
                rec = self.records[spot.object_id] = {
                    "object_id": spot.object_id, "map_id": spot.map_id, "x": spot.x, "y": spot.y,
                    "state": DISCOVERED, "discovered_at": _now()}
                fresh = True
                changed += 1
            if rec.get("state") != OPENED and is_opened(bits_hex, spot.index):
                rec.update({"state": OPENED, "opened_at": _now(), "reward": spot.reward,
                            "item_id": spot.item_id, "item_name": reward_label(spot)})
                if spot.amount is not None:
                    rec["amount"] = spot.amount
                if fresh:
                    rec["opened_before_seen"] = True  # ★見つけたときにはもう開いていた
                else:
                    self.just_opened.append(dict(rec))  # ★いま開いた（RX3-0261 / 勇者メモへ）
                changed += 1
        if changed:
            self._dirty = True
        return changed

    def marks(self, map_id) -> list[tuple[int, int, str]]:
        """★MAP に出す印（x, y, 状態）。⚠ 記録にある宝箱だけ（= 見つけたもの）。

        ⚠ 座標の分からない宝箱（RX3-0283）は出しません（★升が決まらない）。
        """
        return sorted((r["x"], r["y"], r["state"]) for r in self.records.values()
                      if int(r.get("map_id", -1)) == int(map_id)
                      and r.get("x") is not None and r.get("y") is not None)

    def rows(self, map_id=None) -> list[dict]:
        """★記録（⚠ 中身は開けたものだけ入っている）。

        ⚠ 見張っているだけの宝箱（`WATCHED` / RX3-0283）は出しません（★「見つけた数」に入れない）。
        """
        return [dict(r) for _k, r in sorted(self.records.items())
                if r.get("state") != WATCHED
                and (map_id is None or int(r.get("map_id", -1)) == int(map_id))]

    # --- ★しまう・戻す --------------------------------------------------

    def to_dict(self) -> dict:
        return {"version": FORMAT_VERSION, "game": "dq3", "chests": dict(sorted(self.records.items()))}

    @classmethod
    def from_dict(cls, data, path=None, spots=None) -> "ChestBook":
        got = cls(path, spots=spots)
        rows = (data or {}).get("chests") if isinstance(data, dict) else None
        for key, row in (rows or {}).items():
            if isinstance(row, dict) and {"map_id", "x", "y", "state"} <= set(row):
                got.records[str(key)] = dict(row)
            else:
                got.failed += 1
                got.last_error = "壊れた記録: %s" % key
        return got

    def save(self, force: bool = False) -> bool:
        """★書き出す（⚠ 変わっていなければ何もしない / 一時ファイルから置き換える）。"""
        if not force and not self._dirty:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            self.failed += 1                           # ⚠ 黙って捨てない
            self.last_error = str(exc)
            return False
        self._dirty = False
        return True

    @classmethod
    def load(cls, path=None, spots=None) -> "ChestBook":
        target = pathlib.Path(path) if path is not None else DEFAULT_PATH
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(target, spots=spots)
        return cls.from_dict(data, target, spots=spots)


__all__ = ["DEFAULT_PATH", "DISCOVERED", "OPENED", "Spot", "ChestBook",
           "rom_spots", "is_opened", "reward_label"]
