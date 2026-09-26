"""右画面の 1 行 UI: [ 街移動 ] [ 目的地 ▼ ] [ 聞き込み ]（RX3-0058 / 2026-09-02）。

## ★見せるもの / 見せないもの（指示書 §1 / §3-3 / §5-2）

```text
目的地リスト   heard = true の施設 NPC だけ（★面識ができるまで出さない）
聞き込み       未会話 / talk_id != 0 / 辿り着ける NPC を内部で近い順に回す（⚠ 相手の詳細は出さない）
```

## ★段取り

```text
UI → TownNavController → TownService（候補 / BFS）→ CommandWriter（navigate）→ Lua nav_v0
                       ← state.json の nav（局面 / 終わり方）/ last_talk（slot / talk_id）/ screen（会話の窓）
```

⚠ 「A を押した」を会話にしない。★`view_model` が窓の文を勇者メモに流したとき（`last_talk_text`）を会話とみなし、
  `$828B` の slot / talk_id と合わせて heard に記す。
⚠ UI は ROM / RAM の番地を知らない（★service だけを呼ぶ）。
"""
from __future__ import annotations

import time

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QToolButton, QWidget)

from dq3 import action_log as _AL
from dq3 import events as _EV
from dq3.knowledge.town_service import hearing_target

from . import icon_button

#: ★操作 → ログの名前（⚠ 置き場は `auto_env.SOURCE_OF` の 1 つ）
from .auto_env import SOURCE_OF as SOURCE_OF_MODE

#: ★会話の文が流れて来るのを待つ上限（秒）。★窓が閉じる → 画面の refresh で流れる
TALK_TEXT_WAIT_S = 6.0
#: ★閉じたかの確認を待つ上限（秒）
CLOSE_WAIT_S = 4.0
#: ⚠ 1 体に許す試行（★閉じないときに安全に止める）
MAX_TALK_RETRY = 1
#: ⚠ 鍵を使い終わるのを待つ上限（秒 / RX3-0159）。★実機では 400% で 5 秒ほど
ITEM_WAIT_S = 40.0
#: ⚠ 補充を待つ上限（秒）。★Lua が黙っても、画面は必ず終わる
RESTOCK_WAIT_S = 180.0
#: ★聞き込み中に実行環境（区間減速の倍率）を送り直す間隔（秒 / ★Turbo は Lua が持つ / RX3-0170）
KEEP_EVERY_S = 5.0
#: ★★ 街移動は施設の人の最初の台詞で高速化を解き、施設ごとに止める（RX3-0241 / ★Lua の nav_v0 が読む）
FIRST_MESSAGE = "first_message"
#: ★街移動がうまく終わった形 → 人の言葉（★first_message = 最初の台詞で止めた / inn_yes = 宿屋で はい まで）
MOVE_DONE_TEXT = {"talk_done": "★着きました", "arrived": "★着きました", FIRST_MESSAGE: "★着きました",
                  "inn_yes": "★宿屋に「はい」と答えました"}

#: ★★ 街移動のボタン（RX3-0257 / 2026-09-14 依頼者の小WI「街移動UIを1アクション化」）: (種類, 字, 正式な名前)
#:   ★押した時点で移動を始める（⚠ プルダウンも「移動」ボタンも置かない / ⚠ 施設ごとにボタンを増やさない）
#:   ★★ `entrance`（[入]）は**施設ではありません**（RX3-0291 / 2026-09-18 依頼者
#:     「自動移動に街の入口に移動を追加したい。文字は『入』かな。」）。
#:     ⚠⚠ 町の出入口は **ROM に升がありません**（★世界地図へは「端から出る」= `world_edge` で
#:       座標が `None` / `map_graph.arrival_cell` の註「町に入った升は表に無い」）。
#:     → ★**入ってきた升を覚えて**そこへ戻る（⚠ 覚えていなければ押せない / 推測で別の所へ行かない）。
MOVE_BUTTONS = (("inn", "宿", "宿屋"), ("item_shop", "道", "道具屋"),
                ("weapon_armor_shop", "武", "武器・防具屋"), ("church", "神", "教会"),
                # ⚠ 覚えが無いときは**出口**へ行きます（★町を出ます / RX3-0349）
                ("entrance", "入", "街の入口（覚えが無ければ出口へ / 町を出ます）"))

#: ★★ 種類 → アイコンの役割（RX3-0325 / ⚠ 絵の名前は `dq3/ui/icons.py` の表が正本）
#:   ⚠ ここは「どの種類にどの絵か」だけ。★絵そのものの場所は持ちません。
MOVE_ICONS = {"inn": "inn", "item_shop": "item_shop",
              "weapon_armor_shop": "weapon", "church": "church",
              "entrance": "entrance"}

#: ★[入] の種類（⚠ 施設の役割ではないので、名前を分けておく）
ENTRANCE_ROLE = "entrance"
ENTRANCE_LABEL = "街の入口"
#: ★★ 覚えが無いときの行き先（RX3-0349 / 2026-09-21 依頼者「save8 入ボタンで街から出てしまう」）。
#:
#:   ⚠⚠ `RX3-0341` で「★端に立っても町からは出ない」と書きましたが、**誤りでした**。
#:     ★歩ける端の升そのものが出口で、⚠ 踏むと町を出ます（依頼者の実機で確認）。
#:   → ★依頼者「別に出てもいいので、ツールチップを直してもOK」。
#:     ⚠ 動きは変えず、**名前を実態に合わせます**（★「入口」と言って外へ出さない）。
ENTRANCE_EXIT_LABEL = "街の出口（外に出ます）"
#: ⚠ 施設ではないので npc_id を持たない（★候補の並べ替えだけに使う番号）
ENTRANCE_NPC_ID = -1
#: ★移動中に次の候補へ切り替えてよい Lua の段（⚠ 話しかけた後 = talk / inn / close / after は今の施設を優先 / §5）
SWITCH_PHASES = ("clear", "walk", "wait_npc", "face")
#: ★切り替え: 止まってから位置が落ち着くまで待つ（秒 / ⚠ 歩きかけの升から経路を作ると「経路ずれ」で止まる）
SWITCH_SETTLE_S = 0.3
#: ⚠ 切り替え: 止まったと分かるまで待つ上限（秒 / ★Lua が黙っても画面は必ず終わる）
SWITCH_WAIT_S = 5.0

#: ★★ 聞き込みボタンのラベル（RX3-0239 / 依頼者の指示書 §3・§18）。⚠ ボタンは 1 つのまま（★2 つ並べない）
HEAR, REHEAR = "聞き込み", "再聞き込み"

#: ★★ ボタンに出す**1 文字**（RX3-0290 / 2026-09-18 依頼者「聞・再・補にしてサイズを稼ぎたい」）。
#:
#:   ⚠⚠ **名前のほうは変えません**（★記録・メッセージ・行動履歴は「聞き込み」のまま）。
#:     ★ここは「画面に出す字」だけの表です（⚠ 1 文字を台帳や `[HEARING]` の記録に混ぜない）。
#:   ★正式な名前はツールチップに出します（⚠ 1 文字だけでは何か分からないため / `RX3-0257` と同じ作法）。
BUTTON_LABEL = {HEAR: "聞", REHEAR: "再"}
#: ★実行中に出す字（⚠ 「停止」は 2 文字あって幅が揺れる）
STOP_LABEL = "止"
#: ★ツールチップの改行（⚠ 1 文字のボタンは説明が要る）
NEWLINE = chr(10)
#: ★補充のボタン（⚠ 名前は「補充」のまま）
RESTOCK_LABEL = "補"
HEAR_TIPS = {
    HEAR: "★まだ話していない人を近い順に回って話します\n実行中は「停止」になります",
    REHEAR: ("★この場所の人はもう全員聞いています。もう一度全員を回ります（★今までの記録は消しません）\n"
             "★同じ話はメモを増やさず、話し手が「？」なら埋めます。違う話は新しいメモにします\n"
             "実行中は「停止」になります"),
}

#: ⚠⚠ 右パネルの 1 行に収まる長さ（RX3-0102 / 依頼者 2026-09-07）
#:   ★「表示範囲を超えているのでメッセージはログで良い」
#:   ⚠ ただし**消しません**。★全文は行動履歴（`ActionSummary.detail`）に残ります。
STATUS_MAX = 24
#: ⚠ 「字の幅まで縮める」余白（`FIT_PADDING`）は `dq3/ui/icon_button.py` へ移しました
#:   （RX3-0325 / ★アイコンのぶんも足す必要が出たため、計算を 1 か所に寄せた）。

#: ★飛ばした理由 → 人の言葉（⚠ 内部の語をそのまま出さない）
SKIP_TEXT = {
    "unreachable_now": "到達不能",
    "skip_unreachable_now": "到達不能",
    "needs_key": "鍵が要る",
    "path_blocked": "通れず",
    "path_deviation": "経路ずれ",
    "face_moved": "相手が移動",
    "no_conversation": "会話失敗",
    "door_not_opened": "扉を開けられず",
    # ⚠⚠ RX3-0230: 話したのに heard に記せなかった（★表が読めない / slot が表に無い）
    "record_failed": "記録できず",
}

#: ★止まった理由 → 人の言葉
NAV_TEXT = {
    "path_blocked": "道がふさがっています",
    "path_deviation": "経路を見失いました",
    "face_moved": "相手が動きました",
    "skip_unreachable_now": "目的地へ到達できません",
    "unreachable_now": "目的地へ到達できません",
    "needs_key": "鍵が要ります",
    "no_conversation": "会話になりませんでした",
    # ★RX3-0157: 「うまくいきませんでした」では何が起きたか分からない（登録所の受付）
    "window_will_not_close": "会話の窓が閉じませんでした",
    # ★RX3-0170: 遭遇したら止める（★Lua がそのフレームで Turbo を切る / 依頼者 §15）
    "battle": "戦闘になりました",
    # ⚠⚠ RX3-0194: 「また すぐに たびだつ つもりか？」に答えられず、窓を開けたまま止めた（★B は押していない）
    "depart_question_unanswered": "「はい」で答えてください",
    # ⚠ RX3-0241: 宿屋の問いと確かめられない / はい／いいえ が出ない（★Lua は はい を押さずに止めた）
    "inn_question_unanswered": "宿屋の問いは人が答えてください",
    # ⚠ RX3-0273: 選択肢が 3 回開いた（★B = いいえ で聞き直す相手）。Lua は B をやめて止め、窓は開いたまま
    "choice_repeated": "選択肢が繰り返されました（「はい」で答えるか、手で閉じてください）",
}

#: ★終わり方 → ログと Lua に渡す語（`HEARING_DONE` など / 依頼者 §27）
END_WHY = {_AL.SUCCESS: "DONE", _AL.PARTIAL: "DONE", _AL.CANCELLED: "CANCEL"}


#: ★補充の目標（⚠ 人が決めるもの。★ここは既定値だけ / RX3-0066）
#:   ★RX3-0258（2026-09-14 依頼者）: やくそう 6・どくけしそう 2・キメラのつばさ 2・まんげつそう 2・せいすい 2。
#:   ★道具番号で持つ（⚠ 名前は ROM の道具辞書から / UI に名前を書かない）。⚠ 保存があれば保存を優先（★旧い既定のままの人もそのまま）
DEFAULT_WANTS = ((101, 6), (102, 2), (104, 2), (108, 2), (103, 2))


def parse_wants(text: str) -> list:
    """★`やくそう:6,どくけしそう:2` → `[(item_id, 個数), …]`。

    ⚠ 知らない名前は**黙って飛ばします**（★人の打ち間違いで補充ごと止めない）。
    ⚠⚠ ただし `0` 個は入れません（★「買わない」と同じ）。
    """
    from ..knowledge import item_info as II

    by_name = {}
    for item_id in range(0, 128):
        got = II.info(item_id)
        if got is not None and got.name:
            by_name.setdefault(got.name, item_id)
    out = []
    for chunk in (text or "").split(","):
        name, _, count = chunk.strip().partition(":")
        item_id = by_name.get(name.strip())
        try:
            n = int(count or 1)
        except ValueError:
            continue
        if item_id is not None and n > 0:
            out.append((item_id, n))
    return out


def restock_wants(settings=None) -> list:
    """★設定から目標を読む（⚠ 保存が無いときだけ既定 / RX3-0258: 既定は道具番号 `DEFAULT_WANTS`）。"""
    if settings is not None:
        got = settings.get("admin", "restock_wants", None)
        if isinstance(got, str) and got.strip():
            return parse_wants(got)
    return list(DEFAULT_WANTS)


def keep_gold(settings=None) -> int:
    """⚠ 残しておくお金（★宿代など）。"""
    if settings is None:
        return 0
    try:
        return max(0, int(settings.get("admin", "keep_gold", 0) or 0))
    except (TypeError, ValueError):
        return 0


class TownNavController:
    """★街移動 / 聞き込みの段取り。⚠ Qt を知らない（テストしやすいように）。"""

    def __init__(self, vm, service, commands, *, clock=time.time, env_hook=None,
                 action_log=None, writer=None) -> None:
        self.vm = vm
        self.service = service
        self.commands = commands
        self.clock = clock
        #: ★ユーザー向けの行動履歴（RX3-0109）。⚠ 画面へ直接書かない
        self.action_log = action_log if action_log is not None else _AL.shared()
        #: ★自動移動は共通 Event を通す（RX3-0154）。⚠ 聞き込み・補充は次の段階
        if writer is not None:
            self.writer = writer
        elif action_log is not None:
            self.writer = _EV.EventWriter(action_log=action_log)
        else:
            self.writer = _EV.shared()
        #: ★いま走っている 1 回（⚠ 終わりに 1 行だけ出す）
        self.run = None
        #: ★扉を開けている途中（RX3-0159）。⚠ None なら扉の段ではない
        self._door = None
        #: ★この聞き込みで開けた扉 `(map_id, x, y)`（⚠ ROM の地図は扉のまま）
        self._opened: set = set()
        self.item_seq = None
        #: ★目的地の人向けの名前（⚠ map_id や NPC ID は出さない）
        self.target_label = None
        #: ★実行環境（★Turbo ＋ 無音 / RX3-0170）。⚠ 聞き込みの判断には関わらない
        self.env_hook = env_hook
        self.mode: str | None = None          # None / "move" / "hearing"
        #: ★手で話した会話を最後に台帳へ書いたときの `last_talk`（RX3-0282 / ⚠ 立ち上がりで見る = 同じ会話で 2 度書かない）
        self._manual_talk: tuple | None = None
        self.seq: int | None = None            # ★いま Lua に頼んでいる navigate の seq
        self.target: dict | None = None
        self.skipped: set[int] = set()         # ★この聞き込みで飛ばした npc_id
        #: ★再聞き込み（RX3-0239）: 聞いたかを見ずに全員を回る / ★この回で話した npc_id（⚠ 同じ人を繰り返さない）
        self.rehear = False
        self.visited_now: set[int] = set()
        self.done_count = 0
        #: ★この 1 回で頼んだ歩数の合計（⚠ ユーザーへ出すサマリー用 / RX3-0110）
        self.steps = 0
        self.message = ""
        self._handled_seq: int | None = None
        self._waiting_since: float | None = None
        self._last_keep: float = float("-inf")     # ★最初の poll でまず送る
        self.log: list[dict] = []
        #: ★補充（RX3-0066 / RX3-0119）
        self.restock_wants: list = []          #: ★目標の数（⚠ 人が決める）
        self.keep_gold = 0                     #: ⚠ 残しておくお金
        self.plan = None                       #: ★いまの計画（⚠ 押す前に決めたもの）
        self.restock_params: dict | None = None
        self._restock_sent = False
        #: ★Lua の `town_speed.cancels`（人の B）をこの操作の頭で覚えた値（RX3-0170）
        self._cancels_seen: int | None = None
        #: ★この操作で Lua に街の頼みを出したか（⚠ 出していなければ town_end も送らない / RX3-0170）
        self._lua_touched = False
        #: ★街移動で施設の人の最初の台詞を見たか（RX3-0241 / ⚠ 速度・音を戻すのは 1 回だけ）
        self._first_seen = False
        #: ★同じボタンで候補を循環する（RX3-0257）: どの地図で / 種類ごとに前に選んだ npc_id
        self._cycle_map = None
        self._cycle_last: dict = {}
        #: ★移動中に次の候補へ切り替えている途中（RX3-0257 / ⚠ None なら切り替えていない）
        self._switch: dict | None = None
        #: ★町に入ってきた升（RX3-0291 / map_id → (x, y)）。⚠ 動かしている間だけ（★保存しない）
        self._entry: dict = {}
        #: ⚠ いま覚えている map（★変わった瞬間だけ「入ってきた升」を書く）
        self._entry_map = None

    # ------------------------------------------------------------------
    # ★材料（★state.json から / ⚠ 番地は知らない）
    # ------------------------------------------------------------------
    def party_keys(self) -> list[int]:
        """★パーティが持っている鍵の道具 ID（RX3-0078 / 2026-09-07）。

        ⚠⚠ **番地もビットの意味も、ここでは持ちません。**
        ★`item_info` に聞きます（`test_UIはROMの正解を読まない`:
        画面から `dq3rom` を直に触らない）。
        ⚠ 送られていなければ空（★推測で「持っている」ことにしない）。
        """
        from ..knowledge import item_info as II

        try:
            return II.keys_in(self.vm.equip_members())
        except Exception:                                        # noqa: BLE001
            return []                                             # ⚠ 読めないなら「持っていない」

    def _here(self):
        at = self.vm.position()
        from dq3.knowledge.seen_map import is_local

        if at is None or at[1] is None or not is_local(at[0]):
            return None
        here = {"map_id": int(at[1]), "x": at[2], "y": at[3],
                "time_byte": self.vm.time_byte(), "npc_tbl": self.vm.npc_table_hex()}
        # ★眠りの村の段階（RX3-0210 / ★目覚めた後は起きている時の会話だけ済み）。⚠ ほかの map は None
        from dq3.knowledge.story import AWAKE_ADDRESS, phase_of, state_key

        try:
            raw = self.vm._raw() if hasattr(self.vm, "_raw") else {}
        except Exception:                                    # noqa: BLE001
            raw = {}
        here["phase"] = phase_of(here["map_id"], (raw or {}).get(state_key(AWAKE_ADDRESS)))
        return here

    def note_manual_talk(self, made) -> dict | None:
        """★★ **手で**話した会話も「聞いた」台帳へ（RX3-0282 / 2026-09-18 依頼者「自前で聞き込みしたのが考慮されない」）。

        ⚠⚠ `RX3-0185`（2026-09-12）は「台帳へ書くと『聞き込み済み』になる」ので**書かない**と決めていた。
        ★依頼者の求めで判断を変えた（★手で聞いた人を、聞き込みが繰り返さない）。

        ## ⚠⚠ 2026-09-18 訂正: 相手は **勇者メモから受け取る**

        ★最初は `$828B` の見張り（`last_talk`）で相手を決めていました。⚠ **実機で 1 件も書けませんでした**
        （依頼者「話にいっている。ログも 2 つでている」）。

        ```text
        last_talk   ★聞き込み（nav_v0）が自分で押した会話のための見張り
                    ⚠ 手で話したときは立たない（★実測: 13:19:39 の手の会話で nil）
        勇者メモ     ★相手を既に決めている（npc_in_front = 向き＋NPC の位置 / RX3-0133）
                    ★memo 830 = {npc_id: 7, speaker: "馬"} ⚠ こちらを使えばよかった
        ```

        ⚠ 間違って「済み」にしないため、書くのは次が**全部そろったとき**だけ:

        ```text
        ① 会話の本文が取れた          ⚠ 「A を押した」だけでは書かない
        ② 勇者メモが相手を決めた       ★`npc_id` と `map_id`（⚠ 決まっていなければ書かない）
        ③ 自動の聞き込みが動いていない  ⚠ 動いていればあちらが書く（★二重に書かない）
        ④ 同じメモで 2 度目でない      ★`order` で見る（⚠ 同じ人にもう一度話したら書く）
        ⑤ いまも同じ場所にいる         ⚠ 別の map へ移った後に流れてきたメモは書かない
        ```

        ⚠ 断ったときも**理由を 1 行**残します（★次に「NG」と言われたら実機 1 回で分かるように）。

        戻り値: ★書けたら `record_heard` の結果（⚠ 書かなかったら `None`）。
        """
        def got(name, default=None):
            if isinstance(made, dict):
                return made.get(name, default)
            return getattr(made, name, default)

        if self.mode is not None:
            return None                                       # ③ ★あちらが書く（⚠ ログも出さない = 毎回出る）
        text = got("text")
        npc_id, map_id, order = got("npc_id"), got("map_id"), got("order")
        if not text:
            return self._manual_skip("no_text")               # ①
        if npc_id is None or map_id is None:
            return self._manual_skip("no_npc")                # ② ★誰に話したか決まっていない
        key = (map_id, npc_id, order)
        if key == self._manual_talk:
            return None                                       # ④
        here = self._here()
        if here is None or int(here["map_id"]) != int(map_id):
            return self._manual_skip("moved")                 # ⑤
        try:
            rec = self.service.record_heard_npc(int(map_id), here["time_byte"], int(npc_id), text,
                                                npc_tbl_hex=here.get("npc_tbl"), **self._phase_kw(here))
        except Exception as err:                              # noqa: BLE001 ★表が読めない / 相手が居ない
            return self._manual_skip("error %s" % err)
        self._manual_talk = key
        if rec is None:
            return self._manual_skip("not_in_table npc=%s" % npc_id)
        self._env_line("[HEARING] MANUAL map=%s npc=%s talk=%s"
                       % (map_id, rec.get("npc_id"), rec.get("talk_id")))
        return rec

    def _manual_skip(self, why: str) -> None:
        """⚠ 書かなかった理由を残す（★黙って None を返すと、実機で何も分からない）。"""
        self._env_line("[HEARING] MANUAL-SKIP why=%s" % why)
        return None

    @staticmethod
    def _phase_kw(here) -> dict:
        """★段階を渡す（RX3-0210）。⚠ 眠りの村でなければ渡さない（★段階を知らない service もそのまま動く）。"""
        return {"phase": here["phase"]} if (here or {}).get("phase") else {}

    def note_entry(self) -> None:
        """★★ 町に**入ってきた升**を覚える（RX3-0291 / 2026-09-18）。

        ⚠⚠ 町の出入口は ROM に升がありません（★端から出る形）。★だから覚えるしかない。

        ```text
        map が変わった      ★そのとき立っている升を「入ってきた升」にする
        世界地図へ出た      ★忘れる（⚠ 次に入ったら覚え直す）
        同じ map で歩いた   ⚠ 上書きしない（★入口はそのまま）
        ```

        ⚠ 覚えるのは**動かしている間だけ**です（★保存しません）。
          町の中でセーブを読んだときは分からない → ★ボタンを押せなくします（⚠ 別の所へ行かない）。
        ⚠ 0.5 秒ごとに見ているので、★1〜2 升ぶん内側になることがあります（⚠ 端のすぐそば）。
        """
        here = self._here()
        if here is None:
            self._entry_map = None
            return
        map_id = int(here["map_id"])
        if map_id != self._entry_map:
            self._entry_map = map_id
            self._entry[map_id] = (int(here["x"]), int(here["y"]))

    def entry_cell(self, map_id):
        """★その map で覚えている「入ってきた升」。⚠ 知らなければ None。"""
        return self._entry.get(int(map_id)) if map_id is not None else None

    def facilities(self) -> list[dict]:
        here = self._here()
        if here is None:
            return []
        got = self.service.known_reachable_facilities(here["map_id"], here["time_byte"], here["npc_tbl"],
                                                      (here["x"], here["y"]))
        entrance = self._entrance_candidate(here)
        return got + ([entrance] if entrance is not None else [])

    def _entrance_candidate(self, here) -> dict | None:
        """★[入] の候補（⚠ もう居る / 道が無い なら None）。

        ## ⚠⚠ 覚えが無くても出口へ行けます（RX3-0341 / 2026-09-21）

        ★依頼者「save3 自動移動で出口に出れない」。⚠ 原因は `note_entry` が
        **動かしている間しか覚えない**ことでした（★町の中でセーブを読むと分からない）。

        ```text
        ① ★入ってきた升を覚えている  → そこへ（⚠ 今までどおり）
        ② ⚠ 覚えていない            → ★歩ける端のうち**一番近い升**へ
        ③ ⚠ どの端へも行けない       → None（★屋内。⚠ ボタンは出さない）
        ```

        ⚠⚠ **②は町を出ます**（RX3-0349 / 2026-09-21）。
          ★`RX3-0341` では「端に立っても出ない」と書きましたが、⚠ **誤りでした**
          （★依頼者の save8 で実機確認）。歩ける端の升そのものが出口です。
          → ★動きは変えず、**名前を分けます**（⚠ 「入口」と言って外へ出さない）。
        """
        at = (int(here["x"]), int(here["y"]))
        cell = self.entry_cell(here["map_id"])
        if cell is not None and at != cell:
            npc = {"x": cell[0], "y": cell[1], "npc_id": ENTRANCE_NPC_ID}
            try:
                plan = self.service.plan_to(here["map_id"], at, npc)
            except Exception:                                # noqa: BLE001 ★地図が読めない
                plan = None
            if plan is not None:
                return {"role": ENTRANCE_ROLE, "label": ENTRANCE_LABEL,
                        "npc": npc, "plan": plan}
        # ⚠⚠ **端を探すのは「町だと分かっている」ときだけ**（RX3-0355 / 2026-09-21 依頼者
        #   「特にダンジョンはこの機能は一旦凍結させたい」）。
        #   ★ダンジョンでは端まで歩いても出口とは限らず、⚠ **迷い込ませるだけ**です。
        #   ⚠ 「分からない」ときも出しません（★安全側 / 推測で町だと決めない）。
        #   ★覚えている升（①）は**どこでも**使えます（⚠ 実際に通った升なので確かです）。
        if not self._town_like(here["map_id"]):
            return None
        try:
            plan = self.service.plan_to_exit(here["map_id"], at)
        except Exception:                                    # noqa: BLE001
            return None
        if plan is None:
            return None
        got = plan.get("cell") or plan.get("goal")
        npc = {"x": int(got[0]), "y": int(got[1]), "npc_id": ENTRANCE_NPC_ID}
        # ⚠ ここは「入口」ではなく**出口**です（★踏むと町を出ます / RX3-0349）
        return {"role": ENTRANCE_ROLE, "label": ENTRANCE_EXIT_LABEL, "npc": npc, "plan": plan}

    def _town_like(self, map_id) -> bool:
        """★その map が「町のたぐい」と分かっているか（RX3-0355）。

        ⚠ 判定そのものは `location_book.is_town_like` の 1 か所（★ここには写さない）。
        ⚠ 台帳が無い / 読めないときは **false**（★安全側 = ボタンを出さない）。
        """
        book = getattr(self.vm, "location_book", None)
        if book is None or not hasattr(book, "is_town_like"):
            return False
        try:
            return bool(book.is_town_like(map_id))
        except Exception:                                    # noqa: BLE001
            return False

    def candidates(self, role: str, facilities=None) -> list[dict]:
        """★その種類の施設の候補（RX3-0257）。★NPC 番号の順（★台帳の固定の番号 = 起動ごとに変わらない）。

        ⚠ 距離の順にしない（★今いる所で順番が変わると、押すたびの行き先が読めない / 指示書 §4）。
        ⚠ 出すのは今までどおり「面識があり、今いる所から辿り着ける」施設だけ（★No-Spoiler / RX3-0058 §3-3）。
        """
        got = [f for f in (self.facilities() if facilities is None else facilities) if f["role"] == role]
        return sorted(got, key=lambda f: int(f["npc"]["npc_id"]))

    def upcoming(self, role: str, got: list, map_id) -> int:
        """★次に押したら何番目へ行くか（1 から / ⚠ 覚えは変えない / ツールチップにも使う）。"""
        last = (self._cycle_last if self._cycle_map == map_id else {}).get(role)
        if last is not None:
            for i, f in enumerate(got):
                if int(f["npc"]["npc_id"]) > last:
                    return i + 1
        return 1

    def _next_candidate(self, role: str, got: list, map_id) -> dict:
        """★前に選んだ候補の次（★循環: A → B → A / 指示書 §3）。⚠ 地図が変わったら先頭から。"""
        pick = got[self.upcoming(role, got, map_id) - 1]
        if self._cycle_map != map_id:
            self._cycle_map, self._cycle_last = map_id, {}
        self._cycle_last[role] = int(pick["npc"]["npc_id"])
        return pick

    def busy(self) -> bool:
        return self.mode is not None

    # ------------------------------------------------------------------
    # ★頼む
    # ------------------------------------------------------------------
    def _navigate(self, here, plan, *, talk: bool, npc=None, close=None, facility=None, stop_at=None) -> bool:
        # ★この場で開けた扉を地図へ（RX3-0263 / ★Lua の作り直しが開けた扉を通れる）。⚠ 無ければ今までどおりの呼び方
        opened = [(x, y) for (m, x, y) in self._opened if m == here["map_id"]]
        grid = (self.service.write_grid(here["map_id"], opened=opened) if opened
                else self.service.write_grid(here["map_id"]))
        params = {"keys": ",".join(plan["keys"]), "cells": ",".join("%d:%d" % (c[0], c[1]) for c in plan["cells"]),
                  "face": plan["face"] or "", "talk": "1" if talk else "0",
                  # ⚠ 補充は**窓を閉じない**（★店の窓を開けたまま Lua へ渡す / RX3-0119）
                  "close": "1" if (talk if close is None else close) else "0",
                  "grid": str(grid).replace("\\", "/") if grid else "",
                  "npc_slot": str(npc["slot"]) if (npc and npc.get("movement") == "random" and npc.get("slot") is not None) else "-1"}
        if stop_at:
            # ★★ 施設の人の最初の台詞で高速化を解き、施設ごとに止める（RX3-0241 / ★街移動だけ）
            params["stop_at"] = stop_at
            params["facility"] = facility or ""
        if talk and (params["close"] == "1" or (stop_at and facility == "inn")):
            # ★★ 聞き込み: 「また たびだつか」に はい で答えるためのタイル（RX3-0194）。
            # ★★ 宿屋への街移動（RX3-0241）: 泊まるかの問いに はい で答えるのにも同じタイルを使う。
            #   ⚠ 渡せなければ Lua は窓を見つけられず、**A を押さずに**止まる（★B も押さない）
            getter = getattr(self.service, "depart_answer_params", None)
            if callable(getter):
                try:
                    params.update(getter() or {})
                except Exception:                                # noqa: BLE001
                    pass
        params.update(self._env_params())
        try:
            self.seq = self.commands.send("navigate", **params)
            self._lua_touched = True
        except (OSError, ValueError) as err:
            # ⚠⚠ 2026-09-07（RX3-0104）: ここで **`return False` だけ**していました。
            #   ★`mode` が残ったまま `_finish()` を通らないので、
            #   ⚠ 400% ・無音のまま**戻ってこない**道でした。
            self._finish("⚠ 頼めませんでした", status=_AL.FAILED, reason="command_failed")
            return False
        self._handled_seq = None
        self._waiting_since = None
        self.steps += int(plan.get("steps") or 0)
        self.log.append({"at": self.clock(), "seq": self.seq, "mode": self.mode, "steps": plan["steps"],
                         "npc_id": npc["npc_id"] if npc else None, "talk": talk})
        return True

    def start_move(self, role: str) -> bool:
        """★街移動: 面識のある施設へ歩き、着いたら話しかける（★A → はなす まで / 窓は開けたまま）。

        ⚠⚠ 2026-09-12 依頼者「街移動したらAボタン押したい（コマンド実行まで自動）」（RX3-0197）:
          ★以前は「A は押さない」（指示書 §4）でした。★補充（RX3-0119）と同じ `talk=True, close=False` にし、
          ★店員・宿の人の窓を開けたまま人へ返します（⚠ 閉じると B が「いいえ」になる）。

        ⚠⚠ 2026-09-13 依頼者の小WI（RX3-0241 / `docs/design/dq3-facility-stop-spec.md`）:
          ★施設の人の**最初の台詞**で高速化を解き（Lua）、速度・音を開始前へ戻す（`_note_first_message`）。
          ★宿屋は泊まるかの問いに はい まで / 道具屋・武器防具屋・教会は最初の台詞で止める（⚠ 用途は選ばない）。
        """
        here = self._here()
        if here is None:
            self.message = "⚠ 町の中でだけ使えます"
            return False
        got = self.candidates(role)
        if not got:
            self.message = "⚠ %s はまだ知りません" % role
            return False
        # ★同じ種類が複数なら、押すたびに次の候補（RX3-0257 / ★1 軒なら毎回同じ施設）
        pick = self._next_candidate(role, got, here["map_id"])
        self.mode = "move"
        self._set_move_target(role, pick, got)
        self.steps = 0
        self.run = self.action_log.begin("move")
        self._emit(_EV.NAVIGATION_START, {"destination": self.target_label})
        # ★街移動も同じ実行環境で（2026-09-02 依頼者）
        #   ⚠ 2026-09-11（RX3-0170）: **Turbo ＋ 無音**（旧 400%）。★終わりに開始前へ戻す
        self._env_line("[MOVE] START destination=%s" % self.target_label)
        self._begin_env("move")
        self._first_seen = False
        if role == ENTRANCE_ROLE:
            # ★入口は**人ではない**（⚠ 話しかけない / 窓も開かない / 升は踏まず手前で止まる）
            return self._navigate(here, pick["plan"], talk=False, close=False)
        return self._navigate(here, pick["plan"], talk=True, npc=pick["npc"], close=False,
                              facility=role, stop_at=FIRST_MESSAGE)

    def _set_move_target(self, role: str, pick: dict, got: list) -> None:
        """★いま向かう施設（★同じ種類が複数なら「道具屋 2/2」/ RX3-0257 §7）。"""
        index = got.index(pick) + 1
        label = pick["label"] if len(got) <= 1 else "%s %d/%d" % (pick["label"], index, len(got))
        self.target = {"npc": pick["npc"], "label": label, "role": role, "index": index, "count": len(got)}
        self.target_label = label
        self.message = "★%s へ" % label

    def request_move(self, role: str) -> bool:
        """★[宿][道][武][神] を押した（RX3-0257 / 依頼者の小WI「街移動UIを1アクション化」）。

        ```text
        止まっている     ★その種類の次の候補へ移動を始める（★1 軒なら毎回同じ施設）
        移動中           ★次の候補へ切り替える（⚠ 施設の人と話し始めた後は今の施設を優先 / §5）
        聞き込み・補充   ⚠ 受けない
        ```
        """
        if self.mode is None:
            return self.start_move(role)
        if self.mode != "move":
            return False
        return self._switch_move(role)

    def _switch_move(self, role: str) -> bool:
        """★移動中に押した → 次の候補へ（RX3-0257 §5）。

        ⚠⚠ 頼みの置き場は 1 つ（★続けて送ると上書き）。⚠ 経路は state.json の位置から作るので、
          歩いている最中に作ると出発点が遅れ、Lua が「経路ずれ」で止まる。→ ★止めてから、止まった所で作り直す:

        ```text
        Lua がまだ受け取っていない    ★頼みを差し替える（★まだ 1 歩も歩いていない）
        歩いている（clear〜face）      ★nav_stop → 止まって位置が落ち着いたら次の候補へ（`_poll_switch`）
        話し始めた・最初の台詞の後     ⚠ 切り替えない（★誤操作防止 / 指示書 §5）
        ```

        ⚠ 速度・音はそのまま（★1 回の街移動のまま / 終わりに開始前へ戻す）。
        """
        if self._switch is not None:
            self.message = "★切り替えています"
            return False
        nav = self.vm.nav_status() or {}
        started = nav.get("seq") == self.seq
        if self._first_seen or (started and nav.get("phase") not in SWITCH_PHASES):
            self.message = "★施設の人と話しています"
            return False
        here = self._here()
        got = self.candidates(role) if here is not None else []
        if not got:
            return False
        pick = self._next_candidate(role, got, here["map_id"])
        if ((self.target or {}).get("npc") or {}).get("npc_id") == pick["npc"]["npc_id"]:
            return True                      # ★1 軒だけ → そのまま歩き続ける（★同じ施設へ / §2）
        if not started:
            self._set_move_target(role, pick, got)
            self._env_line("[MOVE] SWITCH destination=%s" % self.target_label)
            return self._navigate(here, pick["plan"], talk=True, npc=pick["npc"], close=False,
                                  facility=role, stop_at=FIRST_MESSAGE)
        try:
            self.commands.send("nav_stop")
        except (OSError, ValueError):
            return False
        self._switch = {"role": role, "npc_id": pick["npc"]["npc_id"], "asked": self.clock(),
                        "stopped": False, "pos": None, "since": None}
        self.message = "★%s へ切り替えます" % pick["label"]
        return True

    def _poll_switch(self) -> bool:
        """★止める頼みの後（RX3-0257）: Lua が止まり、位置が落ち着いたら次の候補へ歩き直す。戻り値: この poll を使ったか。"""
        sw = self._switch
        now = self.clock()
        if not sw["stopped"]:
            nav = self.vm.nav_status() or {}
            if nav.get("seq") == self.seq and not nav.get("active") and nav.get("phase") == "done":
                if nav.get("reason") != "stopped_by_user":
                    self._switch = None      # ★止める前に終わった（着いた・戦闘など）→ いつもの終わり方へ
                    return False
                if nav.get("talk_frame") is not None:
                    # ⚠ 止める頼みが届く前に話し始めていた（★窓が開いているかもしれない）→ 人へ返す
                    self._switch = None
                    self._handled_seq = self.seq
                    self._finish("⚠ 話し始めていたので切り替えませんでした", status=_AL.CANCELLED,
                                 reason="switch_too_late")
                    return True
                sw["stopped"] = True
            elif now - sw["asked"] > SWITCH_WAIT_S:
                self._switch = None
                self._finish("⚠ 切り替えられませんでした", status=_AL.FAILED, reason="switch_timeout")
                return True
            else:
                return True
        here = self._here()
        pos = (here["x"], here["y"]) if here is not None else None
        if pos != sw["pos"]:
            sw["pos"], sw["since"] = pos, now       # ⚠ まだ動いている（★歩きかけの升から作らない）
            return True
        if now - sw["since"] < SWITCH_SETTLE_S:
            return True
        self._switch = None
        got = self.candidates(sw["role"]) if here is not None else []
        pick = next((f for f in got if f["npc"]["npc_id"] == sw["npc_id"]), None)
        if pick is None:
            self._handled_seq = self.seq
            self._finish("⚠ 次の施設へ行けません", status=_AL.FAILED, reason="switch_unreachable")
            return True
        self._set_move_target(sw["role"], pick, got)
        self._env_line("[MOVE] SWITCH destination=%s" % self.target_label)
        self._first_seen = False
        self._navigate(here, pick["plan"], talk=True, npc=pick["npc"], close=False,
                       facility=sw["role"], stop_at=FIRST_MESSAGE)
        return True

    def start_restock(self, role: str = "item_shop") -> bool:
        """★補充（RX3-0066 / RX3-0119）。⚠ **押す前に計画を全部決める**。

        ```text
        1 いまの持ち物と所持金 → 計画
        2 ⚠ 買うものが無ければ**歩きもしない**（★1 行だけ出して終わる）
        3 店主まで歩いて話す（⚠ 窓は閉じない）
        4 `restock` を頼む（★窓の操作は Lua）
        ```
        """
        from ..knowledge import item_info as II
        from ..knowledge import restock as RS

        here = self._here()
        if here is None:
            self.message = "⚠ 町の中でだけ使えます"
            return False
        got = self.candidates(role)
        if not got:
            self.message = "⚠ %s はまだ知りません" % role
            return False
        # ★★ 同じ種類の店が 2 軒ある町（RX3-0257）: 話が出ている方の店から買う（⚠ 先頭の店へ歩きに行かない）
        talking = next((f for f in got if self._shop_talk_open(f["npc"])), None)
        if talking is not None:
            got = [talking] + [f for f in got if f is not talking]
        # ★品揃えもその店の人のもの（⚠ 2 軒で品が違う）
        shop = II.shop_of_npc(II.shops_by_map().get(here["map_id"], []), role, got[0]["npc"].get("talk_id"))
        if shop is None:
            self.message = "⚠ 品揃えが分かりません"
            return False
        members = self.vm.equip_members()
        plan = RS.build_plan(members, shop.items, self.restock_wants,
                             gold=self.vm.gold() or 0, keep_gold=self.keep_gold)
        self.plan = plan
        self.target_label = got[0]["label"]
        # ⚠⚠ 買うものが無ければ、★**ボタンを 1 つも押しません**（歩きもしない）
        if plan.is_empty():
            self.run = self.action_log.begin("restock")
            self.mode = "restock"
            self._finish(plan.summary(), status=_AL.CANCELLED, reason=plan.stop)
            return False
        self.mode = "restock"
        self.target = {"npc": got[0]["npc"], "label": got[0]["label"]}
        self.message = "★%s へ" % got[0]["label"]
        self.steps = 0
        self.restock_params = RS.to_params(plan, members)
        self._restock_sent = False
        self.run = self.action_log.begin("restock")
        self._begin_env("restock")
        if self._shop_talk_open(got[0]["npc"]):
            # ★★ パターン B（RX3-0241 §4）: 店の人の話がもう画面に出ている（★街移動が最初の台詞で止めた）
            #   → ★話しかけ直さず、その会話から買う（⚠ 購入のロジックは今までと同じ restock）。
            #   ⚠ 歩く頼みを出すと、歩き出す前の B で店の窓を閉じてしまう（★B = いいえ）
            self._env_line("[RESTOCK] FROM_TALK shop=%s" % got[0]["label"])
            return self._send_restock()
        return self._navigate(here, got[0]["plan"], talk=True, npc=got[0]["npc"],
                              close=False)

    def hearing_kind(self, here=None) -> str:
        """★いま押したら「聞き込み」か「再聞き込み」か（RX3-0239 / 指示書 §3・§18）。

        ★話しかける相手（talk_id > 0 / 王様などを除く）が 1 人以上いて、全員聞き終えていれば「再聞き込み」。
        ★★ 未聴の人が残っていても、**いま辿り着ける未聴の人が 0 人**で、聞いた人が 1 人以上いれば「再聞き込み」（RX3-0247）。
          ⚠⚠ 2026-09-13 依頼者「ジパングで再聞き込みが効かない save3」: 22 人中 20 人を聞き、残る 2 人（卑弥呼の奥 (18,92)・(18,93)）は
            辿り着けない → ⚠ ずっと「聞き込み」のまま、押すと 0 人で終わり、再聞き込みに入れなかった。
        ⚠ 表が読めない・町の外は「聞き込み」。
        """
        here = here if here is not None else self._here()
        if here is None:
            return HEAR
        try:
            got = self.service.counts(here["map_id"], here["time_byte"], here["npc_tbl"], here.get("phase"))
        except Exception:                                        # noqa: BLE001
            return HEAR
        if got.get("status") != "DEFAULT" or got.get("talkable", 0) <= 0:
            return HEAR
        if got.get("heard", 0) >= got["talkable"]:
            return REHEAR
        if got.get("heard", 0) > 0 and not self._reachable_unheard(here):
            return REHEAR
        return HEAR

    def _reachable_unheard(self, here) -> bool:
        """★いま辿り着ける未聴の人がいるか（RX3-0247 / ★聞き込みと同じ探し方: 鍵・段階も同じ）。

        ★画面は 0.5 秒ごとにラベルを作り直すので、同じ場所・同じ表・同じ聞いた数では前の答えを使う。
        ⚠ 探せなければ「いる」（★今までどおり「聞き込み」）。
        """
        try:
            heard = self.service.counts(here["map_id"], here["time_byte"], here["npc_tbl"], here.get("phase")).get("heard")
        except Exception:                                        # noqa: BLE001
            return True
        key = (here["map_id"], here["time_byte"], here["npc_tbl"], here["x"], here["y"], here.get("phase"), heard,
               tuple(self.party_keys()))
        cached = getattr(self, "_reach_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            got = bool(self.service.unheard_reachable_npcs(here["map_id"], here["time_byte"], here["npc_tbl"],
                                                           (here["x"], here["y"]), keys=self.party_keys(),
                                                           **self._phase_kw(here)))
        except Exception:                                        # noqa: BLE001
            return True
        self._reach_cache = (key, got)
        return got

    def start_hearing(self) -> bool:
        """★聞き込み: 未会話 NPC を近い順に回る（指示書 §5 / §7）。

        ★全員聞き終えていれば「再聞き込み」（RX3-0239）: 聞いたかを見ずに全員を回る（⚠ 履歴は消さない）。
        """
        here = self._here()
        if here is None:
            self.message = "⚠ 町の中でだけ使えます"
            return False
        self.rehear = self.hearing_kind(here) == REHEAR
        self.visited_now = set()
        self.mode = "hearing"
        self.skipped = set()
        self.done_count = 0
        self.steps = 0
        self.target_label = None
        self.log = []                         # ⚠ 前回の skip を今回の内訳に混ぜない
        self._door, self._opened = None, set()   # ★RX3-0159
        self.run = self.action_log.begin("hearing")
        self._env_line("[HEARING] START" + (" rehear" if self.rehear else ""))
        self._begin_env("hearing")
        return self._next_target()

    def _begin_env(self, what: str) -> None:
        """★実行環境（Turbo ＋ 無音 / RX3-0170）に入る。⚠ 失敗しても処理は続ける。"""
        self._cancels_seen = None
        self._lua_cancelled()                    # ★いまの「人の B」の数を覚える（⚠ 前の操作の分で止めない）
        if self.env_hook is None:
            return
        try:
            self.env_hook.begin(what)
        except Exception:                                        # noqa: BLE001
            pass

    def _env_params(self) -> dict:
        """★街の頼みに添える Turbo の項目（RX3-0170 / ★Lua の `town_speed.lua` が読む）。

        ⚠ Turbo の入り切りを別の頼みにしない（★置き場が 1 つなので、直後の頼みに上書きされる）。
        """
        if self.env_hook is None or not hasattr(self.env_hook, "params"):
            return {}
        try:
            return dict(self.env_hook.params(self.mode))
        except Exception:                                        # noqa: BLE001
            return {}

    def _env_line(self, text: str) -> None:
        """★ログへ 1 行（`[HEARING] START` など / 依頼者 §27）。⚠ 落ちても続ける。"""
        if self.env_hook is None or not hasattr(self.env_hook, "line"):
            return
        try:
            self.env_hook.line(text)
        except Exception:                                        # noqa: BLE001
            pass

    def _note_first_message(self, nav) -> None:
        """★★ 施設の人の最初の台詞が出た → 速度・音を開始前へ戻す（RX3-0241）。⚠ 1 回だけ。

        ★Lua は同じフレームで Turbo を切っています（`town_speed.first_message`）。ここは画面の持ち分
        （区間減速の倍率・無音）。⚠ 宿屋はこのあとも Lua が はい まで進めるので、終わりを待たずに戻す。
        """
        if self._first_seen or not nav.get("first_message"):
            return
        self._first_seen = True
        self._env_line("[MOVE] FIRST_MESSAGE facility=%s" % (nav.get("facility") or "?"))
        if self.env_hook is not None and hasattr(self.env_hook, "release"):
            try:
                self.env_hook.release(self.mode)
            except Exception:                                    # noqa: BLE001
                pass

    def _shop_talk_open(self, npc) -> bool:
        """★★ 店の人の話がもう画面に出ているか（RX3-0241 §4 パターン B）。

        ★会話の窓が出ていて、最後に話した相手（`$828B` の talk_id）がこの店の人。
        ⚠ 分からなければ False（★今までどおり歩いて話す = パターン A）。
        """
        try:
            if not self.vm.conversation_open_now():
                return False
            talk = self.vm.last_talk() or {}
        except Exception:                                        # noqa: BLE001
            return False
        tid = talk.get("talk_id")
        return isinstance(tid, int) and tid != 0 and tid == (npc or {}).get("talk_id")

    def _send_restock(self) -> bool:
        """★Lua に買い物を頼む（★窓の操作は Lua / 着いた後もパターン B もここ）。"""
        try:
            self.commands.send("restock", **dict(self.restock_params or {}, **self._env_params()))
            self._lua_touched = True
        except (OSError, ValueError) as err:
            self._finish("⚠ 頼めませんでした", status=_AL.FAILED, reason=str(err))
            return False
        self._restock_sent = True
        self._waiting_since = self.clock()
        self.message = "★買っています"
        return True

    def _next_target(self) -> bool:
        here = self._here()
        if here is None:
            self._finish("⚠ 場所が読めません", status=_AL.FAILED)
            return False
        cands = [c for c in self.service.unheard_reachable_npcs(here["map_id"], here["time_byte"], here["npc_tbl"],
                                                                  (here["x"], here["y"]),
                                                                  keys=self.party_keys(),
                                                                  **self._rehear_kw(),
                                                                  **self._phase_kw(here))
                 if c["npc"]["npc_id"] not in self.skipped and c["npc"]["npc_id"] not in self.visited_now]
        if not cands:
            # ⚠⚠ 2026-09-05（RX3-0077）: 候補が尽きても、**まだ話していない人が残っている**ことがある
            #   （★扉の向こうなど、BFS が辿り着けない相手。セーブ 5 の城で 14 人中 5 人）。
            #   ★以前は黙って「聞き込み完了」と出していた → 依頼者には「反映されない」に見えた。
            #   → ★残った人を skip（unreachable_now）として記録し、⚠ 件数を文に出す。
            left = self._left_unheard(here)
            # ★鍵を持っていたら届く人が居るか（⚠ 「鍵が要る」と理由を出すため / RX3-0078）
            with_keys = self._reachable_with_all_keys(here, left)
            for npc in left:
                why = "needs_key" if npc["npc_id"] in with_keys else "unreachable_now"
                self.skipped.add(npc["npc_id"])
                self.log.append({"at": self.clock(), "skip": npc["npc_id"], "reason": why,
                                 "xy": [npc.get("x"), npc.get("y")]})
            # ⚠⚠ 2026-09-07（RX3-0102）依頼者:
            #   「OK だが、表示範囲を超えているのでメッセージはログで良いと思う」
            #   ★画面は**件数だけ**（⚠ 「何人に行けなかったか」は残す / 依頼者の指示）。
            #   ★内訳（扉の向こう・会話失敗…）は行動履歴の 1 行へ。
            missed = len(self.skipped)
            short = "%s完了 %d人" % (REHEAR if self.rehear else HEAR, self.done_count)
            if missed:
                short += " / 未完%d人" % missed
            elif self.done_count == 0:
                # ★★ 0 人のときは**なぜ 0 人か**を言う（RX3-0157 / 依頼者 2026-09-11）。
                #   ⚠ 「聞き込み完了 0人」では、壊れたのか、もう全員聞いたのか分かりません。
                short = self._nobody_text(here, short=True)
            self._finish(short, status=_AL.PARTIAL if missed else _AL.SUCCESS)
            return False
        c = cands[0]
        npc = c["npc"]
        label = self.service.appearance_label(npc["appearance_id"])
        self.target = {"npc": npc, "label": label, "slot": npc.get("slot")}
        # ★勇者メモの行を「見た目の字「…」」にする印（★会話の文が流れたときに view_model が使う）
        self.vm.talk_tag = {"label": label, "npc_id": npc["npc_id"], "map_id": here["map_id"]}
        self.vm.last_talk_text = None
        self.message = "★%s中（%d 人目）" % (REHEAR if self.rehear else HEAR, self.done_count + 1)
        # ★★ 毒の床を避けられなかった（RX3-0277 / 2026-09-18 依頼者「回り込まないが、毒沼超えしか道はない」）。
        #   ⚠ 黙って踏むと「避ける仕組みが効いていない」ように見える。★「回り込めない」と言う
        hurt = int((c["plan"] or {}).get("damage") or 0)
        if hurt:
            self.message += "（⚠ 毒の床 %d）" % hurt
            self._env_line("[HEARING] DAMAGE_FLOOR hp=%d npc=%s cells=%s"
                           % (hurt, npc.get("npc_id"), (c["plan"] or {}).get("damage_cells")))
        # ★★ 経路が閉じた扉を通るなら、扉の手前で区切って鍵を使う（RX3-0159）
        door = self._door_ahead(here, c["plan"])
        if door is not None:
            return self._walk_to_door(here, c, door)
        return self._navigate(here, c["plan"], talk=True, npc=npc)

    # ------------------------------------------------------------------
    # ★★ 扉を開けて聞き込みを続ける（RX3-0159 / 2026-09-11）
    #
    #   ⚠⚠ 経路を探す側は鍵つきの扉を「開けられる」と知っている（RX3-0078）のに、
    #     歩く側が開け方を知らず、**扉に突っ込んで「通れず」**になっていました。
    #   ★実機で通った手順（`docs/research/dq3-door-key-hearing.md`）:
    #
    #     1 扉の手前まで歩き、扉を向く（★nav / talk=0）
    #     2 どうぐ → 鍵の持ち主 → 鍵 → つかう（★item_use_v0 / 画面で名前を探して押す）
    #     3 もう一度同じ相手へ（★開けた扉は覚えておき、2 度は開けない）
    #
    #   ★依頼者の注意: 扉の種類で使う鍵が違う / 誰がどの鍵を持っているか
    #     → ★`knowledge/door_access.py` が決める（⚠ ここに書き写さない）。
    # ------------------------------------------------------------------
    def _door_ahead(self, here, plan):
        """★経路の上の、まだ開けていない最初の扉（⚠ 無ければ None）。"""
        from ..knowledge import door_access as DA

        try:
            rom = self.service.rom_map(here["map_id"])
        except Exception:                                    # noqa: BLE001
            return None
        if rom is None or not hasattr(rom, "door_nibble"):
            return None
        opened = [(x, y) for (m, x, y) in self._opened if m == here["map_id"]]
        return DA.door_on_path(rom, plan.get("cells") or [], opened)

    def _walk_to_door(self, here, cand, door) -> bool:
        from ..knowledge import door_access as DA

        k, xy, nibble = door
        npc = cand["npc"]
        plan = cand["plan"]
        hold = DA.key_for_door(nibble, DA.key_holders(self.vm.equip_members()))
        if hold is None or k >= len(plan.get("keys") or []):
            # ⚠ 鍵つきで経路を引いたのに、開けられる鍵が袋に見つからない（★袋が読めない等）
            self.skipped.add(npc["npc_id"])
            self.log.append({"at": self.clock(), "skip": npc["npc_id"], "reason": "needs_key",
                             "door": list(xy)})
            return self._next_target()
        leg = {"keys": list(plan["keys"][:k]), "cells": list(plan["cells"][:k]),
               "face": plan["keys"][k], "steps": k}
        self._door = {"map_id": here["map_id"], "xy": xy, "nibble": nibble, "hold": hold,
                      "npc": npc, "phase": "walk", "since": None}
        self.log.append({"at": self.clock(), "door": list(xy), "nibble": nibble,
                         "key": hold.name, "member": hold.member + 1, "npc_id": npc["npc_id"]})
        self.message = "★扉を開けに行きます（%s）" % (hold.name or "鍵")
        return self._navigate(here, leg, talk=False, npc=None, close=False)

    def _door_arrived(self, reason) -> None:
        """★扉の手前に着いた → 鍵を使う。⚠ 着けなければ、その人は飛ばす。"""
        from ..knowledge import door_access as DA

        door = self._door
        npc = door["npc"]
        if reason != "arrived":
            self._door = None
            self.skipped.add(npc["npc_id"])
            self.log.append({"at": self.clock(), "skip": npc["npc_id"], "reason": reason,
                             "door": list(door["xy"])})
            self._next_target()
            return
        try:
            self.item_seq = self.commands.send("use_item", **dict(DA.use_params(door["hold"]),
                                                                  **self._env_params()))
            self._lua_touched = True
        except (OSError, ValueError) as err:
            self._door = None
            self.skipped.add(npc["npc_id"])
            self.log.append({"at": self.clock(), "skip": npc["npc_id"],
                             "reason": "command_failed", "error": str(err)})
            self._next_target()
            return
        door["phase"], door["since"] = "open", self.clock()
        self.message = "★%sを使っています" % (door["hold"].name or "鍵")

    def _poll_door_open(self) -> None:
        """★鍵を使い終わるのを待つ → 開けた扉を覚えて、同じ相手へ歩き直す。"""
        door = self._door
        got = self.vm.item_status() or {}
        if got.get("seq") != getattr(self, "item_seq", None) or got.get("phase") != "done":
            if self.clock() - (door["since"] or self.clock()) > ITEM_WAIT_S:
                self._door = None
                self.skipped.add(door["npc"]["npc_id"])
                self.log.append({"at": self.clock(), "skip": door["npc"]["npc_id"],
                                 "reason": "door_not_opened", "why": "timeout"})
                self._next_target()
            return
        self._door = None
        if got.get("reason") != "used":
            # ⚠ 使えなかった（★窓が読めない・袋に無い等）。★その人は飛ばす
            self.skipped.add(door["npc"]["npc_id"])
            self.log.append({"at": self.clock(), "skip": door["npc"]["npc_id"],
                             "reason": "door_not_opened", "why": got.get("reason")})
            self._next_target()
            return
        # ★開けた扉を覚える（⚠ ROM の地図は扉のままなので、自分で覚える）
        self._opened.add((door["map_id"],) + tuple(door["xy"]))
        self.log.append({"at": self.clock(), "opened": list(door["xy"]),
                         "key": door["hold"].name})
        # ★同じ相手へもう一度（⚠ 次の扉があれば、また手前で区切る）
        self._next_target()

    def _reachable_with_all_keys(self, here, left) -> set:
        """★鍵を**全部**持っていたら届く人（⚠ 実際には持っていなくてもよい）。

        ★これで「行けない」を「鍵が要る」と「そもそも届かない」に分けられます。
        ⚠ 鍵を持っていないときだけ意味があります（★持っていれば候補に出ている）。
        """
        from ..knowledge import item_info as II

        every = II.all_key_ids()
        if set(every) <= set(self.party_keys()):
            return set()                     # ⚠ もう全部持っている → ★鍵のせいではない
        got = set()
        for npc in left:
            try:
                plan = self.service.plan_to(here["map_id"], (here["x"], here["y"]), npc,
                                            keys=every)
            except Exception:                                    # noqa: BLE001
                continue
            if plan is not None:
                got.add(npc["npc_id"])
        return got

    def _heard_totals(self, here) -> tuple[int, int] | None:
        """★この場所の「話しかけられる人」と「もう聞いた人」の数（⚠ 読めなければ None）。"""
        try:
            cur = self.service.current_npcs(here["map_id"], here["time_byte"], here["npc_tbl"])
        except Exception:                                    # noqa: BLE001
            return None
        if cur.get("status") != "DEFAULT":
            return None
        talkable = [n for n in cur.get("npcs", []) if hearing_target(n)]   # ★RX3-0194（王様を数えない）
        heard = [n for n in talkable
                 if self.service.heard.is_heard(here["map_id"], n["npc_id"], here.get("phase"))]
        return len(talkable), len(heard)

    def _npc_status(self, here) -> str | None:
        """★この場所の人の表の状態（`DEFAULT` / `UNKNOWN`。⚠ 読めなければ None / RX3-0230）。"""
        try:
            cur = self.service.current_npcs(here["map_id"], here["time_byte"], here["npc_tbl"])
        except Exception:                                    # noqa: BLE001
            return None
        return cur.get("status")

    def _nobody_text(self, here, *, short: bool = False) -> str:
        """★1 人とも話さずに終わった**わけ**（RX3-0157 / 依頼者 2026-09-11）。

        ```text
        ★全員聞いた      この場所の 16 人とは、もう全員話しています
        ★話せる人がいない  話しかけられる人がいません
        ⚠ 分からない      新しく話せる人はいませんでした   ← ★推測で理由を作らない
        ⚠ 表が読めない    この町の人の表が読めません       ← ★RX3-0230（「もう全員」と取れる文を出さない）
        ```
        """
        got = self._heard_totals(here) if here else None
        if got is None and here and self._npc_status(here) not in (None, "DEFAULT"):
            # ⚠⚠ RX3-0230（save1 バハラタ）: 表が読めず候補 0 → 以前は「新しく話せる人はいません」で、
            #   ★もう全員聞いたように読めた。⚠ 表が読めないことをそのまま言う
            return "この町の人の表が読めません"
        if got is not None:
            talkable, heard = got
            if talkable == 0:
                return "話しかけられる人がいません"
            if heard >= talkable:
                return ("もう全員と話しています（%d人）" % talkable if short
                        else "この場所の%d人とは、もう全員話しています" % talkable)
        return "新しく話せる人はいません" if short else "新しく話せる人はいませんでした"

    def _left_unheard(self, here) -> list[dict]:
        """★まだ話していない（talk_id > 0 / heard でない / skip 済みでない）人。⚠ 辿り着けるかは問わない。"""
        try:
            cur = self.service.current_npcs(here["map_id"], here["time_byte"], here["npc_tbl"])
        except Exception:                                    # noqa: BLE001
            return []
        if cur.get("status") != "DEFAULT":
            return []
        # ★再聞き込み（RX3-0239）は「この回で話していない人」
        return [n for n in cur.get("npcs", [])
                if hearing_target(n) and n["npc_id"] not in self.skipped
                and (n["npc_id"] not in self.visited_now if self.rehear
                     else not self.service.heard.is_heard(here["map_id"], n["npc_id"], here.get("phase")))]

    def _rehear_kw(self) -> dict:
        """★再聞き込みのときだけ「聞いた人も候補に」を渡す（RX3-0239 / ⚠ 通常の聞き込みは今までと同じ呼び方）。"""
        return {"include_heard": True} if self.rehear else {}

    def stop(self) -> None:
        """★安全停止（指示書 §12 / §13）: いまの 1 操作を止め、次へ進まない。heard は保つ。"""
        try:
            self.commands.send("nav_stop")
        except (OSError, ValueError):
            pass
        self._finish("停止しました", status=_AL.CANCELLED)

    def _finish(self, message: str, *, status=None, reason=None) -> None:
        """★終わりは**この 1 本だけ**（⚠ どの終わり方もここを通す）。

        ⚠ 2026-09-07（RX3-0110）: ここでユーザー向けの 1 行も出します。
        ★`ActionRun.finish()` が 1 回しか通らないので、⚠ 二重には出ません。
        """
        was = self.mode
        self.mode = None
        self.seq = None
        self._cancels_seen = None
        self.target = None
        self._door = None                    # ★扉の段も片づける（RX3-0159）
        self._switch = None                  # ★切り替えの途中も片づける（RX3-0257）
        self.vm.talk_tag = None
        # ⚠⚠ 画面には**短い形**だけ（RX3-0102: 長い文が右パネルの幅を超えていた）。
        #   ★全文は行動履歴に残ります。
        self.message = self._short(message, was, status)
        if was in ("hearing", "move", "restock"):
            # ⚠⚠ **順番が決まっています**（RX3-0116）:
            #   ① 速度・Mute を開始前へ戻す（`end`）＋ ★Lua の Turbo を切る（`town_end` / RX3-0170）
            #   ② User Action Summary を 1 行
            #   ③ ★ゲームへ操作を返す（`finish`）
            why = "BATTLE" if reason == "battle" else END_WHY.get(status, "ERROR")
            if self.env_hook is not None:
                try:
                    self.env_hook.end(was, why)
                except Exception:                                # noqa: BLE001
                    pass
            self._end_lua(was, why)
            self._done_line(was, why, reason)
            self._summarize(was, status, message, reason)
            if self.env_hook is not None and hasattr(self.env_hook, "finish"):
                try:
                    self.env_hook.finish(was)
                except Exception:                                # noqa: BLE001
                    pass
        self.run = None

    def _end_lua(self, was: str, why: str) -> None:
        """★Lua に「街の作業は終わった」と伝える（RX3-0170）。

        ★Lua はこれで Turbo を切り、動いている nav / restock も止める。
        ⚠ 直前の nav_stop / restock_stop を上書きしても、town_end が同じく止めるので**止め損ねない**。
        ⚠ 送れなくても続ける（★Lua は画面が黙ると `lease_s` で自分から切る）。
        """
        if not self._lua_touched:
            return                               # ⚠ 何も頼んでいない（★買うものが無い補充など）
        self._lua_touched = False
        source = "%s_%s" % (SOURCE_OF_MODE.get(was, "TOWN"), why)
        try:
            self.commands.send("town_end", source=source)
        except (OSError, ValueError):
            pass

    def _done_line(self, was: str, why: str, reason) -> None:
        """★終わりのログ 1 行（`[HEARING] DONE talked=5 unreachable=1` / 依頼者 §27）。"""
        if was == "hearing":
            self._env_line("[HEARING] %s talked=%d unreachable=%d%s" % (
                why, self.done_count, len(self.skipped),
                (" reason=%s" % reason) if reason else ""))
        else:
            self._env_line("[%s] %s%s" % (SOURCE_OF_MODE.get(was, "TOWN"), why,
                                          (" reason=%s" % reason) if reason else ""))

    # ------------------------------------------------------------------
    # ★ユーザー向けの 1 行（RX3-0109 / RX3-0110）
    # ------------------------------------------------------------------
    def _skip_counts(self) -> dict:
        """★飛ばした理由の内訳（⚠ 内部の語のままでは出さない）。"""
        out: dict[str, int] = {}
        for row in self.log:
            why = row.get("reason")
            if row.get("skip") is None or why is None:
                continue
            text = SKIP_TEXT.get(why, "うまくいかず")
            out[text] = out.get(text, 0) + 1
        return out

    def _emit(self, type: str, data: dict, *, level: str = _EV.INFO):
        """★共通 Event を 1 件（⚠ ログのために段取りを壊さない / 依頼者 §25）。"""
        try:
            return self.writer.emit(type, _EV.SRC_NAVIGATION, data, level=level)
        except Exception:                                        # noqa: BLE001
            return None

    def _summarize(self, what: str, status, message: str, reason) -> None:
        """★行動履歴へ 1 行。⚠ 出せなくても処理は止めない。"""
        run, self.run = self.run, None
        if run is None:
            return
        detail = {"reason": reason, "steps": self.steps,
                  "skipped": sorted(x for x in self.skipped if x is not None),
                  "raw_message": message}
        try:
            if what == "restock":
                plan, spent = self.plan, int((self.vm.restock_status() or {}).get("spent") or 0)
                bought = int((self.vm.restock_status() or {}).get("bought") or 0)
                if plan is not None and plan.is_empty():
                    # ★買うものが無かった（⚠ これは失敗ではない）
                    run.cancelled(plan.summary(), **detail)
                elif status == _AL.SUCCESS:
                    run.completed("%s（%d G）" % (self._bought_text(plan, bought), spent),
                                  **detail)
                elif status == _AL.PARTIAL:
                    run.partial("%s（%d G）" % (self._bought_text(plan, bought), spent),
                                **detail)
                elif status == _AL.CANCELLED:
                    run.cancelled("ユーザー操作", **detail)
                else:
                    run.failed(NAV_TEXT.get(reason, "買えませんでした"), **detail)
                return
            if what == "move":
                # ★★ 自動移動は共通 Event を通します（RX3-0154 / 依頼者 §9 §16）。
                #   ⚠ ここでは**文章を作りません**。★行動履歴の 1 行も、Product Log も、
                #     `events/formatter.py` が同じ Event から作ります。
                if not run.claim():
                    return                       # ⚠ 二重には出さない（`finish` と同じ歯止め）
                data = dict(detail, destination=(self.target_label or "目的地"),
                            elapsed_s=run.elapsed())
                if status == _AL.SUCCESS:
                    self._emit(_EV.NAVIGATION_ARRIVE, dict(data, result=_EV.SUCCESS))
                elif status == _AL.CANCELLED:
                    self._emit(_EV.NAVIGATION_STOP, dict(data, result=_EV.CANCELLED))
                else:
                    self._emit(_EV.NAVIGATION_STOP, dict(data, result=_EV.STOPPED),
                               level=_EV.WARNING)
                return
            done = "%d人と会話" % self.done_count
            left = self._skip_counts()
            if self.done_count == 0 and status in (_AL.SUCCESS, _AL.PARTIAL):
                # ★★ 0 人のときは**わけ**を言う（RX3-0157 / 依頼者「もう少し親切なメッセージ」）
                #   ⚠ 「完了：0人と会話」では、壊れたのか、もう全員聞いたのか分かりません。
                #   ⚠⚠ **最後まで回ったときだけ**。★途中で止めたのに「もう全員」と言うと嘘になる。
                done = "話せた人はいません" if left else self._nobody_text(self._here())
            if left:
                inner = "・".join("%s%d" % (k, v) for k, v in sorted(left.items()))
                done += " / 未完%d人（%s）" % (sum(left.values()), inner)
            if status == _AL.CANCELLED:
                run.cancelled("ユーザー操作 / " + done, **detail)
            elif status == _AL.FAILED:
                run.failed("%s / %s" % (NAV_TEXT.get(reason, "うまくいきませんでした"), done),
                           **detail)
            elif left:
                run.partial(done, **detail)
            else:
                run.completed(done, **detail)
        except Exception:                                        # noqa: BLE001
            pass                                                  # ⚠ 履歴のために処理を壊さない

    @staticmethod
    def _bought_text(plan, bought: int) -> str:
        """★「やくそう 3個」（⚠ 買えた数で言う。★計画の数ではない）。"""
        if plan is None or not plan.lines:
            return "%d個" % bought
        if len(plan.lines) == 1:
            return "%s %d個" % (plan.lines[0].name, bought)
        return "%d種 %d個" % (len(plan.lines), bought)

    @staticmethod
    def _short(message: str, what, status) -> str:
        """⚠⚠ 右パネルの幅を超えない短い形（RX3-0102 / 依頼者 2026-09-07）。

        ★「メッセージはログで良い」。⚠ ただし**消しません**（全文は行動履歴へ）。
        """
        if len(message) <= STATUS_MAX:
            return message
        return message[:STATUS_MAX - 1] + "…"

    # ------------------------------------------------------------------
    # ★毎 refresh に呼ぶ
    # ------------------------------------------------------------------
    def poll(self) -> None:
        if self.mode is None:
            return
        # ★聞き込み中は実行環境（区間減速の倍率）を保つ（★KEEP_EVERY_S ごとに送り直す / 終わったときだけ戻す）
        if self.mode in ("hearing", "move", "restock") and self.env_hook is not None                 and hasattr(self.env_hook, "keep"):
            now = self.clock()
            if now - self._last_keep >= KEEP_EVERY_S:
                self._last_keep = now
                try:
                    self.env_hook.keep(self.mode)
                except Exception:                                # noqa: BLE001
                    pass
        # ★人がゲームの B（キーボードの D）で止めた（RX3-0170 / ★Lua が数える / 依頼者 §14）
        if self._lua_cancelled():
            self._finish("停止しました", status=_AL.CANCELLED, reason="user_b")
            return
        # ★移動中に次の候補へ切り替えている（RX3-0257）。⚠ 止める前に終わっていれば、いつもの終わり方へ
        if self.mode == "move" and self._switch is not None and self._poll_switch():
            return
        if self.mode == "restock" and self._restock_sent:
            self._poll_restock()
            return
        # ★鍵を使っている間は nav を見ない（⚠ nav はもう終わっている / RX3-0159）
        if self.mode == "hearing" and self._door is not None and self._door["phase"] == "open":
            self._poll_door_open()
            return
        nav = self.vm.nav_status() or {}
        if nav.get("seq") != self.seq:
            return                                   # ⚠ まだ前の状態 / 別の頼み
        if self.mode == "move":
            self._note_first_message(nav)            # ★RX3-0241（⚠ 宿屋は終わる前に来る）
        if nav.get("active") or nav.get("phase") != "done":
            return
        if self._handled_seq == self.seq:
            return
        reason = nav.get("reason")
        if reason in ("battle", "stopped_by_user"):
            # ★遭遇した / 止めた（RX3-0170）。⚠ 「止まりました」だけでは何が起きたか分からない
            self._handled_seq = self.seq
            if reason == "battle":
                self._finish("⚠ 戦闘になりました", status=_AL.FAILED, reason=reason)
            else:
                self._finish("停止しました", status=_AL.CANCELLED, reason=reason)
            return
        if self.mode == "restock":
            self._handled_seq = self.seq
            if reason != "talk_done":
                # ⚠ 店主に話せていない。★頼まずに終わる（1 つも押していない）
                self._finish("⚠ 店まで行けませんでした", status=_AL.FAILED, reason=reason)
                return
            self._send_restock()
            return
        if self.mode == "move":
            self._handled_seq = self.seq
            # ★着いて話しかけた = talk_done（RX3-0197）。★arrived は話しかけない頼み（古い Lua）の着き方
            # ★RX3-0241: 施設の人の最初の台詞で止めた = first_message / 宿屋で はい と答えた = inn_yes
            if reason in MOVE_DONE_TEXT:
                self._finish(MOVE_DONE_TEXT[reason], status=_AL.SUCCESS, reason=reason)
            elif reason == "inn_question_unanswered":
                # ⚠ 宿屋の問いと確かめられない / 窓が出ない（★Lua は はい を押さずに止めた）→ 人が答える
                self._finish("⚠ " + NAV_TEXT[reason], status=_AL.FAILED, reason=reason)
            else:
                self._finish("⚠ 止まりました", status=_AL.FAILED, reason=reason)
            return
        # ★聞き込み
        if self._door is not None and self._door["phase"] == "walk":
            self._handled_seq = self.seq
            self._door_arrived(reason)
            return
        if reason in ("talk_done", "choice_repeated"):
            self._after_talk(reason)                 # ★choice_repeated も会話は済んでいる（★heard に記す / RX3-0273）
            return
        self._handled_seq = self.seq
        npc = (self.target or {}).get("npc") or {}
        if reason == "depart_question_unanswered":
            # ⚠⚠ 「また すぐに たびだつ つもりか？」の窓が開いたまま（RX3-0194）。★人が「はい」で答える
            #   （⚠ B / いいえ はゲームが終わる。★Lua は B を押さずに止めている）
            self._finish("⚠ " + NAV_TEXT[reason], status=_AL.FAILED, reason=reason)
            return
        if reason in ("skip_unreachable_now", "path_blocked", "face_moved", "path_deviation"):
            self.skipped.add(npc.get("npc_id"))
            self.log.append({"at": self.clock(), "skip": npc.get("npc_id"), "reason": reason})
            self._next_target()
            return
        self._finish("⚠ 止まりました", status=_AL.FAILED, reason=reason)

    def _lua_cancelled(self) -> bool:
        """★Lua が数えた「人が B を押した回数」が、この操作の間に増えたか（RX3-0170）。"""
        try:
            got = (self.vm._raw().get("town_speed") or {}).get("cancels")
        except Exception:                                        # noqa: BLE001
            return False
        if not isinstance(got, int):
            return False
        if self._cancels_seen is None or got < self._cancels_seen:
            self._cancels_seen = got             # ★最初の poll で今の数を覚える（⚠ Lua を読み直すと 0 に戻る）
            return False
        return got > self._cancels_seen

    def _poll_restock(self) -> None:
        """★Lua が買い終わるのを待つ（⚠ 上限つき）。"""
        got = self.vm.restock_status() or {}
        if got.get("phase") != "done":
            if self.clock() - (self._waiting_since or 0) > RESTOCK_WAIT_S:
                try:
                    self.commands.send("restock_stop")
                except (OSError, ValueError):
                    pass
                self._finish("⚠ 時間がかかりすぎました", status=_AL.FAILED,
                             reason="timeout")
            return
        self._restock_sent = False
        bought, reason = int(got.get("bought") or 0), got.get("reason")
        want = self.plan.total_buy if self.plan is not None else 0
        if bought >= want and want > 0:
            self._finish("★買いました", status=_AL.SUCCESS, reason=reason)
        elif bought > 0:
            self._finish("⚠ 途中まで買いました", status=_AL.PARTIAL, reason=reason)
        else:
            self._finish("⚠ 買えませんでした", status=_AL.FAILED, reason=reason)

    def _after_talk(self, reason: str = "talk_done") -> None:
        """★会話の文が勇者メモへ流れ、窓が閉じたのを見てから heard に記し、次へ。

        ★`reason == "choice_repeated"`（RX3-0273）: Lua が選択肢の繰り返しで止めた。★窓は開いたままと分かっているので
        閉じるのを待たず、heard に記してから人に返す（⚠ 次へは進まない）。
        """
        now = self.clock()
        if self._waiting_since is None:
            self._waiting_since = now
        text = getattr(self.vm, "last_talk_text", None)
        closed = not self.vm.conversation_open_now() and reason != "choice_repeated"
        if text is None and now - self._waiting_since < TALK_TEXT_WAIT_S:
            return
        if not closed and reason != "choice_repeated" and now - self._waiting_since < TALK_TEXT_WAIT_S + CLOSE_WAIT_S:
            return
        self._handled_seq = self.seq
        npc = (self.target or {}).get("npc") or {}
        here = self._here() or {}
        talk = self.vm.last_talk() or {}
        if text is None:
            # ⚠ 会話が始まらなかった（★「A を押した」だけでは heard にしない）
            self.skipped.add(npc.get("npc_id"))
            self.log.append({"at": now, "skip": npc.get("npc_id"), "reason": "no_conversation"})
            self._next_target()
            return
        slot = talk.get("slot", npc.get("slot"))
        rec = self.service.record_heard(here.get("map_id"), here.get("time_byte"), slot,
                                        talk.get("talk_id", npc.get("talk_id")), text,
                                        npc_tbl_hex=here.get("npc_tbl"), **self._phase_kw(here))
        if rec is None:
            # ⚠⚠ RX3-0230（save1 バハラタ）: 話したのに heard に記せなかった（★表が読めない / slot が表に無い）。
            #   ⚠ 以前は黙って「話した」に数え、記録は残らず、同じ人が次も候補に出得た。
            #   → ★飛ばした人として内訳（「記録できず」）とログに出す
            self.skipped.add(npc.get("npc_id"))
            self.log.append({"at": now, "skip": npc.get("npc_id"), "reason": "record_failed",
                             "slot": slot, "closed": closed})
            self._env_line("[HEARING] RECORD_FAILED map=%s slot=%s" % (here.get("map_id"), slot))
        else:
            self.done_count += 1
            self.visited_now.add(npc.get("npc_id"))           # ★再聞き込みで同じ人を繰り返さない（RX3-0239）
            self.log.append({"at": now, "heard": rec, "closed": closed})
        if reason == "choice_repeated":
            # ⚠ RX3-0273: 選択肢が 3 回開いた → Lua は B をやめた。★窓を人に返す（★heard には記した）
            self._finish("⚠ " + NAV_TEXT[reason], status=_AL.FAILED, reason=reason)
            return
        if not closed:
            # ★RX3-0217: 「いいえ」（B）で聞き直し続ける相手は B では抜けられない → ★抜け方を出す
            self._finish("⚠ 窓が閉じません（「はい」→ B で抜けられる相手もいます）",
                         status=_AL.FAILED, reason="window_will_not_close")
            return
        self.vm.talk_tag = None
        self.vm.last_talk_text = None
        self._next_target()


class TownBar(QWidget):
    """★1 行だけ（指示書 §2）。⚠ 大きなパネルは作らない。"""

    def __init__(self, vm, service, commands, parent=None, env_hook=None,
                 settings=None) -> None:
        super().__init__(parent)
        self.ctl = TownNavController(vm, service, commands, env_hook=env_hook)
        #: ★目標の数などの小さな設定（⚠ 無ければ既定）
        self.settings = settings
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        # ★★ 街移動は [宿][道][武][神] の 1 クリック（RX3-0257）。⚠ プルダウンも「移動」ボタンも置かない
        #   ★★ 2026-09-20（RX3-0325）: **アイコンの下に字**にしました。
        #     依頼者「1文字ボタンの速さを残しながら、初見でも意味を推測できるようにする」
        #   ★★ 2026-09-21（RX3-0328）: **字を出すのもやめました**（依頼者「アイコンだけでいい」）。
        #     ⚠ 字そのものは残します（`text()` は「宿」を返す / ★記録・検査・説明が使う）。
        #   ⚠⚠ 字を**右**に置くと入りません。★実測: 1 つ 42px × 7 ＋［…］で
        #     右パネル（340px）がほぼ埋まり、**状態の文（「★道具屋 1/2 へ」）の場所が消えます**。
        self.move_buttons: dict[str, QToolButton] = {}
        for role, text, _name in MOVE_BUTTONS:
            button = icon_button.make(MOVE_ICONS[role], text, "",
                                      place=icon_button.ICON)
            button.clicked.connect(lambda _checked=False, r=role: self._on_move(r))
            self.move_buttons[role] = button
        #: ★止まっている間に作った候補（⚠ 移動中は作り直さない = 押せるボタンが揺れない）
        self._known: list = []
        # ★1 文字（RX3-0290 / ⚠ 正式な名前はツールチップに出す）
        self.hear_button = icon_button.make("hear", BUTTON_LABEL[HEAR], "",
                                            place=icon_button.ICON)
        # ⚠ ツールチップは `refresh()` が「聞き込み / 再聞き込み」で入れ直す（★ここでは書かない）
        self.hear_button.clicked.connect(self._on_hear)
        # ★補充（RX3-0066 / RX3-0119）。⚠ 買うものが無ければ**歩きもしません**
        self.restock_button = icon_button.make(
            "restock", RESTOCK_LABEL, "", place=icon_button.ICON)
        self.restock_button.setToolTip(
            "道具を補充する" + NEWLINE +
            "★道具屋まで歩いて、足りないぶんだけ買います"
            "\n★目標の数は［…］の補充設定で決めます（管理画面の文字の欄と同じ）"
            "\n⚠ 足りていれば、ボタンを 1 つも押さずに終わります")
        self.restock_button.clicked.connect(self._on_restock)
        # ★補充設定（RX3-0212 / 2026-09-12 依頼者「リストックの設定画面が欲しい」）。⚠ 右画面は狭いので 1 文字
        #   ⚠ ここはアイコンにしません（★「補」の付属で、独立した機能ではない）
        self.restock_settings_button = QPushButton("…")
        self.restock_settings_button.setFixedWidth(24)
        # ⚠ 高さを揃えないと、★アイコンのボタンだけ背が高くて段差になります（RX3-0325）
        self.restock_settings_button.setFixedHeight(icon_button.HEIGHT[icon_button.ICON])
        self.restock_settings_button.setToolTip("補充設定" + NEWLINE
                                                + "★品ごとに、何個になるまで買うかを決めます")
        self.restock_settings_button.clicked.connect(self.open_restock_settings)
        self._restock_window = None
        self.status = QLabel("")
        self.status.setStyleSheet("color: #888;")
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for w in (*self.move_buttons.values(), self.hear_button, self.restock_button,
                  self.restock_settings_button):
            w.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            row.addWidget(w)
        row.addWidget(self.status, 1)
        # ★押せないボタンでも説明を出す（RX3-0329）。
        #   ⚠ 面識が無い施設のボタンは押せません。★「なぜ押せないか」を知りたいのはそのときです
        icon_button.watch_disabled(self)
        self.refresh()

    def open_restock_settings(self) -> None:
        """★補充設定の窓（⚠ 2 つ開かない / 設定が無ければ開かない）。"""
        if self.settings is None:
            return
        if self._restock_window is None:
            from .restock_window import RestockWindow

            self._restock_window = RestockWindow(self.settings)
        self._restock_window.refresh()
        self._restock_window.show()
        self._restock_window.raise_()

    def _on_move(self, role: str) -> None:
        """★[宿][道][武][神]（RX3-0257）: 止まっていれば移動を始め、移動中なら次の候補へ切り替える。"""
        self.ctl.request_move(role)
        self.refresh()

    def _move_tip(self, role: str, name: str, got: list) -> str:
        """★ボタンのツールチップ（★正式な名前 / 複数なら「道具屋 1/2」/ RX3-0257 §7）。"""
        if not got:
            if role == ENTRANCE_ROLE:
                # ⚠ 「面識」ではない（★入ってきた所を見ていないだけ / RX3-0291）
                return ("%sへ移動\n⚠ この町に**入ってきた所**を見ていないので押せません"
                        "\n★世界地図から入り直すと覚えます（⚠ 町の中でセーブを読んだときは分かりません）" % name)
            return "%sへ移動\n⚠ 面識のある%sがまだありません（★聞き込みで一度話すと押せます）" % (name, name)
        if role == ENTRANCE_ROLE:
            return "%sへ移動\n★この町に入ってきた升の**手前**まで歩きます（⚠ 町は出ません）" % name
        tip = "%sへ移動" % name
        target = self.ctl.target or {}
        if len(got) > 1:
            if self.ctl.mode == "move" and target.get("role") == role:
                tip += "\n★いま %s %d/%d へ（★もう一度押すと次の%sへ）" % (name, target["index"], len(got), name)
            else:
                here = self.ctl._here() or {}
                tip += "\n★次は %s %d/%d（★押すたびに次の%sへ）" % (
                    name, self.ctl.upcoming(role, got, here.get("map_id")), len(got), name)
        return tip

    def _on_hear(self) -> None:
        if self.ctl.mode == "hearing":
            self.ctl.stop()
        elif self.ctl.mode is None:
            self.ctl.start_hearing()
        self.refresh()

    def _on_restock(self) -> None:
        if self.ctl.mode == "restock":
            self.ctl.stop()
        elif self.ctl.mode is None:
            self.ctl.restock_wants = restock_wants(self.settings)
            self.ctl.keep_gold = keep_gold(self.settings)
            self.ctl.start_restock()
        self.refresh()

    def poll(self) -> None:
        # ★入ってきた升を覚える（RX3-0291 / ⚠ 止まっている間も見る = `ctl.poll` は動作中しか進まない）
        try:
            self.ctl.note_entry()
        except Exception:                                    # noqa: BLE001 ★街の行は落とさない
            pass
        self.ctl.poll()
        self.refresh()

    def note_manual_talk(self, made) -> dict | None:
        """★★ 手で話した会話を「聞いた」へ渡す橋（RX3-0282 / ⚠ 2026-09-18 に足した）。

        ⚠⚠ **これが無くて、実機では 1 件も記録されませんでした。**
          ★`main_window` が呼ぶのは `town_bar`（この widget）ですが、
          中身は `TownNavController` にありました。⚠ `hasattr` で守ってあったので、
          **エラーも出ずに丸ごと素通り**していました（依頼者「話にいっている」）。
        """
        return self.ctl.note_manual_talk(made)

    def refresh(self) -> None:
        mode = self.ctl.mode
        if mode is None:                              # ★動いていないときだけ候補を作り直す（⚠ 押せるボタンが揺れない）
            self._known = self.ctl.facilities()
        for role, _text, name in MOVE_BUTTONS:
            got = self.ctl.candidates(role, self._known)
            button = self.move_buttons[role]
            # ⚠ 候補が無ければ最初から押せない（★押してから「ありません」と出さない / §6）/ 聞き込み・補充の間も押せない
            button.setEnabled(bool(got) and mode in (None, "move"))
            button.setToolTip(self._move_tip(role, name, got))
        # ★ボタンは 1 つのまま、ラベルだけ「聞き込み / 再聞き込み」（RX3-0239 / 指示書 §3・§18）
        kind = self.ctl.hearing_kind() if mode is None else None
        name = kind or HEAR
        stopping = mode == "hearing"
        # ★字と絵をいっしょに替える（⚠ `set_label` は幅も合わせ直す / RX3-0325）
        icon_button.set_role(self.hear_button,
                             "stop" if stopping else ("rehear" if name == REHEAR else "hear"))
        icon_button.set_label(
            self.hear_button, STOP_LABEL if stopping else BUTTON_LABEL[name],
            "止める" + NEWLINE + "★いま動いている聞き込みを止めます" if stopping
            else name + NEWLINE + HEAR_TIPS.get(name, ""))
        # ★実行中は「入っている」見た目（⚠ 押せば止まる、が一目で分かるように）
        icon_button.set_on(self.hear_button, stopping)
        self.hear_button.setEnabled(mode in (None, "hearing"))
        restocking = mode == "restock"
        icon_button.set_role(self.restock_button, "stop" if restocking else "restock")
        icon_button.set_label(self.restock_button,
                              STOP_LABEL if restocking else RESTOCK_LABEL)
        icon_button.set_on(self.restock_button, restocking)
        # ⚠ 道具屋に面識が無ければ押せない（★街移動と同じ約束）
        can = (mode is None
               and any(f["role"] == "item_shop" for f in self._known))
        self.restock_button.setEnabled(restocking or can)
        self.status.setText(self.ctl.message)
