"""いま戦っている敵（RX3-0021 / 2026-08-29）。

★★ 名前は「画面で見て覚える」 ★★

⚠⚠ **原作テキストを成果物へ焼きません**（`RX3-0011` 決定 ③）。
  ★敵の名前は ROM で圧縮されていますが、⚠ ゲーム自身が窓に出しています。

```text
fc6 の窓 (12,18):
  " スライム    ー 1ひき"
  " おおがらす   ー 2ひき"
```

★Lua は**生のタイル番号**だけを送り、文字にするのはここです。
⚠ 窓の探し方も文字表も `dq3rom/` に既にあるので、そのまま使います
（★Lua でもう一度書くと、2 か所で食い違います）。

## ★何を出すか

```text
種類と数   ⚠ RAM から（$056D / $0571）★確実
名前       ★画面から（⚠ 出ていないときは、前に覚えたものを使う）
```

## ⚠⚠ HP は出しません

★探しましたが RAM に見つかりませんでした
（⚠ スライム 4 匹のセーブで「8 が 4 つ並ぶ」場所が 0 件）。

⚠ そもそも**ゲームが見せない値**なので、No-Spoiler の考えでも出しません。
"""

from __future__ import annotations

import json
import pathlib
import re

from .. import paths

#: ★「ー」のタイル（⚠ 敵の行の目印）
DASH_TILE = 0x7F

#: ★覚えた名前の置き場（⚠ `work/` は Git の外）
DEFAULT_PATH = paths.lazy_work("dq3-knowledge", "enemy-names.json")

#: ★プロファイル（⚠ 文字表はここから）
PROFILE = (pathlib.Path(__file__).resolve().parents[2]
           / "dq3rom" / "profiles" / "dq3_fc_jp_rev0a.json")


def unhex(text):
    """★16 進の文字列を、タイル番号の並びに戻す。⚠ 壊れていれば空。"""
    if not isinstance(text, str) or len(text) % 2:
        return []
    try:
        return [int(text[i:i + 2], 16) for i in range(0, len(text), 2)]
    except ValueError:
        return []


#: ⚠ 文字表が「空白」「知らない字」に使う印（★名前から取り除く）
FILLER = ("␣", "·", "　", " ")


#: ⚠ 相手を選んでいるあいだ、敵の行の先頭に出るカーソル（★RX3-0063）
CURSORS = "\u25b6\u25bc\u25b8"


def _tidy(text: str) -> str:
    """★名前だけを取り出す（⚠ 空白と枠の印とカーソルを落とす）。

    ⚠⚠ 2026-09-03 の実機で `▶スライム` と読めていました
      （`work/dq3-probe/battle-screens.jsonl` #8 / #10 / #13）。
      ★狙う相手を選んでいるあいだ、⚠ 敵の行の**先頭に ▶ が出ます**。
    """
    for mark in FILLER:
        text = text.replace(mark, "")
    got = text.strip().lstrip(CURSORS).strip()
    return _katakana(got)


def _katakana(name: str) -> str:
    """⚠ 同じ絵を使い回している かな を直す（★入口は `name_text` の 1 つだけ）。

    ⚠⚠ ここを ROM 側とずらすと、★突き合わせ（`_cross_check`）が**必ず割れます**。
    """
    from dq3.knowledge.name_text import to_display

    return to_display(name)


def _charset():
    """⚠ 文字表は profile から（★ここに文字を書かない）。"""
    from retroux.core.text import Charset

    spec = json.loads(PROFILE.read_text(encoding="utf-8")).get("text")
    return Charset(spec) if spec else None


#: ⚠ 敵の行は「ー」のうしろが「N ひき」（★RX3-0063 / 2026-09-03）
COUNT_RE = re.compile(r"^(\d+)ひき")


def _split_row(text: str, box, inside: bytes):
    """★1 行を「名前」と「匹数」に割る。⚠ 割れなければ `None`。

    ⚠⚠ **「ー があること」だけでは敵の行と決められません**（RX3-0063）。

    ```text
    敵の行      「 スライム    ー 3ひき」   ★ー で名前と数を分ける
    メッセージ  「あかりは 2 の ダメージを うけた!」
                                  ↑ ★ダ「メー」ジ の ー が同じ 0x7F
    ```

    ★2026-09-03 の実機で、⚠ `あかりはダメ` を敵の名前として覚えていました
      （`work/dq3-knowledge/enemy-names.json` に保存までされていた）。
      ⚠ 敵 1 匹・該当行 1 本だと、**件数の歯止めも通ります**。

    → ★**ー のうしろが「N ひき」**の行だけを敵の行とみなします。

    ⚠ 名前そのものに「ー」が入るもの（★キラーマシンなど）があるので、
      **右から**探して、最初に「N ひき」が続いたところで割ります。
    """
    end = box.x + box.width + 1
    at = len(inside) - 1
    while at >= 0:
        idx = inside.rfind(bytes([DASH_TILE]), 0, at + 1)
        if idx < 0:
            return None
        dash = box.x + idx
        got = COUNT_RE.match(_tidy(text[dash + 1:end]))
        if got:
            name = _tidy(text[box.x + 1:dash])
            return (name, int(got.group(1))) if name else None
        at = idx - 1
    return None


def enemy_rows(tiles, columns: int = 32, rows: int = 30) -> list[tuple[str, int]]:
    """画面から「敵の名前と匹数」を並び順に読む。

    ⚠⚠ **窓の中だけを読みます。** ★1 行は画面いっぱい（32 桁）なので、
      素で切ると**左のコマンド窓の字が混ざります**
      （2026-08-29 に実際に「▶たたかう スライム」と読めてしまった）。

    ★濁点は 1 行上の別タイルなので、`dq3rom/screen.read_screen` に任せます
      （⚠ ここで合成し直すと 2 か所で食い違います）。
    """
    if not tiles or len(tiles) < columns * rows:
        return []
    charset = _charset()
    if charset is None:
        return []
    from dq3rom import screen as sc
    from dq3rom import window as win

    raw = bytes(t & 0xFF for t in tiles)
    lines = sc.read_screen(raw, charset)
    for box in win.find_windows(raw):
        got = []
        for y in range(box.y, min(box.y + box.height + 2, rows)):
            row = raw[y * columns:(y + 1) * columns]
            # ⚠ 窓の中だけを見る（★枠の外の「ー」は拾わない）
            inside = row[box.x:box.x + box.width + 2]
            if DASH_TILE not in inside:
                continue
            hit = _split_row(lines[y].text, box, inside)
            if hit is not None:
                got.append(hit)
        if got:
            # ★敵の窓は 1 つ（⚠ 最初に見つかったものを使う）
            return got
    return []


#: ⚠ 匹数として在り得る幅（★DQ3 は 1 群 8 匹まで）
SANE_COUNT = (1, 9)


def _sane(group) -> bool:
    """★その群を信じてよいか（RX3-0065 / 2026-09-03）。

    ⚠⚠ 戦闘の**開始直後**、RAM が未初期化の値を返す枚があります。

    ```text
    実測（work/dq3-probe/battle-screens.jsonl）
      #1 ids/n=[(0, 255)]                  ⚠ 匹数が 255
      #2 ids/n=[(0,0),(0,0),(0,0),(0,0)]   ⚠ 全部 0
    ```

    ★そこで名前を覚えると、⚠ **間違った番号に名前が付きます**
      （⚠⚠ しかも保存されるので、あとから気づけません）。
    """
    key = group.get("id")
    count = group.get("n")
    if key is None or not isinstance(count, int):
        return False
    return SANE_COUNT[0] <= count <= SANE_COUNT[1]


#: ⚠ 戦闘の初めに出る 1 行の形（★敵の名前ではなく、**言い回し**だけ）
APPEARED = re.compile(r"^(.{1,10}?)があらわれた")


def appeared_name(tiles, columns: int = 32, rows: int = 30) -> str | None:
    """★「◯◯が␣あらわれた！」の 1 行から名前を読む。

    ⚠⚠ **群が 1 つのときの唯一の手がかり**です（RX3-0065 / 2026-09-03）。

    ```text
    実測（work/dq3-probe/battle-screens.jsonl）
      1 群の戦闘 17 枚すべて   ⚠ 一覧の窓が**出ない**
      出ていたのは            ★「アルミラージが␣あらわれた！」の 1 行
    ```

    ★DQ3 は群が 1 つのとき、敵の一覧を出しません。
    ⚠ そのため `enemy_rows` は永久に空で、名前を 1 つも覚えませんでした。

    ⚠ 2 群以上では**使いません**。★「A と B が あらわれた」の形を
      実測していないので、**取り違える恐れ**があります。
    """
    if not tiles or len(tiles) < columns * rows:
        return None
    charset = _charset()
    if charset is None:
        return None
    from dq3rom import screen as sc

    raw = bytes(t & 0xFF for t in tiles)
    for line in sc.read_screen(raw, charset):
        got = APPEARED.match(_tidy(line.text))
        if got:
            name = got.group(1).strip()
            if name:
                return name
    return None


def names_on_screen(tiles, columns: int = 32, rows: int = 30) -> list[str]:
    """★名前だけを並び順に返す（⚠ 中身は `enemy_rows`）。"""
    return [name for name, _count in enemy_rows(tiles, columns, rows)]


class EnemyNames:
    """★見た敵の名前を覚えておく（⚠ 番号 → 名前）。"""

    def __init__(self, path=None) -> None:
        self.path = pathlib.Path(path) if path is not None else DEFAULT_PATH
        self.names: dict[int, str] = {}
        #: ⚠ 匹数が合わずに見送った回（★黙って 0 を返したことが見えるように）
        self.mismatched = 0
        #: ★ROM の名前との突き合わせ（RX3-0069 / ⚠ 不一致でも上書きしない）
        self.rom_agree = 0
        self.rom_disagree = 0
        self.mismatches: list[dict] = []
        #: ⚠⚠ 行が 1 本も読めなかった回（★敵の一覧が画面に出ていない）
        self.no_rows = 0
        #: ⚠⚠ 行が**足りなかった**回（★一部しか出ていない / RX3-0065）
        #:   ⚠ 実測では「群 2 / 行 1」がいちばん多い。
        #:   ★どの行がどの群か決められないので、覚えると取り違えます。
        self.partial = 0
        self.failed = 0
        self.last_error: str | None = None
        self._dirty = False

    def learn(self, groups, tiles) -> int:
        """★いま出ている敵の名前を覚える。⚠ 覚えた数を返す。

        `groups` は `[{"id": 0, "n": 1}, ...]`（★RAM から。順番が同じ）。
        ⚠ 名前が読めた数と群の数が**合わないときは覚えません**
          （★ずれたまま覚えると、別の敵の名前が付く）。
        """
        found = enemy_rows(tiles)
        if not found and len(groups) == 1 and _sane(groups[0]):
            # ★群が 1 つなら「◯◯があらわれた！」から覚える（RX3-0065）。
            #
            #   ⚠ 群が 1 つのとき、一覧は**出ないことが多い**
            #     （★実測 36 枚中、出ていたのは 3 枚だけ）。
            #   ⚠⚠ 「出ない」と言い切るのは**言い過ぎ**でした（2026-09-03 訂正）。
            solo = appeared_name(tiles)
            if solo:
                found = [(solo, int(groups[0].get("n") or 0))]
        if not found:
            self.no_rows += 1
            return 0
        if len(found) != len(groups):
            # ⚠⚠ 一部しか出ていない（RX3-0065 / 2026-09-03 実測）。
            #   ★どの行がどの群かを決められないので**覚えません**。
            #   ⚠ 間違った名前を付けるより、覚えないほうがましです。
            self.partial += 1
            return 0
        # ⚠ 匹数のずれは**数えるだけ**（RX3-0063 / 2026-09-03）。
        #
        #   ★最初は「合わない回は覚えない」にしていました。
        #   ⚠⚠ ところが実機 run で **会った 4 体 / 覚えた 0 件**になりました
        #     （`work/evidence/20260903_085554_fix-verify`）。
        #   ★戦闘中、窓の「N ひき」は**描き直されません**。
        #     ⚠ 1 匹倒した時点で RAM の匹数とずれ、そこから先は
        #     **永久に覚えなくなります**（★歯止めが強すぎました）。
        #
        #   → ★メッセージ窓を弾く本体は `_split_row` の**形**のほうです。
        for group, (_name, count) in zip(groups, found):
            if int(group.get("n") or 0) != count:
                self.mismatched += 1
        got = 0
        for group, (name, _count) in zip(groups, found):
            key = group.get("id")
            if key is None or not name:
                continue
            if self.names.get(int(key)) != name:
                self.names[int(key)] = name
                self._dirty = True
                got += 1
            self._cross_check(int(key), name)
        return got

    def _cross_check(self, key: int, seen: str) -> None:
        """★画面で読んだ名前を ROM の名前と突き合わせる（RX3-0069 §9）。

        ⚠⚠ **上書きしません。** ★一致は数え、不一致は両方と番号を残します。
        """
        from dq3.knowledge import rom_names

        rom = rom_names.monster(key)
        if rom is None:
            return
        if rom == seen:
            self.rom_agree += 1
        else:
            self.rom_disagree += 1
            self.mismatches.append({"id": key, "screen": seen, "rom": rom})

    def label(self, group) -> str:
        """★画面に出す 1 行。⚠ 名前を知らなければ番号で出す。"""
        from dq3.knowledge import rom_names

        key = group.get("id")
        count = group.get("n") or 0
        # ★ROM の名前を先に（primary / RX3-0069 §8）→ ⚠ ROM が無ければ画面で読めた名前
        name = (rom_names.monster(key) or self.names.get(int(key))) if key is not None else None
        if name is None:
            # ⚠ 知らないものを「知っている風」に出さない
            name = "？（敵 %s）" % key
        return "%s ー %d ひき" % (name, count)

    # --- ★しまう・戻す --------------------------------------------------

    def save(self, force: bool = False) -> bool:
        if not force and not self._dirty:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"game": "dq3",
                            "names": {str(k): v
                                      for k, v in sorted(self.names.items())}},
                           ensure_ascii=False),
                encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            # ⚠ 黙って捨てない
            self.failed += 1
            self.last_error = str(exc)
            return False
        self._dirty = False
        return True

    @classmethod
    def load(cls, path=None) -> "EnemyNames":
        got = cls(path)
        try:
            data = json.loads(got.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return got                     # ⚠ 無くても空から始める
        for key, name in (data.get("names") or {}).items():
            try:
                got.names[int(key)] = str(name)
            except (TypeError, ValueError):
                got.failed += 1
                got.last_error = "壊れた記録: %s" % key
        return got


# --- ★★ 会った / 倒した を覚える（RX3-0025 / 2026-08-30）-------------------
#
#   依頼者 2026-08-30:「モンスター情報が表示されない」
#                     「戦闘が終わっても直近のモンスター情報を表示させたい」
#
#   ⚠⚠ **中身をいつ出すか**は No-Spoiler の判断（指示書 §10）。
#     ★依頼者の選択は「1 度でも**倒したら**出す」（⚠ DQ2 の図鑑と同じ）。
#
#   ⚠ 「倒した」をどう知るか:
#     ★戦闘が終わったときに**経験値が増えていれば勝ち**。
#     ⚠ 逃げた・全滅したときは増えないので、これで見分けられる。

class EnemyBook(EnemyNames):
    """★見た名前に加えて、「会った」「倒した」を覚える。

    ⚠ `EnemyNames` を継承します（★名前を覚える仕組みはそのまま）。
    """

    def __init__(self, path=None) -> None:
        super().__init__(path)
        #: ★戦って見た敵（⚠ 倒したとは限らない）
        self.met: set = set()
        #: ★倒した敵（⚠ ここに入って初めて中身を出す）
        self.defeated: set = set()
        #: ★呪文を試した回数と効いた回数（RX3-0271）。`{敵: {耐性の名前: [試した, 効いた]}}`
        #:   ⚠ 観測だけ（★ゲーム自身の判定の結果 / 既にかかっていた敵は数えない）。⚠ ROM の耐性とは混ぜない
        self.tries: dict = {}

    def record_spell(self, enemy_id, key: str, ok: bool) -> None:
        """★1 回の判定を覚える（RX3-0271）。⚠ 1 回の失敗で「耐性がある」とは決めない（★数えるだけ）。"""
        if enemy_id is None or not key:
            return
        row = self.tries.setdefault(int(enemy_id), {}).setdefault(str(key), [0, 0])
        row[0] += 1
        if ok:
            row[1] += 1
        self._dirty = True

    def record_battle(self, groups, won: bool) -> int:
        """★1 つの戦闘を覚える。⚠ 新しく分かった数を返す。

        `won` は「経験値が増えたか」。⚠ 逃げた戦闘では中身を出しません。
        """
        added = 0
        for group in groups or ():
            key = group.get("id")
            if key is None:
                continue
            key = int(key)
            if key not in self.met:
                self.met.add(key)
                self._dirty = True
                added += 1
            if won and key not in self.defeated:
                self.defeated.add(key)
                self._dirty = True
                added += 1
        return added

    def knows_details(self, enemy_id) -> bool:
        """★その敵の中身を出してよいか。

        ⚠⚠ **倒していない敵の中身は出しません**（★No-Spoiler）。
        """
        return enemy_id is not None and int(enemy_id) in self.defeated

    # --- ★しまう・戻す ---------------------------------------------------

    def save(self, force: bool = False) -> bool:
        if not force and not self._dirty:
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "game": "dq3",
                "names": {str(k): v for k, v in sorted(self.names.items())},
                "met": sorted(self.met),
                "defeated": sorted(self.defeated),
                # ★RX3-0271: 呪文を試した回数 / 効いた回数（★観測だけ）
                "tries": {str(k): {name: list(v) for name, v in sorted(rows.items())}
                          for k, rows in sorted(self.tries.items())},
            }, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            # ⚠ 黙って捨てない
            self.failed += 1
            self.last_error = str(exc)
            return False
        self._dirty = False
        return True

    @classmethod
    def load(cls, path=None) -> "EnemyBook":
        got = cls(path)
        try:
            data = json.loads(got.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return got                     # ⚠ 無くても空から始める
        for key, name in (data.get("names") or {}).items():
            try:
                got.names[int(key)] = str(name)
            except (TypeError, ValueError):
                got.failed += 1
                got.last_error = "壊れた記録: %s" % key
        for field, target in (("met", got.met), ("defeated", got.defeated)):
            for key in (data.get(field) or ()):
                try:
                    target.add(int(key))
                except (TypeError, ValueError):
                    got.failed += 1
                    got.last_error = "壊れた記録: %s の %s" % (field, key)
        # ⚠ 倒したのに会っていない、は起きないはず（★念のためそろえる）
        got.met |= got.defeated
        # ★RX3-0271: 呪文を試した回数 / 効いた回数（⚠ 壊れた行は数えて捨てる / 無ければ空）
        for key, rows in (data.get("tries") or {}).items():
            try:
                got.tries[int(key)] = {str(name): [int(v[0]), int(v[1])] for name, v in dict(rows).items()}
            except (TypeError, ValueError, IndexError):
                got.failed += 1
                got.last_error = "壊れた記録: tries の %s" % key
        return got


#: ★ROM の敵の表から出す項目（⚠ 倒した敵にだけ出す）
#: ★Monster Panel に出す項目（⚠ 指示書 §18。DQ2 の略称に寄せる）
#:
#:   ⚠⚠ `hp` / `attack` / `defense` / `gold` は **10 bit の値**です
#:     （★`*_raw` は下位 8 bit だけ / `RX3-0033` で上位 2 bit を確定）。
MASTER_FIELDS = (
    ("HP", "hp"),
    ("MP", "mp"),
    ("攻", "attack"),
    ("守", "defense"),
    ("速", "agility"),
    ("EXP", "exp"),
    ("G", "gold"),
)

#: ⚠⚠ 2026-09-01 訂正: `*_raw` は**下位 8 bit だけ**でした。
#:   ★`RX3-0033` で上位 2 bit が確定したので、10 bit の値に替えます
#:   （⚠ HP が 255 を超える敵が 14 体います）。
DETAIL_FIELDS = (
    ("レベル", "level"),
    ("最大HP", "hp"),
    ("こうげき", "attack"),
    ("しゅび", "defense"),
    ("すばやさ", "agility"),
    ("経験値", "exp"),
)


def _master_row(enemy_id, rom_path=None):
    """★ROM の敵 1 行（⚠ 引いてくるだけ。出してよいかは決めない）。"""
    try:
        from dq3rom import enemies as en
        from dq3rom import profile as dq3
    except ImportError:
        return None
    target = pathlib.Path(rom_path) if rom_path else (
        pathlib.Path(__file__).resolve().parents[2] / "work" / "rom"
        / "DQ3_J.nes")
    try:
        rows = en.read_all(dq3.load_and_identify(target))
    except Exception:                                  # noqa: BLE001
        return None
    index = int(enemy_id)
    return rows[index] if 0 <= index < len(rows) else None


def details_of(enemy_id, rom_path=None):
    """★その敵の中身（⚠ ROM から。倒したかの判断はここではしない）。

    ⚠⚠ **呼ぶ前に `knows_details()` で確かめてください。**
      ★ここは「引いてくるだけ」で、出してよいかは決めません。

    ⚠ ROM が無ければ `None`（★落ちません）。
    """
    try:
        from dq3rom import enemies as en
        from dq3rom import profile as dq3
    except ImportError:
        return None
    target = pathlib.Path(rom_path) if rom_path else (
        pathlib.Path(__file__).resolve().parents[2] / "work" / "rom"
        / "DQ3_J.nes")
    try:
        rows = en.read_all(dq3.load_and_identify(target))
    except Exception:                                  # noqa: BLE001
        return None                        # ⚠ ROM が無い環境でも落ちない
    index = int(enemy_id)
    if not (0 <= index < len(rows)):
        return None
    got = rows[index]
    return [(label, getattr(got, field, None)) for label, field in DETAIL_FIELDS]


def master_of(enemy_id, rom_path=None):
    """★Monster Panel に出す性能（⚠ ROM の値をそのまま）。

    ⚠⚠ `details_of` との違い: あちらは「倒した敵だけ」の**中身**で、
      `RX3-0021` の No-Spoiler に従います。★こちらは指示書 §2.2:

      > 取得できた値をそのまま表示してよい

    ⚠ ROM が無ければ `None`（★落ちません）。
    """
    got = _master_row(enemy_id, rom_path)
    if got is None:
        return None
    return [(label, getattr(got, field, None)) for label, field in MASTER_FIELDS]

