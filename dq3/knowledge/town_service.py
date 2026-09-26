"""街ナビ＋聞き込みの service（RX3-0058）。★UI はここだけを呼ぶ（指示書 §28）。

```text
known_reachable_facilities()   ★面識（heard）のある施設 NPC で、いま辿り着ける → 目的地リスト
unheard_reachable_npcs()       ★未会話 / talk_id != 0 / いま居る / 辿り着ける → 聞き込みの候補（BFS の近い順）
plan_to(npc)                   ★隣（カウンター越し含む）へ BFS → Lua へ渡す keys / cells / face
record_heard()                 ★会話が開いた事実を heard へ（本文は画面に出たものだけ）
```

## ⚠ 通行可否は ROM の collision（OBSERVED / RX3-0051）

★1,000 超の edge で BLOCK→PASS 0 だが CONFIRMED ではない。⚠ 依頼者の指示書 §24 に従って使う。
閉じた扉は BLOCK、warp / SPECIAL は経路に含めない（★BFS は床 P とカウンター C だけを通る）。

## ★ROM の先回りをしない（指示書 §1 / §3-3）

★目的地リストに出るのは heard = true の施設だけ。★聞き込みの候補は UI に詳細を出さず、内部で順番に回すだけ。
"""
from __future__ import annotations

import collections
import datetime as _dt
import json
import pathlib

from dq3 import paths as _paths
from dq3.knowledge import npc_heard as _heard
from dq3.knowledge import npc_master as _master
from dq3.testing import navigation as _nav
from dq3.testing import passability as _pass
from dq3.testing import talk_script as _talk

ROOT = pathlib.Path(__file__).resolve().parents[2]
GRID_DIR = ROOT / "work" / "dq3-nav"

#: ★聞き込みで 1 体に許す近づき直しの上限（★Lua 側の上限と揃える。超えたら skip_unreachable_now）
MAX_APPROACHES = 8

#: ★★ 聞き込みで**話しかけない**相手（talk_id → わけ / RX3-0194 / 2026-09-12）。⚠ 手で話すのは止めない
#:
#:   ⚠⚠ 依頼者「save3 王様に聞き込みをしてセーブして終了してしまう」: 王様は冒険の書に記録したあと
#:     「どうじゃ？ また すぐに たびだつ つもりか？」と聞く。★聞き込みは窓を B で閉じるので、
#:     ⚠ B（取り消し）が「いいえ」になり**ゲームが終わる**。★話の中身も次のレベルまでの経験値だけ。
#:
#:   ⚠⚠ 2026-09-12 再発（依頼者「イシス（save6）でやはり再発する」/ RX3-0194 再開）: 手の表は 430 / 426 だけで、
#:     ★イシスの女王（433）は表にも記録にも無かった。→ ★王様の相手は **ROM から起こす**（`rom_save_kings()`）。
#:     ★記録して旅立つかを聞く処理 bank 13 `$BB61` に入る台本 = {426, 430, 431〜436}（`talk_script.save_king_talk_ids`）。
#:     ★430 / 426 は ROM が読めないときの**控え**として残す（⚠ 消さない）。
#:     ★それでも話してしまったときは、Lua が Q2 に「はい」で答える（`nav_v0.lua` の `$BB9D` / Layer A）。
HEARING_SKIP_TALK_IDS = {
    430: "アリアハンの王様（記録して「また たびだつか」→ B でゲームが終わる）",
    # ⚠⚠ 2026-09-12 依頼者「save8 ロマリアの玉座で同様の動きになってしまった（セーブして終了）」
    426: "ロマリアの王様（同上 / map 74 / npc 1）",
    # ⚠⚠ RX3-0217（2026-09-12 依頼者「save5 アッサラームの押しの強い商人。無限ループになり…」）:
    #   「うっているものを みますか？」に B（= いいえ）→「まあ そういわずに」で同じことを聞き直す。
    #   ★聞き込みは B しか押さないので、⚠ B を 16 回押して聞き込みごと止まり、窓が開いたまま残った。
    974: "アッサラームの押しの強い商人（map 12 / npc 11 / B = いいえ で聞き直し続ける）",
    973: "アッサラームの押しの強い商人（map 12 / npc 10 / ★同じ見た目・隣の台本 / 同じ止まり方）",
}

#: ★★ 聞き込みで困る相手を、会話の記録から見分ける言葉の組（★組の言葉を**全部**言った相手 / RX3-0194・0217）。
#:   ⚠ 王様ごとに talk_id も台本も違う（430 = 台本 70 / 426 = 台本 66）→ ★番号の決まりが無い。
#:   ★一度でも記録に残った相手は、次から話しかけない（⚠ はじめての相手は防げない → 分かったら表にも足す）
SAVE_TALK_WORDS = ("ぼうけんのしょ", "たびだつ")
#: ★「いいえ」で聞き直し続ける商人（★ほかの町の押しの強い商人も、一度記録に残れば外す）
LOOP_TALK_WORDS = ("そういわずに",)
SKIP_TALK_WORD_GROUPS = (SAVE_TALK_WORDS, LOOP_TALK_WORDS)
CONVERSATIONS_PATH = _paths.work("dq3-knowledge", "npc-conversations.json")
_LEARNED = {"key": None, "ids": frozenset()}


def learned_save_talks(path=None) -> frozenset:
    """★会話の記録で「ぼうけんのしょ」と「たびだつ」を両方言った相手の talk_id（⚠ 読めなければ空）。

    ★ファイルの更新時刻で覚えておく（⚠ 聞き込みは 1 人ごとに何度も呼ぶ）。
    """
    target = pathlib.Path(path) if path else CONVERSATIONS_PATH
    try:
        stamp = target.stat().st_mtime_ns
    except OSError:
        return frozenset()
    key = (str(target), stamp)
    if _LEARNED["key"] == key:
        return _LEARNED["ids"]
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    ids = set()
    for rows in (raw or {}).values() if isinstance(raw, dict) else ():
        for row in rows or []:
            text = str((row or {}).get("text") or "")
            if any(all(word in text for word in group) for group in SKIP_TALK_WORD_GROUPS):
                try:
                    ids.add(int(row.get("talk_id")))
                except (TypeError, ValueError):
                    pass
    _LEARNED["key"], _LEARNED["ids"] = key, frozenset(ids)
    return _LEARNED["ids"]


def rom_save_kings() -> frozenset:
    """★ROM から見分けた「冒険の書に記録して また たびだつかを聞く」相手（RX3-0194 / ⚠ 読めなければ空）。"""
    return _talk.save_king_talk_ids()


def hearing_target(npc: dict, learned=None) -> bool:
    """★聞き込みで話しかける相手か（⚠ talk_id = 0 と、話しかけない相手を外す / ★数えるときも同じ決まり）。

    ★外すのは 手の表（`HEARING_SKIP_TALK_IDS`）/ ROM の王様（`rom_save_kings()`）/ 会話の記録（`learned`）。
    `learned`: 会話の記録から見分けた相手（★既定は `learned_save_talks()`）。
    """
    tid = int((npc or {}).get("talk_id") or 0)
    if tid == 0 or tid in HEARING_SKIP_TALK_IDS or tid in rom_save_kings():
        return False
    return tid not in (learned_save_talks() if learned is None else learned)


_DEPART_TILES: dict = {}


def depart_answer_params() -> dict:
    """★聞き込みの Lua へ渡す「はい」「いいえ」のタイル（RX3-0194 / `nav_v0.lua` が Q2 の窓を探す）。

    ⚠ 作れなければ空（★Lua は窓を見つけられず、**A を押さずに**止まる）。
    """
    if "params" not in _DEPART_TILES:
        try:
            from dq3.knowledge.restock import _charset
            from dq3.phase0.generate_lua import tile_bytes

            charset = _charset()
            _DEPART_TILES["params"] = {
                word: "".join("%02X" % b for b in tile_bytes(text, charset))
                for word, text in (("yes", "はい"), ("no", "いいえ"))}
        except Exception:                                    # noqa: BLE001 ★文字表が読めない
            _DEPART_TILES["params"] = {}
    return dict(_DEPART_TILES["params"])


class TownService:
    def __init__(self, heard: _heard.HeardLedger | None = None, rom_maps: dict | None = None,
                 labels: dict | None = None) -> None:
        self.heard = heard or _heard.HeardLedger()
        self._rom_maps: dict[int, _pass.RomMap] = rom_maps if rom_maps is not None else {}
        self._labels = labels

    # ------------------------------------------------------------------
    # ★材料
    # ------------------------------------------------------------------
    @staticmethod
    def depart_answer_params() -> dict:
        """★聞き込みの Lua へ渡す「はい」「いいえ」のタイル（RX3-0194 / ★UI はここから受け取る）。"""
        return depart_answer_params()

    def rom_map(self, map_id: int) -> _pass.RomMap | None:
        if map_id not in self._rom_maps:
            try:
                self._rom_maps[map_id] = _pass.from_rom(map_id)
            except Exception:                                    # noqa: BLE001 ★展開できない map
                self._rom_maps[map_id] = None
        return self._rom_maps[map_id]

    def current_npcs(self, map_id: int, time_byte: int | None, npc_tbl_hex: str | None) -> dict:
        """★Master + Runtime を 1 つに。⚠ 差し替え map は status = UNKNOWN で空。"""
        # ★heard はファイルから読み直す（⚠ 管理画面が初期化 / 復元した後に古い中身で候補を作らない / RX3-0059）
        try:
            self.heard.reload()
        except Exception:                                        # noqa: BLE001
            pass
        # ★差し替えのある map でも、実機の表が既定の表と一致すれば使う（RX3-0175 / ロマリア）
        master = _master.master_for(map_id, time_byte, npc_tbl_hex)
        slots = _master.runtime_slots(npc_tbl_hex)
        rows = _master.merged(master, slots) if master["status"] == "DEFAULT" else []
        rows, off_map = self._on_map(map_id, rows)
        return {"map_id": map_id, "time": master["time"], "status": master["status"], "npcs": rows,
                "runtime_count": len(slots), "table_id": master.get("table_id"), "off_map": off_map}

    def _on_map(self, map_id: int, rows: list[dict]) -> tuple[list[dict], list[int]]:
        """★いまの位置が地図の外の人を外す（RX3-0250）。戻り値: (地図の中の人, 外した npc_id)。

        ⚠⚠ 2026-09-13 依頼者「地図の外にいる人を、聞き込みの数に入れないようにしてよいですか → OK」:
          ★save3 のジパング（map 23 = 39 x 63）の npc 4・5 は (18,92)・(18,93)（★ROM の表でも RAM でも同じ / 立てる升 0）。
          ⚠ 聞き込みのたびに「未完 2 人」と数えていた。★イベントで消えた人（(128,128) / `npc_master.merged`）と同じ扱い。
        ★位置は毎回 RAM を優先して見るので、イベントで地図の中に出てくれば、そのときから候補に入る。
        ⚠ 地図が読めなければ外さない（★今までどおり）。
        """
        try:
            rom = self.rom_map(map_id)
        except Exception:                                        # noqa: BLE001
            rom = None
        width, height = getattr(rom, "width", None), getattr(rom, "height", None)
        if not width or not height:
            return rows, []
        inside, outside = [], []
        for n in rows:
            x, y = n.get("x"), n.get("y")
            if isinstance(x, int) and isinstance(y, int) and not (0 <= x < width and 0 <= y < height):
                outside.append(n["npc_id"])
            else:
                inside.append(n)
        return inside, outside

    def heard_now(self, map_id: int, npc: dict, phase=None) -> bool:
        """★いまの相手を聞いたか（★差し替え先の表から直した人は、いまの台詞で聞いたときだけ / RX3-0231）。"""
        return self.heard.is_heard(map_id, npc["npc_id"], phase,
                                   talk_id=npc.get("talk_id") if npc.get("variant") else None)

    def write_grid(self, map_id: int, opened=()) -> pathlib.Path | None:
        """★Lua の replan / 近づき直し用に通行可否の表を書く（★1 map 1 ファイル）。

        ★`opened` … この場で鍵を使って開けた扉の升（RX3-0263 / `(x, y)` / ★`O` で書く = Lua が通れる）。
        """
        rom = self.rom_map(map_id)
        if rom is None:
            return None
        GRID_DIR.mkdir(parents=True, exist_ok=True)
        path = GRID_DIR / ("grid_%03d.txt" % map_id)
        path.write_text(self.grid_text(rom, opened), encoding="utf-8")
        return path

    #: ★Lua の grid でカウンターを表す字（RX3-0182）。⚠ Lua の `passable` は P / C だけ通すので、通れないのは壁と同じ
    COUNTER_LETTER = "K"
    #: ★Lua の grid で「開けた扉」を表す字（RX3-0263 / ★Lua の `passable` が通す）。⚠ 閉じた扉は `D` のまま = 壁
    DOOR_OPEN_LETTER = "O"
    #: ★Lua の grid で「ダメージ床」を表す字（RX3-0277）。★Lua の `bfs` は先に H を通らずに探し、道が無ければ通る
    DAMAGE_LETTER = "H"

    @classmethod
    def grid_text(cls, rom: _pass.RomMap, opened=()) -> str:
        """★Lua が読む地図（★`RomMap.to_text` ＋ カウンターだけ `K` ＋ 開けた扉だけ `O` ＋ ダメージ床だけ `H`）。

        ⚠⚠ 2026-09-12 依頼者「カザーブの村のさかばで聞き込みできない ※カウンター越しでNPCが移動するパターン」:
          Lua の地図はカウンターを壁と同じ `B` で書くので、⚠ **カウンター越しに話せる**ことを Lua が知らなかった。
        ⚠ `RomMap.to_text` は変えない（★probe・検査が `B` を前提にしている）。

        ★★ 開けた扉（RX3-0263 / 2026-09-14）: ⚠ 以前は開けた後も `D`（壁）のままで、Lua の作り直し
          （近づき直し・ふさがれたときの replan）が開けた扉を通れず遠回りした（★Python の経路は鍵で扉を通るのに）。
          → ★この場で開けた扉（`opened`）だけ `O`（door_open）/ ⚠ 閉じた扉は `D`（door_closed）= 壁のまま。
          ⚠ 扉でない升は `opened` に来ても変えない（★覚え違いで壁を通さない）。
        """
        lines = rom.to_text().splitlines()
        done = {(int(x), int(y)) for x, y in (opened or ())}
        for y in range(rom.height):
            row = list(lines[y + 1])
            for x in range(rom.width):
                if _nav.is_counter(rom, x, y):
                    row[x] = cls.COUNTER_LETTER
                elif (x, y) in done and row[x] == "D":
                    row[x] = cls.DOOR_OPEN_LETTER
                elif row[x] == "P" and rom.damage(x, y) is not None:
                    row[x] = cls.DAMAGE_LETTER          # ★RX3-0277（⚠ `to_text` は P のまま）
            lines[y + 1] = "".join(row)
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # ★候補
    # ------------------------------------------------------------------
    @staticmethod
    def fixed_cells(npcs) -> set[tuple[int, int]]:
        """★固定の NPC が立っている升（★経路はここを通らない / RX3-0176）。

        ⚠⚠ 2026-09-12 依頼者「ロマリアかくとうじょうで聞き込みがきかない」: 受付の升を通る経路を出し、
        実機では 1 歩目で受付にぶつかって、7 人とも「経路ずれ」で飛ばしていた。
        ⚠ 動く NPC は入れない（★位置は歩くうちに変わる。塞がれたら Lua の replan に任せる）。
        """
        return {(n["x"], n["y"]) for n in npcs if n.get("movement") == "fixed"}

    def plan_to(self, map_id: int, start: tuple[int, int], npc: dict, others=(),
                *, keys=(), avoid=()) -> dict | None:
        """★NPC の隣（カウンター越し含む）へ BFS。⚠ 経路が無ければ None。

        ★`keys`（持っている道具 ID）を渡すと、⚠ **開けられる扉の向こう**も探します
        （RX3-0078）。⚠ 渡さなければ今までどおりです。
        ★`avoid`（固定の NPC の升 / `fixed_cells`）は通りません（RX3-0176）。
        """
        rom = self.rom_map(map_id)
        if rom is None:
            return None
        plan = _nav.plan(rom, tuple(start), (npc["x"], npc["y"]),
                         [tuple(o) for o in others], keys=keys, avoid=avoid)
        if plan is None:
            return None
        # ⚠ `keys` は Lua へ渡す**押すボタン**の意味で使っています（★名前が衝突している）。
        #   ★扉は `doors` で別に返します。
        return {"goal": list(plan["goal"]), "face": plan["final_face"], "keys": list(plan["path"]),
                "cells": [list(c) for c in plan["cells"]], "steps": len(plan["path"]),
                "doors": [list(d) for d in plan.get("doors") or ()],
                # ★避けられなかったダメージ床（RX3-0277）。⚠ 0 でなければ「回り込む道が無かった」
                "damage": int(plan.get("damage") or 0),
                "damage_cells": [list(c) for c in plan.get("damage_cells") or ()]}

    def exit_cells(self, map_id: int) -> list[tuple[int, int]]:
        """★★ その map の「外へ出られる升」（RX3-0341 / 2026-09-21）。

        ⚠⚠ **町の出入口は ROM の表にありません。** ★DQ3 の町は**端から歩いて出ます**
        （`map_graph` の `world_edge` が `x = None / y = None` なのはそのため）。
        → ★ここでは「外周のうち**歩ける**升」を出口とみなします。

        ⚠ 屋内（城の中など）は端がすべて壁なので**空**になります（★それが正しい）。
          ★実測: map 88（バラモスの城）は端へ 1 歩も行けません。
        """
        rom = self.rom_map(map_id)
        if rom is None:
            return []
        got = set()
        for x in range(rom.width):
            for y in (0, rom.height - 1):
                if rom.klass(x, y) == _pass.PASS:
                    got.add((x, y))
        for y in range(rom.height):
            for x in (0, rom.width - 1):
                if rom.klass(x, y) == _pass.PASS:
                    got.add((x, y))
        return sorted(got)

    def plan_to_exit(self, map_id: int, start: tuple[int, int], others=(),
                     *, keys=(), avoid=()) -> dict | None:
        """★★ いま居る升から**一番近い出口**への経路（RX3-0341）。⚠ 無ければ None。

        ⚠⚠ **覚えていなくても出口へ行けるようにするための道**です。

        ```text
        ★今まで  「入ってきた升」を動かしている間だけ覚える（`town_bar.note_entry`）
        ⚠ 困る    町の中でセーブを読むと**知らない** → ボタンが押せない（★依頼者の save3）
        ★これから 覚えが無ければ、⚠ 歩ける端のうち**一番近い升**を目的地にする
        ```

        ⚠ 端そのものに立っても外へは出ません（★出るのは**さらに 1 歩**）。
          → ★だから「出口まで連れて行く」で止まります（⚠ 勝手に町を出ない）。
        """
        cells = self.exit_cells(map_id)
        if not cells:
            return None
        # ⚠⚠ **もう端に立っているなら出しません**（★そこが出口 / 2026-09-21 の検査で見つけた）。
        #   ⚠ これが無いと「内側へ 1 歩戻って端を向く」道になります（★実測: map 9 の (0,0)）。
        if tuple(start) in set(cells):
            return None
        best = None
        for cell in cells:
            npc = {"x": cell[0], "y": cell[1]}
            try:
                plan = self.plan_to(map_id, start, npc, others, keys=keys, avoid=avoid)
            except Exception:                              # noqa: BLE001 ★地図が読めない
                continue
            if plan is None:
                continue
            if best is None or plan["steps"] < best["steps"]:
                best = dict(plan, cell=[cell[0], cell[1]])
        return best

    def known_reachable_facilities(self, map_id: int, time_byte, npc_tbl_hex, start) -> list[dict]:
        """★目的地リスト（指示書 §3-2 / §14）。★heard = true の施設 NPC だけ。★固定順（宿屋 → 道具屋 → 武器防具屋 → 教会）。"""
        cur = self.current_npcs(map_id, time_byte, npc_tbl_hex)
        if cur["status"] != "DEFAULT":
            return []
        others = [(n["x"], n["y"]) for n in cur["npcs"]]
        fixed = self.fixed_cells(cur["npcs"])               # ★人の上を通らない（RX3-0176）
        out = []
        for role in _master.ROLE_ORDER:
            for n in cur["npcs"]:
                if n["role"] != role or n["role_status"] != "CONFIRMED":
                    continue
                if not self.heard_now(map_id, n):
                    continue                                 # ★面識が無ければ出さない（§3-3）
                plan = self.plan_to(map_id, start, n, [o for o in others if o != (n["x"], n["y"])],
                                    avoid=fixed - {(n["x"], n["y"])})
                if plan is None:
                    continue
                out.append({"role": role, "label": _master.role_label(role), "npc": n, "plan": plan})
        return out

    def unheard_reachable_npcs(self, map_id: int, time_byte, npc_tbl_hex, start,
                               *, keys=(), phase=None, include_heard: bool = False) -> list[dict]:
        """★聞き込みの候補（指示書 §5-2）。★BFS 距離の近い順。⚠ 詳細は UI に出さない。

        ★`keys`（持っている道具 ID）を渡すと、⚠ **扉の向こうの人**も候補に入ります
        （RX3-0078 / ⚠ 城で 14 人中 5 人が扉の向こうだった）。
        ★`include_heard`（再聞き込み / RX3-0239）: 聞いたかは見ない（⚠ 話しかけない相手は今までどおり外す）。
        """
        cur = self.current_npcs(map_id, time_byte, npc_tbl_hex)
        if cur["status"] != "DEFAULT":
            return []
        others = [(n["x"], n["y"]) for n in cur["npcs"]]
        fixed = self.fixed_cells(cur["npcs"])               # ★人の上を通らない（RX3-0176）
        out = []
        for n in cur["npcs"]:
            if not hearing_target(n):
                continue                                     # ★talk_id = 0 / 話しかけない相手は対象外（§23 / RX3-0194）
            if not include_heard and self.heard_now(map_id, n, phase):
                continue                                     # ★目覚めた後は起きている時の会話だけ済み（RX3-0210）
            plan = self.plan_to(map_id, start, n, [o for o in others if o != (n["x"], n["y"])],
                                keys=keys, avoid=fixed - {(n["x"], n["y"])})
            if plan is None:
                continue                                     # ★今は辿り着けない → 今回は外す（heard = false は保つ / §6）
            out.append({"npc": n, "plan": plan, "distance": plan["steps"],
                        "damage": int(plan.get("damage") or 0)})
        # ★★ 毒の床を通るしかない相手は**後回し**（RX3-0277 / 2026-09-18 依頼者「毒の沼を超えて聞き込みにいく」）。
        #   ⚠⚠ 実測（テドンの夜 / `town_speed.log` 09:11）: 沼の向こうの 1 人へ **行き 24・帰り 22 = 46** 減っていた。
        #     ★近い順だけで並べると、途中でその人へ渡り、次の人のために**もう一度**渡ってくる。
        #   → ★渡る相手を最後にすれば、渡るのは 1 回で済む（⚠ 順番を変えるだけ。★行かないとは決めない）。
        out.sort(key=lambda r: (r["damage"] > 0, r["distance"], r["npc"]["npc_id"]))
        return out

    def counts(self, map_id: int, time_byte, npc_tbl_hex, phase=None) -> dict:
        """★内部の数（§22 / §23）: 全 NPC / talk 可能 / heard。⚠ UI に出すかは UI 側の判断。"""
        cur = self.current_npcs(map_id, time_byte, npc_tbl_hex)
        talkable = [n for n in cur["npcs"] if hearing_target(n)]
        heard = [n for n in talkable if self.heard_now(map_id, n, phase)]
        return {"npc_total": len(cur["npcs"]), "talkable": len(talkable), "heard": len(heard),
                "status": cur["status"]}

    # ------------------------------------------------------------------
    # ★heard
    # ------------------------------------------------------------------
    def npc_of_slot(self, map_id: int, time_byte, slot: int, npc_tbl_hex: str | None = None) -> dict | None:
        # ⚠ 候補と同じ表で引く（★差し替えのある map では実機の表が要る / RX3-0175）
        master = _master.master_for(map_id, time_byte, npc_tbl_hex)
        for n in master.get("npcs", []):
            if n.get("slot") == slot:
                return n
        return None

    def record_heard(self, map_id: int, time_byte, slot: int, talk_id: int, text: str | None,
                     at: str | None = None, npc_tbl_hex: str | None = None, phase: str | None = None,
                     npc: dict | None = None) -> dict | None:
        """★会話が開いた事実を heard へ。★本文は画面に出たものだけ（ROM の先読みは入れない）。

        ⚠ `npc` を渡すと `slot` は見ません（★手で話した会話は相手が **npc_id** で分かる / RX3-0282）。
        """
        if npc is None:
            npc = self.npc_of_slot(map_id, time_byte, slot, npc_tbl_hex)
        if npc is None:
            return None
        at = at or _dt.datetime.now().isoformat(timespec="seconds")
        self.heard.record(map_id, npc["npc_id"], talk_id, time="night" if _master.is_night(time_byte) else "day",
                          at=at, text=text, phase=phase)
        self.heard.save()
        return {"map_id": map_id, "npc_id": npc["npc_id"], "talk_id": talk_id, "talk_id_rom": npc["talk_id"],
                "match": talk_id == npc["talk_id"], "role": npc.get("role"), "appearance_id": npc["appearance_id"],
                "label": self.appearance_label(npc["appearance_id"]), "at": at}

    def record_heard_npc(self, map_id: int, time_byte, npc_id: int, text: str | None,
                         *, npc_tbl_hex: str | None = None, phase: str | None = None,
                         at: str | None = None) -> dict | None:
        """★**npc_id で**「聞いた」へ（RX3-0282 / 2026-09-18）。

        ⚠⚠ 手で話した会話では、聞き込み用の見張り（`$828B` の `last_talk`）は**立ちません**。
          ★そのかわり勇者メモが相手を決めています（`npc_in_front` → `npc_id` / RX3-0133）。
          → ★その `npc_id` をそのまま受け、⚠ **今の表に居ることだけ**確かめて書きます。

        ⚠ 台詞の番号は今の表の値を使います（★差し替え先の人 = `variant` の判定に要る / RX3-0231）。
        """
        cur = self.current_npcs(map_id, time_byte, npc_tbl_hex)
        if cur["status"] != "DEFAULT":
            return None
        npc = next((n for n in cur["npcs"] if int(n["npc_id"]) == int(npc_id)), None)
        if npc is None:
            return None
        return self.record_heard(map_id, time_byte, None, npc.get("talk_id"), text,
                                 at=at, npc_tbl_hex=npc_tbl_hex, phase=phase, npc=npc)

    #: ★向き（`$0644`）→ 進む向き（⚠ `nav_v0.lua` の `KEY_INDEX` と同じ並び）
    FACING_STEPS = {0: (0, -1), 1: (1, 0), 2: (0, 1), 3: (-1, 0)}
    #: ★何升先まで見るか。⚠ 店員は**カウンター越し**なので 1 升では届かない
    TALK_REACH = 2

    def appearance_in_front(self, npc_tbl_hex, appearance_hex, start, facing,
                            *, reach: int = TALK_REACH) -> dict | None:
        """★**表がどれか分からなくても**、正面に居る人の見た目だけは出す（RX3-0304 / 2026-09-20）。

        ## ⚠⚠ なぜ要るか

          ★依頼者「バラモスを倒した時、王様とイベントセリフを話すが、？になっている」。
          ⚠ 玉座（map 71）は NPC の表がどれとも合わず（`status = UNKNOWN`）、
            ★`npc_in_front` が `None` を返すので**話者が `？`** になっていました。

          ⚠ 表が分からない以上、★`npc_id` も `talk_id` も**決められません**（推測しない）。
          ★けれど「**どんな見た目の人か**」は実機の表から分かります。

        戻り値: `{"appearance_id", "label", "slot", "x", "y"}`。⚠ 分からなければ `None`。
        """
        step = self.FACING_STEPS.get(int(facing) % 4 if facing is not None else -1)
        if step is None or start is None or not appearance_hex:
            return None
        slots = _master.runtime_slots(npc_tbl_hex, appearance_hex)
        here = {(s.get("x"), s.get("y")): s for s in slots
                if s.get("appearance_id") is not None and not _master.is_hidden(s)}
        x, y = int(start[0]), int(start[1])
        for n in range(1, max(1, int(reach)) + 1):
            got = here.get((x + step[0] * n, y + step[1] * n))
            if got is None:
                continue
            return {"appearance_id": got["appearance_id"],
                    "label": self.appearance_label(got["appearance_id"]),
                    "slot": got.get("slot"), "x": got.get("x"), "y": got.get("y")}
        return None

    def npc_in_front(self, map_id: int, time_byte, npc_tbl_hex, start, facing,
                     *, reach: int = TALK_REACH):
        """★いま話している相手（⚠ 分からなければ `None`。★推測で決めない）。

        ⚠⚠ 手で話した会話は、これまで**相手が分からず**勇者メモが `？「…` でした
        （RX3-0133 / 2026-09-09 依頼者「老人と会話したが、勇者メモがハテナになっている」）。
        ★向き（`$0644`）と NPC の**いまの位置**（RAM 由来）が分かれば決まります。

        ```text
        1 升先   ★普通の人
        2 升先   ⚠ 店員（★カウンター越し。RX3-0053 で実機に確かめた形）
        ```

        ⚠ 途中に別の人が居たら、★手前の人を返します（そちらに話しかけているため）。
        """
        step = self.FACING_STEPS.get(int(facing) % 4 if facing is not None else -1)
        if step is None or start is None:
            return None
        cur = self.current_npcs(map_id, time_byte, npc_tbl_hex)
        if cur["status"] != "DEFAULT":
            return None
        here = {(n["x"], n["y"]): n for n in cur["npcs"]}
        x, y = int(start[0]), int(start[1])
        for n in range(1, max(1, int(reach)) + 1):
            got = here.get((x + step[0] * n, y + step[1] * n))
            if got is not None:
                return got
        return None

    def appearance_label(self, appearance_id: int) -> str:
        from dq3.testing import npc_sprites as _sp

        return _sp.label_for(appearance_id, self._labels)

    @staticmethod
    def memo_text(label: str, text: str) -> str:
        """★勇者メモの 1 行（指示書 §15-2）: `商「…」`。★先頭の `＊「` を見た目の字に置き換える。"""
        body = text.strip()
        if body.startswith("＊「"):
            body = body[2:]
        elif body.startswith("「"):
            body = body[1:]
        if not body.endswith("」"):
            body += "」"
        return "%s「%s" % (label, body)

    # ------------------------------------------------------------------
    # ★詳細画面の材料（指示書 §18-21）
    # ------------------------------------------------------------------
    def heard_timeline(self, map_ids=None) -> list[dict]:
        """★時系列（first_heard_at 昇順）。★同じ本文は最初の 1 件だけ（count を添える）。"""
        rows = []
        for key, convs in self.heard.conversations.items():
            map_id, npc_id = (int(v) for v in key.split("/"))
            if map_ids is not None and map_id not in map_ids:
                continue
            for c in convs:
                rows.append({"map_id": map_id, "npc_id": npc_id, "talk_id": c["talk_id"], "text": c["text"],
                             "count": c["count"], "first_heard_at": str(c["first_heard_at"]),
                             "last_heard_at": str(c["last_heard_at"]), "text_hash": c["text_hash"]})
        rows.sort(key=lambda r: (r["first_heard_at"], r["map_id"], r["npc_id"]))
        return rows

    def maps_with_heard(self) -> list[int]:
        return sorted({int(k.split("/")[0]) for k in self.heard.conversations})


def facility_order_key(role: str) -> int:
    try:
        return _master.ROLE_ORDER.index(role)
    except ValueError:
        return len(_master.ROLE_ORDER)


__all__ = ["TownService", "MAX_APPROACHES", "facility_order_key", "collections"]
