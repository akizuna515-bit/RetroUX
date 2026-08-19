"""移動の結果を判定する（2026-07-30 / 指示書 5章）。

★★ **操作ではなく結果を保存する**（指示書 2.2）★★

    ✗ 「右キーを押した」
    ✓ 「(10,5) から右へ進み、(11,5) に移動できた」
    ✓ 「(10,5) から上へ進もうとしたが、座標が変わらなかった」

## 進め方

    入力を見つけた       -> `PendingMove` としてメモリに置く（DBには書かない）
    座標が隣へ動いた     -> 通れた。`MapEdge` を UPSERT
    期限まで動かなかった -> 通れなかった。`MapBlockedDirection` を UPSERT
    マップが変わった     -> 遷移。`MapTransition` を UPSERT

## 記録しない場面（指示書 5.1 / 5.4）

⚠ 「動かなかった」は**いろいろな理由で起きる**。次の場面は失敗として数えない:

| 場面 | 理由 |
| --- | --- |
| 戦闘へ移った | 歩けなかったのではなく戦闘が入った |
| メニュー・会話が開いた | 入力がそちらへ行っている |
| マップが変わった | 遷移として別に記録する |
| 状態が読めていない | そもそも判定材料が無い |

★**分からないときは記録しない**。間違った壁を1つ作ると、
  あとの自動移動がそこを永久に避ける。
"""

from __future__ import annotations

from .models import Direction, Observation, PendingMove, Place, SessionMode
from .repository import NavigationRepository

#: 向き → 座標の差。★「その向きの先のマス」を見るのに使う
_DELTA = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


class NavigationObserver:
    """状態の変化を見て、地図知識を記録する。

    ⚠ **表示のための処理で本体を止めない。** DB が壊れていても
      例外を外へ出さない（警告を1回だけログに出して、以後は静かに諦める）。
    """

    def __init__(self, repository: NavigationRepository, *,
                 move_timeout_frames: int = 30,
                 record_edges: bool = False,
                 record_blocked: bool = False,
                 record_transitions: bool = True,
                 passability=None,
                 on_mismatch=None,
                 logger=None) -> None:
        # ★★ 既定を切に変えた（2026-08-13 / 製品版ログ整理 §12）★★
        #
        #   ⚠ 通常歩行で「通れた／進めなかった」を1マスずつ学習していた。実測:
        #
        #       MapEdge              2,117 行   ← 通れた
        #       MapBlockedDirection    496 行   ← 進めなかった
        #       MapTransition          346 行   ← ★これは ROM から作れない
        #
        #     通常歩行の学習が、残すべき遷移の **7.6 倍**（VisitedTile を
        #     入れると 234 倍）。★しかも中身は **ROM に最初から入っている**。
        #
        #   ★`record_transitions` だけ入のままにする（§16）。
        #     旅の扉・階段・ピット・ワープ・一方通行は ROM 解析だけでは分からない。
        #
        #   ⚠ 引数は**残す**。研究用に取り直したいときがあるため
        #     （`user_config.yaml` の `navigation.record_edges: true`）。
        self.repo = repository
        self.move_timeout_frames = int(move_timeout_frames)
        self.record_edges = record_edges
        self.record_blocked = record_blocked
        self.record_transitions = record_transitions
        # ★★ ROM 解析との食い違いだけを拾う（2026-08-13 / §17）★★
        #   `passability` … `map_passability.json` を読んだ表（無ければ None）
        #   `on_mismatch` … 見つけたときに呼ぶ。★events へ流す口
        #
        #   ⚠ **成功した歩行は記録しない**。食い違いだけ（§17）。
        self.passability = passability
        self.on_mismatch = on_mismatch
        #: ★一度知らせた食い違い。⚠ 同じマスを何度も通るので抑える
        self._seen_mismatch: set = set()
        self.log = logger
        self.pending: PendingMove | None = None
        #: 直前に「ここに居た」と確定した場所。★遷移の起点に使う
        self.last_place: Place | None = None
        self._failed_once = False
        #: ★一度知らせた「想定外の座標変化」。⚠ 同じ跳び方を毎回出さない
        self._seen_jumps: set[tuple[int, int, int, int, int]] = set()
        self.stats = {"edges": 0, "blocked": 0, "transitions": 0, "skipped": 0,
                      "mismatches": 0}

    # --- 入口 ---------------------------------------------------------

    def observe(self, state) -> Observation:
        """状態1つぶんを見る。**毎回呼んでよい**（軽い）。

        ★DB に触るのは「何か分かったとき」だけ。
        """
        try:
            return self._observe(state)
        except Exception as exc:                       # noqa: BLE001
            # ⚠ 移動知識が取れなくてもゲームと GUI は動かす（指示書 11.11）
            self.stats["skipped"] += 1
            if not self._failed_once:
                self._failed_once = True
                if self.log is not None:
                    self.log.warning("移動知識の記録に失敗しました（以後は静かに諦めます）: %s", exc)
            return Observation(skipped="error")

    # --- 中身 ---------------------------------------------------------

    def _place(self, state) -> Place | None:
        """状態から場所を作る。**1つでも読めなければ None**。

        ⚠ `0` は正しい座標。`None` と混ぜない（playbook の原則）。
        """
        if state is None or not getattr(state, "fresh", False):
            return None
        if state.map_id is None or state.map_x is None or state.map_y is None:
            return None
        ptr = state.map_data_pointer
        # ★マップのデータ位置は必ず切り替えバンクの窓にある。
        #   外なら「まだマップを読み込んでいない」（タイトル画面など）。
        if ptr is None or not (0x8000 <= ptr <= 0xBFFF):
            return None
        return Place(state.map_id, ptr, state.map_x, state.map_y)

    def _observe(self, state) -> Observation:
        frame = int(getattr(state, "frame", 0) or 0)

        # --- 戦闘中は何もしない（指示書 5.1）---
        if state is not None and getattr(state, "in_battle", False):
            # ★保留していた移動は**捨てる**。戦闘で止まったのを
            #   「通れなかった」と数えてはいけない（指示書 5.4）。
            self.pending = None
            self.last_place = None
            self.stats["skipped"] += 1
            return Observation(skipped="in_battle")

        place = self._place(state)
        if place is None:
            self.pending = None
            self.last_place = None
            self.stats["skipped"] += 1
            return Observation(skipped="state_incomplete")

        previous = self.last_place
        self.last_place = place

        # --- マップが変わった（指示書 5.5）---
        if previous is not None and previous.map_key != place.map_key:
            direction = self.pending.direction if self.pending else None
            self.pending = None
            if not self.record_transitions:
                self.stats["skipped"] += 1
                return Observation(skipped="transitions_disabled")
            first = self.repo.record_transition(previous, place, direction)
            self.stats["transitions"] += 1
            if first and self.log is not None:
                # ★★ 2026-08-09: 1マスごとの観測は DEBUG（依頼者の指示）★★
                #   > 移動ログもDEBUGレベルで良い
                #   ⚠ 記録（MapEdge / MapTransition）はこれまでどおり残ります。
                #     ★DEBUG にしたのは**ログ行だけ**です。経路探索の土台は
                #       そのまま（`MapGraph` / `WorldGraph` が読んでいます）。
                #   ⚠ 画面に出すと1セッションで145行になり、読みたい行が
                #     押し流されていました（実測）。ファイルには残ります。
                self.log.debug(
                    "新しい遷移: map %02X (%d,%d) -> map %02X (%d,%d)",
                    previous.map_id, previous.x, previous.y,
                    place.map_id, place.x, place.y)
            return Observation(transition=True, direction=direction,
                               place=previous, to_place=place)

        # --- 同じマップ内で座標が動いた ---
        if previous is not None and previous.key != place.key:
            direction = Direction.from_delta(place.x - previous.x,
                                             place.y - previous.y)
            if direction is None:
                # ⚠ 隣の1マスでない（斜め・2マス以上・ワープ）。
                #   **通れたとは言えない**ので記録しない（指示書 5.3）。
                self.pending = None
                self.stats["skipped"] += 1
                # ⚠ これは「取り逃がした」記録です（速く歩くと出ます）。
                #   ★件数は `stats["skipped"]` に積まれるので、
                #     多いかどうかは終了時のまとめで分かります。
                #
                # ★★ 同じ跳び方は1回だけ出す（2026-08-13 / §3・§18B）★★
                #   ⚠ 実測で **1,535 行**あり、同じ座標対が 12 回出ていました。
                #     ★行ったり来たりすると同じ2点が何度も鳴ります。
                jump = (place.map_id, previous.x, previous.y, place.x, place.y)
                if self.log is not None and jump not in self._seen_jumps:
                    self._seen_jumps.add(jump)
                    self.log.debug(
                        "想定外の座標変化: map %02X (%d,%d) -> (%d,%d)",
                        place.map_id, previous.x, previous.y, place.x, place.y)
                return Observation(skipped="unexpected_jump", place=previous,
                                   to_place=place)
            self.pending = None
            # ★★ ROM 解析との食い違いだけを見る（2026-08-13 / §17）★★
            #   ⚠ **成功した歩行そのものは記録しない**。
            #     ★表が「通れない」と言っていたときだけ鳴る。
            #   ⚠⚠ こちら向きの食い違いは**言い訳が効かない**
            #     （実際に歩けたのだから、見立てが誤っている）。
            self._note_mismatch("walked", place.map_id, place.x, place.y,
                                direction.value)
            if not self.record_edges:
                self.stats["skipped"] += 1
                return Observation(skipped="edges_disabled")
            first = self.repo.record_edge(previous, direction, place.x, place.y)
            # ★その方向は通れた。壁の疑いを外す（指示書 5.3 / 11.5）
            self.repo.clear_blocked(previous, direction)
            self.stats["edges"] += 1
            # ⚠ ここにあった「新しい道」の DEBUG は**やめた**
            #   （2026-08-13 / 製品版ログ整理 §12）。
            #   ★通常歩行は ROM 解析で作るので、1行ずつ知らせる意味がない。
            #     実測でこの経路は DEBUG 7,585 行の主因だった。
            #   ⚠ `record_edges: true` に戻した人向けにも出さない
            #     （★研究用途なら DB を直接見るほうが早い）。
            return Observation(moved=True, direction=direction,
                              place=previous, to_place=place)

        # --- 動いていない ---
        held = Direction.parse(getattr(state, "input_direction", None))
        if self.pending is None:
            if held is not None:
                # ★入力を見つけた。**まだ DB に書かない**（指示書 5.2）
                self.pending = PendingMove(
                    place=place, direction=held, input_frame=frame,
                    deadline_frame=frame + self.move_timeout_frames)
            return Observation(skipped="no_change")

        # 押している方向が変わったら、前の保留は捨てる（結果が言えない）
        if held is not None and held is not self.pending.direction:
            self.pending = PendingMove(
                place=place, direction=held, input_frame=frame,
                deadline_frame=frame + self.move_timeout_frames)
            return Observation(skipped="direction_changed")

        # 場所が変わっていたら保留は無効（別の所の話になる）
        if self.pending.place.key != place.key:
            self.pending = None
            return Observation(skipped="place_changed")

        if not self.pending.expired(frame):
            return Observation(skipped="waiting")

        # --- 期限まで動かなかった＝通れなかった（指示書 5.4）---
        pending, self.pending = self.pending, None
        # ★食い違いだけ見る（§17）。⚠ こちら向きは **NPC・演出の可能性が高い**
        #   （実測 235 件が ROM では通れる地形だった）。★重みが違う。
        delta = _DELTA.get(pending.direction.value)
        if delta is not None:
            self._note_mismatch("blocked", pending.place.map_id,
                                pending.place.x + delta[0],
                                pending.place.y + delta[1],
                                pending.direction.value)
        if not self.record_blocked:
            self.stats["skipped"] += 1
            return Observation(skipped="blocked_disabled")
        first = self.repo.record_blocked(pending.place, pending.direction)
        self.stats["blocked"] += 1
        # ⚠ ここにあった「進めない方向」の DEBUG も**やめた**（§12）。
        #   ★理由は上と同じ。⚠ さらにこの観測は「30 フレーム待って動かなかった」
        #     という作りなので、NPC・演出・入力の取りこぼしが混ざる
        #     （実測 235 件が ROM では通れる地形だった）。
        #     ★通れない根拠として弱いものを、1行ずつ知らせない。
        return Observation(blocked=True, direction=pending.direction,
                           place=pending.place)

    # --- ROM 解析との食い違い（§17）------------------------------------

    def _note_mismatch(self, what: str, map_id: int, x: int, y: int,
                       direction: str | None) -> None:
        """食い違っていたら1回だけ知らせる。

        ⚠ **表が無ければ何もしない。** ★「分からない」と「食い違い」を混ぜない。

        ⚠ 同じマスは何度も通るので、**同じ食い違いは1回だけ**にする
          （★でないと、やめたはずの 2,117 行が形を変えて戻ってくる）。
        """
        if self.passability is None:
            return
        try:
            from .mismatch import check_blocked, check_walked

            found = (check_walked if what == "walked" else check_blocked)(
                self.passability, map_id, x, y, direction)
        except Exception:                              # noqa: BLE001
            # ⚠ 表の形が違っても本体は止めない
            return
        if found is None:
            return
        key = (found.kind, map_id, x, y, direction)
        if key in self._seen_mismatch:
            return
        self._seen_mismatch.add(key)
        self.stats["mismatches"] += 1
        if self.log is not None:
            # ★歩けたのに「通れない」と言っていた側は**見立ての誤り**。
            #   ⚠ 進めなかった側は NPC の可能性が高いので段階を下げる。
            #
            # ⚠⚠ **変数へ入れてから呼ばない**（2026-08-13）。
            #   ★`level = self.log.warning` の形にすると、棚卸しの検出器が
            #     拾えず、**数えられない出力**ができる（`audit_log_sites.py`
            #     の「拾えないもの」に書いてある形そのもの）。
            #   ★分岐を2つ書くほうが、少し長くても数えられる。
            args = (found.kind, map_id, x, y, direction or "-",
                    found.expected, found.observed, found.terrain_id)
            fmt = ("ROM 解析と食い違い（%s）: map %02X (%d,%d) %s"
                   " / 表=%s 実際=%s / 地形 %s")
            if found.kind == "walked_but_blocked":
                self.log.warning(fmt, *args)
            else:
                self.log.debug(fmt, *args)
        if self.on_mismatch is not None:
            try:
                self.on_mismatch(found)
            except Exception:                          # noqa: BLE001
                pass

    # --- セッション ---------------------------------------------------

    def start_session(self, mode: SessionMode = SessionMode.MANUAL_OBSERVATION,
                      place: Place | None = None) -> int | None:
        try:
            return self.repo.start_session(mode.value, place or self.last_place)
        except Exception:                              # noqa: BLE001
            return None

    def finish_session(self, session_id: int | None, result: str,
                       stop_reason: str | None = None) -> None:
        if session_id is None:
            return
        try:
            self.repo.finish_session(
                session_id, result, self.last_place,
                steps=self.stats["edges"], transitions=self.stats["transitions"],
                stop_reason=stop_reason)
        except Exception:                              # noqa: BLE001
            pass
