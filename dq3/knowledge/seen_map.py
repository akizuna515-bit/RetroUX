"""見た升を貯める（RX3-0023 / 2026-08-29）。

★★ これが「見た所だけ描く」の土台です ★★

依頼者 2026-08-29 の選択:

    見た所だけ塗る
      ★探索は残る / ⚠ 最初はほぼ真っ黒

## ⚠⚠ 「見た」の決め方

★**画面に映った升**を「見た」とします（⚠ 歩いた升ではありません）。

```text
歩いた升だけ  → ⚠ 目の前の地形が黒いままで、地図として読めない
画面に映った  → ★実際に目で見たもの。⚠ ずるにならない
```

⚠ 窓が開いていて隠れていた升も「映った」に数えます。★窓は動くので、
隠れていたかを厳密に追うと、重いわりに得るものがありません。

## ★どの升が映っているか

`dq3rom/viewport.py` が答えを持っています（⚠ こちらで数え直さない）。

```text
主人公はいつも画面の升 (8, 7)   ★16x16 の升で数えて
地図 = 主人公の地図座標 + (画面の升 - (8, 7))
```

⚠ スクロールからは求まりません（★面がスクロールに合わせて書き換わるため、
`scroll / 16` は地図座標になりません）。これは実測で確かめた話です。

## ⚠⚠ 地図の鍵は「種別 + 番号」

★世界地図とローカルで**座標の意味が違う**ので、混ぜてはいけません。

```text
kind 0  世界地図        鍵 "w"      座標 $2A/$2B
kind 2  アレフガルド    鍵 "a"      座標 $2A/$2B
kind 1  ローカル        鍵 "L<番号>" 座標 $30/$31
```

⚠ `map_no`（`$8B`）は**ローカルのときだけ**意味があります。
★世界地図に出ても**前のローカルの値が残ったまま**でした
（2026-08-29 実測: セーブ 10 個中 8 個が世界地図なのに `map_no=9`）。

⚠⚠ ここを 1 つの番号で混ぜると、**世界地図を歩いた記録が街の地図に化けます**。

## ⚠ 入れ物の形

```text
map_id ごとに、升 1 つ = 1 ビット
  ビットの位置 = y * width + x
  ★width は「これまでに見た中でいちばん右 + 1」を 16 の倍数へ丸めたもの
```

⚠ 座標の一覧（`[[3,4],[3,5],...]`）にすると、世界地図を歩き回ったとき
**数万件**になります。★ビットなら 256x256 でも 8KB です。

## ⚠⚠ 消えては困る

★記録は `work/dq3-knowledge/seen.json` に置きます。

⚠ `work/` は Git の外なので、**消したら戻りません**。
★だから「保存に失敗したら黙って捨てる」ことはせず、⚠ 失敗を数えて残します。

## ⚠ どれくらい細かく拾えるか

```text
Lua が state.json を書く  30 フレーム（★約 0.5 秒）
画面が読む                 500 ms
1 画面                     16 x 15 升
```

⚠ 普通の速さでは 0.5 秒に 2 升ほどしか動かないので、★隙間は出ません
（視界が 16 升あるため、8 升動いても半分は重なります）。

⚠⚠ **ターボで極端に速く走ると、隙間が出ます**（★0.5 秒で 16 升以上動いた場合）。
⚠ 通った所を推測で塗ることは**しません**（★見ていない升を塗ることになるため）。
→ ⚠ そのときは、もう一度歩けば埋まります。

## ⚠ 重くしない

DQ2 で踏んだ実測: 地図の描き直しが 1 回 **137.8 ms**（★1 歩ごと）。

→ ⚠ **毎フレーム保存しない。** ★中身が増えたときだけ、しかも
`SAVE_EVERY_SECONDS` に 1 回までにします。
"""

from __future__ import annotations

import base64
import dataclasses
import json
import pathlib
import time

from dq3rom import viewport

from .. import paths

#: ★保存先（⚠ `work/` は Git の外）
DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "seen.json")

#: ★幅を丸める単位（⚠ 1 升増えるたびに詰め直さないため）
WIDTH_STEP = 16

#: ⚠ これより短い間隔では保存しない（★毎フレーム書かない）
SAVE_EVERY_SECONDS = 5.0

#: ★書き出す形の版（⚠ 形を変えたら上げる）
FORMAT_VERSION = 2

#: ★居場所の種別（⚠ `dq3rom/profiles/…json` の `runtime.location.kind`）
KIND_WORLD = 0
KIND_LOCAL = 1
KIND_ALEFGARD = 2


#: ★新しい鍵の形（⚠ これに合わないものは古い記録）
KEY_SHAPE = __import__("re").compile(r"^(w|a|L\?|L[0-9]+|k[-0-9]+)$")


def is_map_key(key) -> bool:
    """★`map_key()` が作る形かどうか。

    ⚠ はじめは地図番号だけ（`"9"`）を鍵にしていました。
    ★そのころの記録は**世界地図と街が混ざっている**ので、見分けて外します。
    """
    return bool(KEY_SHAPE.match(str(key)))


#: ★世界（地上）として扱う種別（⚠ ここに無いものは**ローカル**）
WORLD_KINDS = (KIND_WORLD, KIND_ALEFGARD)


def is_local(loc_kind) -> bool:
    """★「地図の中」か（⚠ 世界地図・アレフガルド以外はすべてローカル / RX3-0103）。

    ## ⚠⚠ なぜ「1 だけ」ではいけないか

      ★依頼者の実測（`DQ3_J.fc6` / ナジミの塔へ行く洞窟）:

      ```text
      kind($2F) = 5   map_no($8B) = 45   寸法($88/$89) = 58x40
      ★ROM の area map 45 も 58x40（⚠ 番号も寸法も**正しい**）
      ```

      ⚠ それでも `kind == 1` だけを見ていたので、★記録は `k5` という別枠へ行き、
      ⚠⚠ **MAP は真っ黒 / 場所の名前も付けられません**でした。
    """
    return loc_kind is not None and loc_kind not in WORLD_KINDS


def map_key(loc_kind, map_id=None) -> str:
    """★その地図をひとつに決める鍵。

    ⚠⚠ 番号だけで混ぜない。★世界地図の `map_no` は**前の値の残り**なので、
    そのまま使うと**世界を歩いた記録が街の地図に化けます**。
    """
    if loc_kind == KIND_ALEFGARD:
        return "a"
    if loc_kind == KIND_WORLD:
        return "w"
    if is_local(loc_kind) and map_id is not None:
        return "L%d" % int(map_id)
    if loc_kind == KIND_LOCAL:
        # ⚠ ローカルなのに番号が分からないときは、★別枠に置く
        return "L?"
    # ⚠⚠ 番号の無い知らない種別は**混ぜない**（★既存の地図へ流し込まない）
    return "k%s" % loc_kind


@dataclasses.dataclass
class _Map:
    """1 つの地図ぶんの記録。"""

    width: int = WIDTH_STEP
    cells: set = dataclasses.field(default_factory=set)

    def mark(self, x: int, y: int) -> bool:
        """★1 升を見たことにする。⚠ 増えたら True。"""
        if x < 0 or y < 0:
            # ⚠ 地図の外（★端に寄ると画面には映るが、地図には無い）
            return False
        if (x, y) in self.cells:
            return False
        self.cells.add((x, y))
        if x >= self.width:
            self.width = ((x // WIDTH_STEP) + 1) * WIDTH_STEP
        return True


class SeenMap:
    """map_id ごとに「見た升」を貯める。

    ⚠ ここは**貯めるだけ**です。★描くのは `dq3/ui/map_window.py`。
    """

    def __init__(self, path=None) -> None:
        self.path = pathlib.Path(path) if path is not None else DEFAULT_PATH
        self.maps: dict[str, _Map] = {}
        #: ★保存できなかった回数（⚠ 黙って捨てない）
        self.failed = 0
        self.last_error: str | None = None
        #: ★最後に保存したときの時計（⚠ 間隔を守るため）
        self._saved_at = 0.0
        #: ⚠ 保存してから増えたか
        self._dirty = False

    # --- ★記録する ------------------------------------------------------

    def mark(self, key: str, x: int, y: int) -> bool:
        """★1 升。⚠ 増えたら True。`key` は `map_key()` が作る文字列。"""
        key = str(key)
        got = self.maps.get(key)
        if got is None:
            got = self.maps[key] = _Map()
        if got.mark(int(x), int(y)):
            self._dirty = True
            return True
        return False

    def mark_view(self, key: str, party_x: int, party_y: int,
                  width: int | None = None, height: int | None = None) -> int:
        """★いま画面に映っている升を、まとめて見たことにする。

        ⚠ 地図の大きさが分かっていれば渡してください（★外を塗らないため）。
        分からなければ、**0 以上**であることだけで通します。

        戻り値: ★新しく見た升の数。
        """
        # ⚠ 大きさが分からないときは、画面ぶんだけ通る大きな値を置く。
        #   ★`Viewport.contains` は 0 <= x < width で見るだけなので、
        #   これで「負を捨てる」ふるまいだけが残る。
        view = viewport.Viewport(
            party_x=int(party_x), party_y=int(party_y),
            width=int(width) if width else 1 << 30,
            height=int(height) if height else 1 << 30)
        added = 0
        for map_x, map_y, _tile_x, _tile_y in view.visible_cells():
            if self.mark(key, map_x, map_y):
                added += 1
        return added

    # --- ★読み出す ------------------------------------------------------

    def is_seen(self, key: str, x: int, y: int) -> bool:
        got = self.maps.get(str(key))
        return got is not None and (int(x), int(y)) in got.cells

    def cells(self, key: str) -> set:
        """★その地図で見た升（⚠ 中身を書き換えないこと）。"""
        got = self.maps.get(str(key))
        return got.cells if got is not None else set()

    def count(self, key: str | None = None) -> int:
        if key is None:
            return sum(len(m.cells) for m in self.maps.values())
        return len(self.cells(key))

    # --- ★しまう・戻す --------------------------------------------------

    def to_dict(self) -> dict:
        """⚠ 升 1 つ = 1 ビット（★座標の一覧だと数万件になる）。"""
        maps = {}
        for key, got in sorted(self.maps.items()):
            if not got.cells:
                continue
            height = max(y for _x, y in got.cells) + 1
            blob = bytearray((got.width * height + 7) // 8)
            for x, y in got.cells:
                bit = y * got.width + x
                blob[bit // 8] |= 1 << (bit % 8)
            maps[key] = {
                "w": got.width,
                "h": height,
                "bits": base64.b64encode(bytes(blob)).decode("ascii"),
            }
        return {"version": FORMAT_VERSION, "game": "dq3", "maps": maps}

    @classmethod
    def from_dict(cls, data: dict, path=None) -> "SeenMap":
        got = cls(path)
        if not isinstance(data, dict):
            return got
        # ⚠⚠ **古い形の記録は読みません。**
        #
        #   ★版 1 は鍵が地図番号だけでした。⚠ 世界地図でも `map_no` に
        #   前の値（例: 9）が残るため、**世界を歩いたぶんが街の地図として
        #   貯まっています**（2026-08-30 に実機で 686 升の混入を確認）。
        #   → ⚠ そのまま描くと、街の地図に**行っていない所の地形**が出ます。
        #
        #   ⚠ 捨てはしません（★`seen-v1.json` として隣に残します）。
        rows = dict(data.get("maps") or {})
        # ⚠⚠ **古い形の鍵は読みません。**
        #
        #   ★はじめは鍵が地図番号だけ（`"9"`）でした。⚠ 世界地図でも
        #   `map_no` に前の値（例: 9）が残るため、**世界を歩いたぶんが
        #   街の地図として貯まります**（2026-08-30 に実機で 686 升の混入を確認）。
        #   → ⚠ そのまま描くと、街の地図に**行っていない所の地形**が出ます。
        #
        #   ⚠ 捨てはしません（★`seen-v1.json` として隣に残します）。
        old_keys = [k for k in rows if not is_map_key(k)]
        if old_keys:
            got.failed += 1
            got.last_error = (
                "古い形の鍵が %d 件ありました（%s …）。"
                "⚠ 世界地図と街が混ざっているので読みません。"
                "★`seen-v1.json` に残してあります。"
                % (len(old_keys), ", ".join(sorted(old_keys)[:4])))
            got._keep_old(data)
            for k in old_keys:
                rows.pop(k, None)
        for key, one in rows.items():
            try:
                width = int(one["w"])
                height = int(one["h"])
                blob = base64.b64decode(one["bits"])
            except (KeyError, TypeError, ValueError):
                # ⚠ 1 つ壊れていても、★残りは読める
                got.failed += 1
                got.last_error = "壊れた記録: map %s" % key
                continue
            entry = got.maps.setdefault(str(key), _Map())
            entry.width = max(entry.width, width)
            # ⚠ 途中で切れている記録もある（★書いている最中に落ちた等）。
            #   ⚠⚠ 長さを信じて読むと `IndexError` で**全部**読めなくなる。
            #   → ★実際にあるバイトぶんだけ読む。
            usable = min(width * height, len(blob) * 8)
            if usable < width * height:
                got.failed += 1
                got.last_error = "途中で切れた記録: map %s" % key
            for bit in range(usable):
                if blob[bit // 8] & (1 << (bit % 8)):
                    entry.cells.add((bit % width, bit // width))
        return got

    def _keep_old(self, data) -> bool:
        """★読まなかった記録を、隣に残す（⚠ 消さない）。"""
        if self.path is None:
            return False
        try:
            spare = self.path.with_name(self.path.stem + "-v1.json")
            if spare.exists():
                return False               # ⚠ 既にある（★上書きしない）
            spare.parent.mkdir(parents=True, exist_ok=True)
            spare.write_text(json.dumps(data, ensure_ascii=False),
                             encoding="utf-8")
            return True
        except (OSError, TypeError, ValueError):
            return False

    def save(self, force: bool = False) -> bool:
        """★書き出す。⚠ 増えていなければ何もしない。

        ⚠ 間隔を守る（★毎フレーム書かない）。`force` で今すぐ書ける。
        """
        if not force:
            if not self._dirty:
                return False
            if time.monotonic() - self._saved_at < SAVE_EVERY_SECONDS:
                return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # ⚠ 書いている途中を読ませない（★一時ファイルから置き換える）
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False),
                encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            # ⚠⚠ 黙って捨てない（★消えたら戻らない記録）
            self.failed += 1
            self.last_error = str(exc)
            return False
        self._saved_at = time.monotonic()
        self._dirty = False
        return True

    @classmethod
    def load(cls, path=None) -> "SeenMap":
        """★読み込む。⚠ 無ければ空（**新しい冒険**）。"""
        target = pathlib.Path(path) if path is not None else DEFAULT_PATH
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # ⚠ 壊れていても消さない（★人が見て直せるように残す）
            return cls(target)
        return cls.from_dict(data, target)
