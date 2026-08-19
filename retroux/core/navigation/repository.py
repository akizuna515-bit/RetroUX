"""移動知識ログの保存（2026-07-30 / 指示書 4章・9章）。

★★ **同じ情報は UPSERT で集約する。** ★★
  同じ道を100回通っても**行は増えない**（回数と最終観測日時だけが動く）。

★確度の上げ方は**定数で持ち、設定から変えられる**（指示書 4.2）。
  「3回失敗したら probable」のような閾値をコードに散らさない。
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

from .models import (
    ActionType, Classification, Confidence, Direction, LandmarkKind, Place,
    TransitionType,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclasses.dataclass(frozen=True)
class Thresholds:
    """確度を上げる閾値（指示書 4.2「具体的な閾値は定数化し、設定変更可能に」）。"""

    #: これ以上失敗したら `probable`（★別の時刻での失敗を数える）
    blocked_probable: int = 3
    #: これ以上見たら遷移を `confirmed`
    transition_confirmed: int = 2


class NavigationRepository:
    """地図知識を SQLite へ入れる／出す。

    ⚠ **ここでは判定しない。** 「通れた」「通れなかった」の判断は
      `observer.py` の仕事。ここは言われたことを集約して書くだけ。
    """

    def __init__(self, db, rom_hash: str,
                 thresholds: Thresholds | None = None) -> None:
        self.db = db
        self.rom_hash = rom_hash
        self.t = thresholds or Thresholds()

    @property
    def _conn(self):
        """★`Database` の正面口から借りる（2026-08-01 / 指示書 §9.1）。

        ⚠ 以前は `self.db._conn` と**私的な名前**を直に触っていた。
          外から使う以上それは規約なので、`connection` として公開した。
        """
        return self.db.connection

    # --- 通れた -------------------------------------------------------

    def record_edge(self, place: Place, direction: Direction,
                    to_x: int, to_y: int,
                    action_type: ActionType = ActionType.WALK) -> bool:
        """通れたことを記録する。初めてなら True。

        ★実際に通れたのだから `confirmed`（指示書 4.1）。
        ★同じ辺の再通過では**行を増やさず** `success_count` を足す。
        """
        now = _now()
        self._conn.execute(
            "INSERT INTO MapEdge (rom_hash, map_id, map_ptr, from_x, from_y,"
            " to_x, to_y, direction, action_type, success_count, confidence,"
            " first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)"
            " ON CONFLICT(rom_hash, map_id, map_ptr, from_x, from_y, to_x, to_y)"
            " DO UPDATE SET success_count = success_count + 1,"
            "   last_seen = excluded.last_seen,"
            # ★通れたのだから確度は上げる（下げない）
            "   confidence = 'confirmed'",
            (self.rom_hash, place.map_id, place.map_ptr, place.x, place.y,
             to_x, to_y, direction.value, action_type.value,
             Confidence.CONFIRMED.value, now, now))
        self.db.commit()
        row = self._conn.execute(
            "SELECT success_count FROM MapEdge WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ? AND from_x = ? AND from_y = ? AND to_x = ?"
            " AND to_y = ?",
            (self.rom_hash, place.map_id, place.map_ptr, place.x, place.y,
             to_x, to_y)).fetchone()
        return bool(row) and int(row["success_count"]) == 1

    def clear_blocked(self, place: Place, direction: Direction) -> None:
        """その方向は通れたので、壁の疑いを外す（指示書 5.3 / 11.5）。

        ★★ **行は消さない。** ★★
          「一度は通れなかった」という観測も事実。消すと
          「扉が閉まっていた」「NPCが居た」という情報まで失う。
          `success_count` を足し、分類を `unknown_block` に戻して
          確度を `provisional` へ**下げる**。
        """
        self._conn.execute(
            "UPDATE MapBlockedDirection SET success_count = success_count + 1,"
            "  classification = ?, confidence = ?, last_seen = ?"
            " WHERE rom_hash = ? AND map_id = ? AND map_ptr = ? AND x = ?"
            "   AND y = ? AND direction = ?",
            (Classification.UNKNOWN_BLOCK.value, Confidence.PROVISIONAL.value,
             _now(), self.rom_hash, place.map_id, place.map_ptr,
             place.x, place.y, direction.value))
        self.db.commit()

    # --- 通れなかった -------------------------------------------------

    def record_blocked(self, place: Place, direction: Direction) -> bool:
        """通れなかったことを記録する。初めてなら True。

        ★★ **初回は必ず `unknown_block` + `provisional`。** ★★
          失敗1回で壁と決めない（指示書 2.4）。
        """
        now = _now()
        self._conn.execute(
            "INSERT INTO MapBlockedDirection (rom_hash, map_id, map_ptr, x, y,"
            " direction, blocked_count, classification, confidence,"
            " first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)"
            " ON CONFLICT(rom_hash, map_id, map_ptr, x, y, direction)"
            " DO UPDATE SET blocked_count = blocked_count + 1,"
            "   last_seen = excluded.last_seen",
            (self.rom_hash, place.map_id, place.map_ptr, place.x, place.y,
             direction.value, Classification.UNKNOWN_BLOCK.value,
             Confidence.PROVISIONAL.value, now, now))
        self.db.commit()

        row = self._conn.execute(
            "SELECT blocked_count, success_count FROM MapBlockedDirection"
            " WHERE rom_hash = ? AND map_id = ? AND map_ptr = ? AND x = ?"
            "   AND y = ? AND direction = ?",
            (self.rom_hash, place.map_id, place.map_ptr, place.x, place.y,
             direction.value)).fetchone()
        if row is None:
            return False
        blocked, success = int(row["blocked_count"]), int(row["success_count"])
        # ★★ 一度でも通れた方向は、何度失敗しても確度を上げない ★★
        #   扉やNPCのように「開くときもある」ものを壁にしないため。
        if success == 0 and blocked >= self.t.blocked_probable:
            self._conn.execute(
                "UPDATE MapBlockedDirection SET confidence = ?"
                " WHERE rom_hash = ? AND map_id = ? AND map_ptr = ? AND x = ?"
                "   AND y = ? AND direction = ?",
                (Confidence.PROBABLE.value, self.rom_hash, place.map_id,
                 place.map_ptr, place.x, place.y, direction.value))
            self.db.commit()
        return blocked == 1

    # --- 遷移した -----------------------------------------------------

    def record_transition(self, source: Place, target: Place,
                          direction: Direction | None = None,
                          transition_type: TransitionType = TransitionType.UNKNOWN
                          ) -> bool:
        """マップが変わったことを記録する。初めてなら True。

        ★同じ遷移を再度通っても**行を増やさず** `observed_count` を足す。
        """
        now = _now()
        self._conn.execute(
            "INSERT INTO MapTransition (rom_hash, from_map_id, from_map_ptr,"
            " from_x, from_y, to_map_id, to_map_ptr, to_x, to_y,"
            " transition_type, direction_hint, observed_count, confidence,"
            " first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)"
            " ON CONFLICT(rom_hash, from_map_id, from_map_ptr, from_x, from_y,"
            "             to_map_id, to_map_ptr, to_x, to_y)"
            " DO UPDATE SET observed_count = observed_count + 1,"
            "   last_seen = excluded.last_seen",
            (self.rom_hash, source.map_id, source.map_ptr, source.x, source.y,
             target.map_id, target.map_ptr, target.x, target.y,
             transition_type.value,
             direction.value if direction else None,
             Confidence.PROVISIONAL.value, now, now))
        self.db.commit()

        row = self._conn.execute(
            "SELECT observed_count FROM MapTransition WHERE rom_hash = ?"
            " AND from_map_id = ? AND from_map_ptr = ? AND from_x = ?"
            " AND from_y = ? AND to_map_id = ? AND to_map_ptr = ? AND to_x = ?"
            " AND to_y = ?",
            (self.rom_hash, source.map_id, source.map_ptr, source.x, source.y,
             target.map_id, target.map_ptr, target.x, target.y)).fetchone()
        if row is None:
            return False
        count = int(row["observed_count"])
        if count >= self.t.transition_confirmed:
            self._conn.execute(
                "UPDATE MapTransition SET confidence = ? WHERE rom_hash = ?"
                " AND from_map_id = ? AND from_map_ptr = ? AND from_x = ?"
                " AND from_y = ? AND to_map_id = ? AND to_map_ptr = ?"
                " AND to_x = ? AND to_y = ?",
                (Confidence.CONFIRMED.value, self.rom_hash,
                 source.map_id, source.map_ptr, source.x, source.y,
                 target.map_id, target.map_ptr, target.x, target.y))
            self.db.commit()
        return count == 1

    # --- 読む ---------------------------------------------------------

    def edges(self, map_id: int, map_ptr: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM MapEdge WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ?", (self.rom_hash, map_id, map_ptr)).fetchall()
        return [dict(r) for r in rows]

    def blocked(self, map_id: int, map_ptr: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM MapBlockedDirection WHERE rom_hash = ?"
            " AND map_id = ? AND map_ptr = ?",
            (self.rom_hash, map_id, map_ptr)).fetchall()
        return [dict(r) for r in rows]

    def transitions(self, map_id: int | None = None,
                    map_ptr: int | None = None) -> list[dict]:
        if map_id is None:
            rows = self._conn.execute(
                "SELECT * FROM MapTransition WHERE rom_hash = ?"
                " ORDER BY id", (self.rom_hash,)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM MapTransition WHERE rom_hash = ?"
                " AND from_map_id = ? AND from_map_ptr = ? ORDER BY id",
                (self.rom_hash, map_id, map_ptr)).fetchall()
        return [dict(r) for r in rows]

    def transitions_into(self, map_id: int, map_ptr: int) -> list[dict]:
        """そのマップへ**入ってきた**遷移。

        ★階層の推定に要る。「どこから来たか」が分からないと
          「1つ下りた」のか「1つ上がった」のか言えない。
        """
        rows = self._conn.execute(
            "SELECT * FROM MapTransition WHERE rom_hash = ?"
            " AND to_map_id = ? AND to_map_ptr = ? ORDER BY id",
            (self.rom_hash, map_id, map_ptr)).fetchall()
        return [dict(r) for r in rows]

    # --- 人が決めたこと（フェーズ5・6）---------------------------------

    def map_override(self, map_id: int, map_ptr: int) -> dict | None:
        """人が入れた階層・名前。無ければ None。"""
        row = self._conn.execute(
            "SELECT * FROM MapOverride WHERE rom_hash = ?"
            " AND map_id = ? AND map_ptr = ?",
            (self.rom_hash, map_id, map_ptr)).fetchone()
        return dict(row) if row is not None else None

    #: 階層だけ見たいときの別名（`FloorEstimator` が呼ぶ）
    floor_override = map_override

    def set_map_override(self, map_id: int, map_ptr: int, *,
                         floor_index: int | None = None,
                         floor_label: str | None = None,
                         display_name: str | None = None,
                         note: str | None = None,
                         keep_missing: bool = True) -> None:
        """人が階層・名前を決める。★**最優先**として保存する。

        ⚠ `keep_missing=True`（既定）のとき、渡さなかった項目は
          **前の値を残す**。名前だけ直したいのに階層が消える、を防ぐ。
          全部入れ替えたいときは `keep_missing=False`。
        """
        now = _now()
        if keep_missing:
            previous = self.map_override(map_id, map_ptr) or {}
            if floor_index is None:
                floor_index = previous.get("floor_index")
            if floor_label is None:
                floor_label = previous.get("floor_label")
            if display_name is None:
                display_name = previous.get("display_name")
            if note is None:
                note = previous.get("note")
        self._conn.execute(
            "INSERT INTO MapOverride (rom_hash, map_id, map_ptr,"
            " floor_index, floor_label, display_name, note,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(rom_hash, map_id, map_ptr)"
            " DO UPDATE SET floor_index = excluded.floor_index,"
            " floor_label = excluded.floor_label,"
            " display_name = excluded.display_name,"
            " note = excluded.note, updated_at = excluded.updated_at",
            (self.rom_hash, map_id, map_ptr, floor_index, floor_label,
             display_name, note, now, now))
        self.db.commit()

    def set_floor_override(self, map_id: int, map_ptr: int,
                           floor_index: int | None,
                           floor_label: str | None = None,
                           note: str | None = None) -> None:
        """階層だけ決める。

        ⚠ `floor_index=None`（「分からない」）を**入れられる**ようにするため、
          ここでは `keep_missing=False` にはせず、階層の2つだけ入れ替える。
        """
        previous = self.map_override(map_id, map_ptr) or {}
        self.set_map_override(
            map_id, map_ptr, floor_index=floor_index, floor_label=floor_label,
            display_name=previous.get("display_name"),
            note=note if note is not None else previous.get("note"),
            keep_missing=False)

    def clear_map_override(self, map_id: int, map_ptr: int) -> None:
        """人の指定を取り消す（ROM 由来の値に戻る）。"""
        self._conn.execute(
            "DELETE FROM MapOverride WHERE rom_hash = ?"
            " AND map_id = ? AND map_ptr = ?",
            (self.rom_hash, map_id, map_ptr))
        self.db.commit()

    #: 名前が同じことをするので別名（呼ぶ側の意図が読めるように）
    clear_floor_override = clear_map_override

    def map_overrides(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM MapOverride WHERE rom_hash = ?"
            " ORDER BY map_id, map_ptr", (self.rom_hash,)).fetchall()
        return [dict(r) for r in rows]

    # --- 遷移の種類を人が直す（フェーズ4）------------------------------

    def set_transition_type(self, transition_id: int, kind,
                            confidence: Confidence = Confidence.CONFIRMED
                            ) -> bool:
        """遷移の種類を人が決める。戻り値は**直せたか**。

        ★★ **人が見たものがいちばん確か。** ★★ 観測側は種類を
          `unknown` で入れる（画面から階段か扉かは判定できない）。
          ここで直した値は `confirmed` になり、階層の推定に使われる。

        ⚠ 読めない種類は**入れない**（`unknown` に戻したりもしない）。
          綴り違いが静かに別の種類として保存される。
        """
        parsed = TransitionType.parse(kind)
        if parsed is None:
            return False
        cur = self._conn.execute(
            "UPDATE MapTransition SET transition_type = ?, confidence = ?,"
            " last_seen = ? WHERE id = ? AND rom_hash = ?",
            (parsed.value, Confidence(confidence).value, _now(),
             int(transition_id), self.rom_hash))
        self.db.commit()
        return int(cur.rowcount) > 0

    def transitions_at(self, place: Place) -> list[dict]:
        """そのマスから**出る**遷移。★立っている所を直すために使う。"""
        rows = self._conn.execute(
            "SELECT * FROM MapTransition WHERE rom_hash = ?"
            " AND from_map_id = ? AND from_map_ptr = ? AND from_x = ?"
            " AND from_y = ? ORDER BY id",
            (self.rom_hash, place.map_id, place.map_ptr, place.x,
             place.y)).fetchall()
        return [dict(r) for r in rows]

    # --- 人が書いたメモ（フェーズ6）------------------------------------

    def set_note(self, place: Place, body: str) -> bool:
        """メモを置く／書き直す。戻り値は**新しく作ったか**。

        ⚠ 空文字は保存しない（**消す**）。空のメモを残すと、
          地図に「中身の無いメモ」が並ぶ。
        """
        text = (body or "").strip()
        if not text:
            self.delete_note(place)
            return False
        # ★「新しく作ったか」は**書く前に**見る。UPSERT のあとでは
        #   作ったのか書き直したのか区別できない。
        existed = self.note(place) is not None
        now = _now()
        self._conn.execute(
            "INSERT INTO MapNote (rom_hash, map_id, map_ptr, x, y, body,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(rom_hash, map_id, map_ptr, x, y)"
            " DO UPDATE SET body = excluded.body,"
            " updated_at = excluded.updated_at",
            (self.rom_hash, place.map_id, place.map_ptr, place.x, place.y,
             text, now, now))
        self.db.commit()
        return not existed

    def note(self, place: Place) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM MapNote WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ? AND x = ? AND y = ?",
            (self.rom_hash, place.map_id, place.map_ptr, place.x,
             place.y)).fetchone()
        return dict(row) if row is not None else None

    def delete_note(self, place: Place) -> int:
        cur = self._conn.execute(
            "DELETE FROM MapNote WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ? AND x = ? AND y = ?",
            (self.rom_hash, place.map_id, place.map_ptr, place.x, place.y))
        self.db.commit()
        return int(cur.rowcount)

    def notes(self, map_id: int, map_ptr: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM MapNote WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ? ORDER BY y, x",
            (self.rom_hash, map_id, map_ptr)).fetchall()
        return [dict(r) for r in rows]

    # --- 目印（フェーズ6）----------------------------------------------

    def set_landmark(self, place: Place, kind, label: str | None = None, *,
                     source: str = "manual",
                     confidence: Confidence = Confidence.CONFIRMED) -> bool:
        """目印を置く。戻り値は**置けたか**。

        ⚠ 種類が読めなければ**置かない**（`other` に丸めない）。
          綴り違いが静かに増えると、あとで種類で絞れなくなる。
        """
        parsed = LandmarkKind.parse(kind)
        if parsed is None:
            return False
        now = _now()
        self._conn.execute(
            "INSERT INTO MapLandmark (rom_hash, map_id, map_ptr, x, y, kind,"
            " label, source, confidence, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(rom_hash, map_id, map_ptr, x, y, kind)"
            " DO UPDATE SET label = excluded.label,"
            " source = excluded.source, confidence = excluded.confidence,"
            " updated_at = excluded.updated_at",
            (self.rom_hash, place.map_id, place.map_ptr, place.x, place.y,
             parsed.value, label, source, Confidence(confidence).value,
             now, now))
        self.db.commit()
        return True

    def delete_landmark(self, place: Place, kind) -> int:
        parsed = LandmarkKind.parse(kind)
        if parsed is None:
            return 0
        cur = self._conn.execute(
            "DELETE FROM MapLandmark WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ? AND x = ? AND y = ? AND kind = ?",
            (self.rom_hash, place.map_id, place.map_ptr, place.x, place.y,
             parsed.value))
        self.db.commit()
        return int(cur.rowcount)

    def landmarks(self, map_id: int, map_ptr: int, kind=None) -> list[dict]:
        """そのマップの目印。`kind` を渡すとその種類だけ。

        ⚠ 読めない `kind` を渡されたら**空**を返す（全件返さない）。
          全件返すと「宝箱だけ探したのに全部出た」ことに気づけない。
        """
        if kind is None:
            rows = self._conn.execute(
                "SELECT * FROM MapLandmark WHERE rom_hash = ? AND map_id = ?"
                " AND map_ptr = ? ORDER BY y, x",
                (self.rom_hash, map_id, map_ptr)).fetchall()
            return [dict(r) for r in rows]
        parsed = LandmarkKind.parse(kind)
        if parsed is None:
            return []
        rows = self._conn.execute(
            "SELECT * FROM MapLandmark WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ? AND kind = ? ORDER BY y, x",
            (self.rom_hash, map_id, map_ptr, parsed.value)).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        """溜まっている知識の量（画面とログに出す）。"""
        def one(sql: str) -> int:
            return int(self._conn.execute(sql, (self.rom_hash,)).fetchone()[0])

        return {
            "edges": one("SELECT COUNT(*) FROM MapEdge WHERE rom_hash = ?"),
            "blocked": one("SELECT COUNT(*) FROM MapBlockedDirection"
                           " WHERE rom_hash = ?"),
            "transitions": one("SELECT COUNT(*) FROM MapTransition"
                               " WHERE rom_hash = ?"),
            # ★人が入れたもの（フェーズ6）。観測と分けて数える
            "notes": one("SELECT COUNT(*) FROM MapNote WHERE rom_hash = ?"),
            "landmarks": one("SELECT COUNT(*) FROM MapLandmark"
                             " WHERE rom_hash = ?"),
        }

    # --- セッション ---------------------------------------------------

    def start_session(self, mode: str, place: Place | None) -> int:
        cur = self._conn.execute(
            "INSERT INTO NavigationSession (rom_hash, started_at, mode,"
            " start_map_id, start_map_ptr, start_x, start_y)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (self.rom_hash, _now(), mode,
             place.map_id if place else None, place.map_ptr if place else None,
             place.x if place else None, place.y if place else None))
        self.db.commit()
        return int(cur.lastrowid)

    def finish_session(self, session_id: int, result: str,
                       place: Place | None = None, *, steps: int = 0,
                       transitions: int = 0, battles: int = 0,
                       stop_reason: str | None = None) -> None:
        self._conn.execute(
            "UPDATE NavigationSession SET ended_at = ?, result = ?,"
            " end_map_id = ?, end_map_ptr = ?, end_x = ?, end_y = ?,"
            " steps_moved = ?, transitions = ?, battles = ?, stop_reason = ?"
            " WHERE id = ?",
            (_now(), result,
             place.map_id if place else None, place.map_ptr if place else None,
             place.x if place else None, place.y if place else None,
             steps, transitions, battles, stop_reason, session_id))
        self.db.commit()
