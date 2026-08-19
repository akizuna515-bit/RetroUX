"""イベントを取り込んで SQLite に記録する（P5）。

責務分割（D-1 / DEV-1）:
    リアルタイム判断は Lua 側に閉じている。Python は記録と表示に徹する。
    **このプロセスが落ちてもゲームは正常に動き、ログだけが欠落する。**
    したがってここでは、取りこぼしより処理継続を優先する。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import events as ev
from .bridge.reader import JsonlTailer
from .bridge.writer import write_command
from .db.database import Database


HEAD_SIGNATURE_MAX_BYTES = 1024


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _opt_int(value: object) -> int | None:
    """イベントの数値フィールドを int にする。欠落・不正なら None。

    Lua 側は勝利表示を捕まえられなかった場合にこのフィールドを送らない
    （逃走・敗北）。無理に 0 を入れると「0ゴールド獲得」と区別できない。
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_time(event: "ev.Event") -> str | None:
    """イベントが持っている発生時刻（UTCのISO文字列）。無ければ None。

    ★Lua 側が `time`（`os.time()` の秒）を入れてくれる。
      取り込みが遅れても**起きた時刻**で記録できる。
      古い events.jsonl には入っていないので None を返す。
    """
    raw = event.get("time")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def rotate_events(db, events_path: Path | str, **kwargs):
    """`events.jsonl` を世代交代させ、**取り込み位置も一緒に戻す**。

    ## ⚠⚠ なぜ関数を分けたか

      世代交代（ファイルの rename）と取り込み位置のリセットは
      **必ず対で**行う必要があります。★片方だけやると:

        ・rename だけ  → 位置が古いまま。★新しいファイルの先頭を読み飛ばす
        ・reset だけ   → 同じ行を**もう一度**取り込む（二重記録）

      ⚠ 呼び出し側で2つ並べて書くと、いつか片方を忘れます。
      ★ここで1つにまとめます。

    ★取り込みが追いついていなければ、`events_rotation.rotate` が
      何もせずに戻ります（⚠ 未取り込みの行を置き去りにしないため）。

    使い方（★`Recorder` を作る**前**に一度だけ）:

        result = rotate_events(db, path)
        if result.rotated:
            log.info("%s", result.message())
    """
    from .events_rotation import rotate

    source = str(Path(events_path).resolve())
    offset, _sig = db.get_ingest_state(source)
    result = rotate(events_path, ingested_offset=offset, **kwargs)
    if result.rotated:
        # ★新しいファイルは空。位置は 0、署名は「まだ無い」
        db.set_ingest_state(source, 0, None)
    return result


def _head_signature(path: Path | str) -> str | None:
    """ファイルの **1行目** の署名。同じファイルを読み続けているかの判定に使う。

    固定長の先頭バイト列ではなく1行目を使うのは、追記でファイルが伸びても
    署名が変わらないようにするため。固定長だと、ファイルがその長さに満たない
    うちは追記のたびに署名が変わり、同じファイルを別物と誤判定してしまう。

    1行目がまだ書き終わっていない場合は None を返す（判定を保留する）。
    """
    p = Path(path)
    if not p.exists():
        return None
    with p.open("rb") as fh:
        head = fh.read(HEAD_SIGNATURE_MAX_BYTES)
    newline = head.find(b"\n")
    if newline < 0:
        return None
    return hashlib.sha256(head[:newline]).hexdigest()


@dataclass
class PendingBattle:
    """battle_start を受けてから battle_end を待っている状態。"""

    started_at: str
    started_monotonic: float
    monster_ids: list[int]
    is_first_encounter: bool
    is_boss: bool
    auto_input_used: bool = False


@dataclass
class RecorderStats:
    """GUI などが参照する軽い状態。"""

    battles_recorded: int = 0
    warnings: list[str] = field(default_factory=list)
    warning_codes: set[str] = field(default_factory=set)
    """すでに表示した警告の識別子。同じ警告を二重に出さないために使う。"""
    last_event_type: str | None = None
    in_battle: bool = False
    current_monsters: list[int] = field(default_factory=list)
    current_speed: float = 1.0
    danger: bool = False
    savestate_saved: dict | None = None
    """終了ボタンからの保存要求に対する返事。{"slot": 1, "ok": True}

    ★None は「まだ返事が無い」。呼ぶ側は**要求の前に None へ戻す**こと。
      前回の返事が残っていると「保存できた」と誤解する。
    """
    danger_reason: str | None = None
    """危険と判断した理由。

    ★「危険状態」と「読めていない」を画面で区別するために持つ。
      タイトル画面ではパーティ領域がまだ意味を持たないため、
      安全側に倒す仕掛け（is_danger のフェイルセーフ）が働いて
      **赤い「危険状態」が出っぱなし**になっていた。
      壊れているように見えるが、正しく安全側へ倒れている状態。
      理由まで出せば、見た人が区別できる。
    """


class Recorder:
    """events.jsonl を読み、SQLite に書き、遭遇済み集合を Lua へ返す。"""

    def __init__(
        self,
        db: Database,
        rom_hash: str,
        events_path: Path | str,
        command_path: Path | str,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.db = db
        self.rom_hash = rom_hash
        self.command_path = Path(command_path)

        # 前回どこまで読んだかを DB から復元する。
        # Lua はセッションをまたいで events.jsonl に追記し続けるため、
        # 毎回先頭から読むと再起動のたびに過去の戦闘を重複記録してしまう。
        self._source = str(Path(events_path).resolve())
        saved_offset, saved_sig = db.get_ingest_state(self._source)

        # ファイルが削除されて作り直された場合、保存済みの位置を使うと
        # 新しいセッションの先頭を読み飛ばす。先頭の署名で見分ける。
        # 署名は毎回ファイルから取り直す（起動時点ではまだ空のこともあるため、
        # 初期化時の値を握り続けると常に空の署名を保存してしまう）。
        if saved_sig is not None and _head_signature(events_path) != saved_sig:
            saved_offset = 0

        self.tailer = JsonlTailer(events_path, start_offset=saved_offset)
        self.stats = RecorderStats()
        self._pending: PendingBattle | None = None
        # 戦闘中に溜める出来事（battle_end で battle_id が決まってから書く）
        self._pending_events: list[dict] = []
        # 実時間の計測に使う。テストから差し替えられるようにしておく。
        self._clock = clock or (lambda: datetime.now(timezone.utc).timestamp())

    # --- 取り込み ----------------------------------------------------

    def poll(self) -> int:
        """新しいイベントを取り込む。処理した件数を返す。

        ★1件ずつコミットしない（MVP2 Phase 1 で実測して直した）。
          1イベント = 1コミット = 1回の fsync で **127ms** かかっており、
          溜まっていた 4820 件の取り込みに10分近くを要していた。
          GUI は起動時にこれを同期で呼ぶため、**固まったように見えていた**。
          まとめて1コミットにすると、同じ件数が1秒未満で終わる。

        ⚠ 途中で失敗したら**まとめて捨てる**。半端に取り込むと、
          取り込み位置だけ進んで戦闘が欠ける、という直しにくい壊れ方になる。
        """
        count = 0
        with self.db.bulk():
            for event in self.tailer.read_new_events():
                self.handle(event)
                count += 1
            # 読んだ位置は件数に関わらず保存する。
            # 未完了行を読み飛ばした場合など、件数0でも位置は進みうる。
            self.db.set_ingest_state(self._source, self.tailer.offset,
                                     _head_signature(self._source))
        if count:
            self.push_encountered()
        return count

    def handle(self, event: ev.Event) -> None:
        self.stats.last_event_type = event.type
        handler = {
            ev.BATTLE_START: self._on_battle_start,
            ev.BATTLE_END: self._on_battle_end,
            ev.SPEED_CHANGE: self._on_speed_change,
            ev.DANGER_ENTER: self._on_danger_enter,
            ev.DANGER_EXIT: self._on_danger_exit,
            ev.SAVESTATE_SAVED: self._on_savestate_saved,
            ev.BATTLE_TURN: self._on_battle_turn,
            ev.BATTLE_ACTION: self._on_battle_action,
            ev.BATTLE_OBSERVATION: self._on_battle_observation,
            ev.WARNING: self._on_warning,
            ev.SESSION_START: self._on_session_start,
        }.get(event.type)
        if handler is not None:
            handler(event)

    def _on_session_start(self, event: ev.Event) -> None:
        """★★★ FCEUX が起動し直したら、前の起動の警告を捨てる（2026-08-08）★★★

        ⚠⚠ **依頼者の報告: 直したのに「遭遇済みキャッシュに読めない行が…」が
        まだ出る。**

          ★実測すると、`work/events.jsonl` に**過去 612 件**の同じ警告が
            残っていました。⚠ 取り込みが先頭からやり直しになると、
            **2026-08-07 の警告が今日の画面に出ます**。
            ファイルはもう直っているのに、です。

        ⚠ 警告は「いまどうなっているか」の話です。★終わった起動の苦情を
          出し続けるのは、**直したのに直っていないように見せる**嘘になります。

        ⚠ 消すのは警告だけです。★戦闘の記録（積み上げた数字）は消しません。
        """
        self.stats.warnings.clear()
        self.stats.warning_codes.clear()

    def _on_warning(self, event: ev.Event) -> None:
        """警告を溜める。同じ内容を二重に出さない。

        重複判定は code を優先する。同じ問題を GUI 側と Lua 側の両方から
        報告することがあり、文言の一致に頼ると些細な差で重複してしまう。
        """
        message = str(event.get("message", ""))
        if not message:
            return
        self.add_warning(message, code=event.get("code"))

    def add_warning(self, message: str, code: str | None = None) -> None:
        if code:
            if code in self.stats.warning_codes:
                return
            self.stats.warning_codes.add(code)
        elif message in self.stats.warnings:
            return
        self.stats.warnings.append(message)

    def _on_battle_start(self, event: ev.Event) -> None:
        ids = event.enemy_ids
        # 過渡状態や壊れたイベントを戦闘として記録しない。
        if not ids:
            return
        # 初遭遇かどうかは Lua 側の判断を正とする（リアルタイムに倍速へ反映
        # 済みのため）。DB 側は記録を追随させる。
        self.db.mark_encountered(self.rom_hash, ids)
        # ★前の戦闘の残りを持ち越さない。混ざると別の戦闘の行動として記録される。
        self._pending_events = []
        self._pending = PendingBattle(
            # ★イベントが持っている時刻を優先する。
            #   取り込みが遅れた（＝溜まっていた）ぶんを後からまとめて処理すると、
            #   ここで now() を使っていた時代は**全部が取り込み時刻**になった。
            #   実際、4820件を追いついたとき 1400 戦闘すべてが同じ時刻になった。
            started_at=_event_time(event) or _now_iso(),
            started_monotonic=self._clock(),
            monster_ids=ids,
            is_first_encounter=bool(event.get("is_first_encounter", False)),
            is_boss=bool(event.get("is_boss", False)),
        )
        self.stats.in_battle = True
        self.stats.current_monsters = ids

    def _on_battle_end(self, event: ev.Event) -> None:
        self.stats.in_battle = False
        self.stats.current_monsters = []
        pending = self._pending
        self._pending = None
        if pending is None:
            # battle_start を取りこぼした場合。記録できないが処理は続ける。
            return

        # Lua 側が測った実時間を優先する。こちら側の時計は「イベントを処理した
        # 時刻」でしかなく、ポーリング間隔より短い戦闘では 0 に潰れてしまう。
        # 「削減できた待ち時間」の集計に直結するため精度が要る。
        duration_ms = _opt_int(event.get("duration_ms"))
        if duration_ms is None:
            duration_ms = int((self._clock() - pending.started_monotonic) * 1000)
        battle_id = self.db.insert_battle(
            rom_hash=self.rom_hash,
            started_at=pending.started_at,
            ended_at=_event_time(event) or _now_iso(),
            duration_ms=duration_ms,
            duration_frames=int(event.get("duration_frames") or 0) or None,
            monster_ids=pending.monster_ids,
            is_first_encounter=pending.is_first_encounter,
            is_boss=pending.is_boss,
            speed_applied=float(event.get("speed_applied") or 0.0) or None,
            auto_input_used=not (pending.is_first_encounter or pending.is_boss),
            # 勝利表示中に Lua が捕まえた値。逃走・敗北では表示が出ないため
            # None になる（それ自体が結果の手がかりになる）。
            exp_gained=_opt_int(event.get("exp_gained")),
            gold_gained=_opt_int(event.get("gold_gained")),
            # 戦闘の結末。Lua が判定した値をそのまま入れる。
            #   win        勝利表示が出た
            #   lose       生存者が居なくなった
            #   flee       途中でプレイヤーに操作が渡っていた（逃げられた場面がある）
            #   enemy_fled 敵が逃げた。プレイヤーは負けても逃げてもいない
            # ★経験値の値では判定していない。⚠ 逃げたとき・敵が逃げたときの
            #   動きが読めず、勝敗の根拠にすると誤判定が警戒リストに波及する。
            #   （B-9「アドレス未確定」は 2026-07-31 に解決済み。理由は別）
            # 古い形式のイベント（outcome を持たない）では None のままにする。
            result=event.get("outcome") or None,
        )

        # ★戦闘中に溜めた出来事を、いま決まった battle_id へ結びつける。
        #   途中で書けないのは「書く先がまだ無い」ため（行が作られていない）。
        if self._pending_events:
            self.db.insert_battle_events(battle_id, self._pending_events)
            self._pending_events = []
        self.stats.battles_recorded += 1

    def _on_speed_change(self, event: ev.Event) -> None:
        self.stats.current_speed = float(event.get("multiplier") or 1.0)

    def _on_danger_enter(self, event: ev.Event) -> None:
        self.stats.danger = True
        reason = event.get("reason")
        self.stats.danger_reason = str(reason) if reason else None

    def _on_danger_exit(self, _event: ev.Event) -> None:
        self.stats.danger = False
        self.stats.danger_reason = None

    # --- 行動単位ログ（Phase 3）------------------------------------
    #
    # ★戦闘が終わるまで**溜めておく**。BattleEvent は battle_id を持つが、
    #   その id は battle_end で行を作ったときに初めて決まるため。
    #   途中で書けないのではなく、**書く先がまだ無い**。

    def _on_battle_turn(self, event: ev.Event) -> None:
        self._pending_events.append({
            "kind": "turn", "turn": int(event.get("turn", 0)),
            "seq": 0, "frame": event.get("frame"),
        })

    def _on_battle_action(self, event: ev.Event) -> None:
        self._pending_events.append({
            "kind": "action", "turn": int(event.get("turn", 0)),
            "seq": int(event.get("seq", 0)), "frame": event.get("frame"),
            "actor": event.get("actor"), "target": event.get("target"),
            "action_name": event.get("action"),
            "selected_by": event.get("selected_by"),
            "reason": event.get("reason"),
        })

    def _on_battle_observation(self, event: ev.Event) -> None:
        self._pending_events.append({
            "kind": str(event.get("kind", "?")),
            "turn": int(event.get("turn", 0)),
            "seq": int(event.get("seq", 0)), "frame": event.get("frame"),
            "actor": event.get("name"),
            "before": event.get("before"), "after": event.get("after"),
            "delta": event.get("delta"),
        })

    def _on_savestate_saved(self, event: ev.Event) -> None:
        self.stats.savestate_saved = {
            "slot": event.get("slot"),
            "ok": bool(event.get("ok", False)),
        }

    # --- Lua への配布 ------------------------------------------------

    def push_encountered(self) -> None:
        """DB 上の遭遇済み集合を Lua へ渡す。

        Lua 側はこれを受け取ると自前のキャッシュを上書きする。
        DB を正にするための同期。
        """
        write_command(self.command_path,
                      encountered=self.db.encountered_ids(self.rom_hash))
