"""SQLite の永続化層。

スキーマは docs/design/mvp1-spec.md §4 に準拠。
`rom_hash` は PRG-only SHA-256（DEV-10、retroux/core/rom.py 参照）。
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS Rom (
    rom_hash    TEXT PRIMARY KEY,   -- PRG-only SHA-256（iNESヘッダを除く）
    title       TEXT NOT NULL,
    region      TEXT NOT NULL,
    mapper      INTEGER,
    first_seen  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS EncounteredMonster (
    rom_hash        TEXT NOT NULL REFERENCES Rom(rom_hash),
    monster_id      INTEGER NOT NULL,
    first_seen_at   TEXT NOT NULL,
    encounter_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (rom_hash, monster_id)
);

CREATE TABLE IF NOT EXISTS BattleLog (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rom_hash        TEXT NOT NULL REFERENCES Rom(rom_hash),
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    duration_ms     INTEGER,
    duration_frames INTEGER,
    monster_ids     TEXT NOT NULL,      -- JSON配列
    is_first_encounter INTEGER NOT NULL,
    is_boss         INTEGER NOT NULL,
    -- ⚠ 2026-08-12 訂正: ここは「win / retreat」と書いてあったが、
    --   ★`retreat` という値は**存在しない**。実データ 522 件は
    --   win 500 / flee 13 / lose 6 / enemy_fled 3。
    --   決めているのは bridge.lua:3189（saw_victory / 全滅 / 自分が逃走 / 敵が逃走）。
    result          TEXT,               -- win | lose | flee | enemy_fled
    exp_gained      INTEGER,            -- 同上
    gold_gained     INTEGER,            -- 同上
    speed_applied   REAL,
    auto_input_used INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_battlelog_started ON BattleLog(rom_hash, started_at);

-- events.jsonl をどこまで読んだか。
-- Lua 側はセッションをまたいで追記し続けるため、これを保存しておかないと
-- 記録プロセスを再起動するたびに過去の戦闘を重複記録してしまう。
-- head_sig はファイル先頭の署名。events.jsonl が削除されて作り直された場合に
-- 保存済みの位置をそのまま使うと、新しいセッションの先頭を読み飛ばしてしまう。
-- 行動単位ログ（MVP2 Phase 3 / 指示書 7.4・7.5）。
--
-- ★指示書には予測ダメージ・スコア・次点候補の列もあるが、**作っていない**。
--   計算する材料が無く、空の列を置くと「そういう値」に見えるため。
--   分かってから足す。
--
-- ★1つの表にまとめてある（Action と Observation を分けていない）。
--   いま入るのは「AIが決めたこと」と「HPがこう変わった」の2種類だけで、
--   分けても片方が数行になる。**kind で区別**し、
--   増えて意味が出てきたら分ける。
CREATE TABLE IF NOT EXISTS BattleEvent (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id    INTEGER NOT NULL REFERENCES BattleLog(id),
    turn_no      INTEGER NOT NULL DEFAULT 0,
    sequence_no  INTEGER NOT NULL DEFAULT 0,
    frame_no     INTEGER,
    kind         TEXT NOT NULL,      -- party_hp / party_mp / enemy_hp / action
    actor        TEXT,               -- 誰が / 誰の
    target       TEXT,
    action_name  TEXT,
    value_before INTEGER,
    value_after  INTEGER,
    delta        INTEGER,
    selected_by  TEXT,               -- ai / manual（分かるときだけ）
    reason       TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_battle_event_battle
    ON BattleEvent(battle_id, turn_no, sequence_no);

CREATE TABLE IF NOT EXISTS IngestState (
    source     TEXT PRIMARY KEY,
    offset     INTEGER NOT NULL,
    head_sig   TEXT,
    updated_at TEXT NOT NULL
);

-- 歩いたマス（2026-07-29 / 地図）。
--
-- ★★ **「自分が通った所」だけを持つ。** ★★
--   依頼者の決定（Q3）: 完全地図は出さない。ダンジョンの探索を潰さない。
--   だから ROM から地形を入れるのではなく、**実際に居た座標だけ**を貯める。
--
-- ⚠ `map_id` だけでは足りない。同じ ID でも階が違うことがあるので、
--   いま読み込んでいるマップのデータ位置（`$23-$24`）も鍵に含める。
CREATE TABLE IF NOT EXISTS VisitedTile (
    rom_hash   TEXT NOT NULL,
    map_id     INTEGER NOT NULL,
    map_ptr    INTEGER NOT NULL,
    x          INTEGER NOT NULL,
    y          INTEGER NOT NULL,
    visits     INTEGER NOT NULL DEFAULT 1,
    -- 画面に出ていた色（RGB444 の16進3文字）。★分からなければ NULL。
    --   これがあると、地図をゲーム画面と同じ色で描ける。
    color      TEXT,
    -- ネームテーブルのタイルID（16進2文字 / 2026-08-01）。★分からなければ NULL。
    --   ⚠ `color` は各マスの**中心1画素**なので、洞窟の床（黒地に赤い点）が
    --     ほぼ黒になり、**主人公自身の色**まで拾っていた。
    --   ★タイルIDはぶれず（実測 960/960 一致）、スプライトも混ざらない。
    tile       TEXT,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    PRIMARY KEY (rom_hash, map_id, map_ptr, x, y)
);
CREATE INDEX IF NOT EXISTS idx_visited_map
    ON VisitedTile(rom_hash, map_id, map_ptr);

-- ============================================================
-- 移動知識ログ（2026-07-30 / 指示書 `input/移動知識ログ・経路記録仕様.md`）
-- ============================================================
--
-- ★★ **保存するのは「どのキーを何回押したか」ではない。** ★★
--   「この道は通れる」「この方向は今のところ通れない」
--   「この階段は別のマップにつながる」という**再利用できる地図知識**。
--
-- ★同じ情報は UPSERT で集約する。同じ道を100回通っても**行は増えない**
--   （回数と最終観測日時だけが動く）。
--
-- ⚠ 毎フレームの座標履歴はここに入れない（入れると意味が変わり、肥大化する）。

-- 通れると分かった隣接関係。
CREATE TABLE IF NOT EXISTS MapEdge (
    rom_hash        TEXT NOT NULL,
    map_id          INTEGER NOT NULL,
    map_ptr         INTEGER NOT NULL,
    from_x          INTEGER NOT NULL,
    from_y          INTEGER NOT NULL,
    to_x            INTEGER NOT NULL,
    to_y            INTEGER NOT NULL,
    direction       TEXT NOT NULL,
    action_type     TEXT NOT NULL DEFAULT 'walk',
    success_count   INTEGER NOT NULL DEFAULT 1,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    movement_cost   REAL NOT NULL DEFAULT 1.0,
    confidence      TEXT NOT NULL DEFAULT 'confirmed',
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    PRIMARY KEY (rom_hash, map_id, map_ptr, from_x, from_y, to_x, to_y)
);
CREATE INDEX IF NOT EXISTS idx_mapedge_from
    ON MapEdge(rom_hash, map_id, map_ptr, from_x, from_y);

-- 通れなかった方向の観測。
--
-- ⚠⚠ **失敗1回で壁と確定しない**（指示書 2.4）。同じ「動かなかった」に
--   壁 / NPC / 扉 / イベント / 入力取りこぼし / 会話中 / メニュー中 が化ける。
--   だから初回は必ず `unknown_block` + `provisional` で入れ、
--   別の時刻に何度も失敗して初めて確度を上げる。
--   **一度でも通れたら通行可能を優先する。**
CREATE TABLE IF NOT EXISTS MapBlockedDirection (
    rom_hash        TEXT NOT NULL,
    map_id          INTEGER NOT NULL,
    map_ptr         INTEGER NOT NULL,
    x               INTEGER NOT NULL,
    y               INTEGER NOT NULL,
    direction       TEXT NOT NULL,
    blocked_count   INTEGER NOT NULL DEFAULT 1,
    success_count   INTEGER NOT NULL DEFAULT 0,
    classification  TEXT NOT NULL DEFAULT 'unknown_block',
    confidence      TEXT NOT NULL DEFAULT 'provisional',
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    PRIMARY KEY (rom_hash, map_id, map_ptr, x, y, direction)
);

-- 別マップへの遷移（階段・出口・旅の扉など）。
CREATE TABLE IF NOT EXISTS MapTransition (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    rom_hash            TEXT NOT NULL,
    from_map_id         INTEGER NOT NULL,
    from_map_ptr        INTEGER NOT NULL,
    from_x              INTEGER NOT NULL,
    from_y              INTEGER NOT NULL,
    to_map_id           INTEGER NOT NULL,
    to_map_ptr          INTEGER NOT NULL,
    to_x                INTEGER NOT NULL,
    to_y                INTEGER NOT NULL,
    transition_type     TEXT NOT NULL DEFAULT 'unknown',
    direction_hint      TEXT,
    location_id         TEXT,
    section_from        TEXT,
    section_to          TEXT,
    observed_count      INTEGER NOT NULL DEFAULT 1,
    confidence          TEXT NOT NULL DEFAULT 'provisional',
    first_seen          TEXT NOT NULL,
    last_seen           TEXT NOT NULL,
    UNIQUE (rom_hash, from_map_id, from_map_ptr, from_x, from_y,
            to_map_id, to_map_ptr, to_x, to_y)
);

-- 人がそのマップについて決めたこと（2026-07-30 / マッパー仕様 フェーズ5・6）。
--
-- ★★ **人の指定が最優先。** ★★
--   階層は3つの出どころがある:
--     1. 人がここに入れた値        ← いちばん強い
--     2. ROM 由来の対応表（`map_bindings.yaml` の floor_index）
--     3. 上下移動からの推定
--   食い違ったら**黙って片方を選ばず、食い違いとして出す**。
--
-- ⚠ 「入口の階」は逆アセンブルから決められないことを確かめた:
--     ローレシア           1F/2F/B1 -> 入口は 1F（地上側）
--     ロンダルキアへの洞窟 B1/1F..6F -> 入口は B1（地下側）
--   符号でも map_id の並び順でも、どちらか片方しか当たらない。
--   → 人が直せるようにここを用意した。
--
-- ★`display_name` は名前の上書き。**ファイル（locations.yaml）は触らない**。
--   日本語名の大半は ROM から取っていないので、間違っていたらここで直せる。
--   ⚠ 名前は表示だけ。自動移動は map_id と階層で動くので壊れない。
CREATE TABLE IF NOT EXISTS MapOverride (
    rom_hash     TEXT NOT NULL,
    map_id       INTEGER NOT NULL,
    map_ptr      INTEGER NOT NULL,
    floor_index  INTEGER,
    floor_label  TEXT,
    display_name TEXT,
    note         TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (rom_hash, map_id, map_ptr)
);

-- 人が書いたメモ（2026-07-30 / マッパー仕様 フェーズ6）。
--
-- ★★ **これは人の言葉。機械が上書きしない。** ★★
--   「ここに宝箱」「この階段は行き止まり」のような、
--   観測では取れない気づきを置く場所。
--
-- ⚠ 座標ごとに1件。同じマスに書き直したら**上書き**（行は増えない）。
--   ⚠ 消したいときは削除する（空文字で残すと「空のメモ」が地図に出る）。
CREATE TABLE IF NOT EXISTS MapNote (
    rom_hash    TEXT NOT NULL,
    map_id      INTEGER NOT NULL,
    map_ptr     INTEGER NOT NULL,
    x           INTEGER NOT NULL,
    y           INTEGER NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (rom_hash, map_id, map_ptr, x, y)
);
CREATE INDEX IF NOT EXISTS idx_mapnote_map
    ON MapNote(rom_hash, map_id, map_ptr);

-- 目印（2026-07-30 / マッパー仕様 フェーズ6）。
--
-- ★メモとの違い: **種類が決まっている**（宝箱・階段・店・王様…）。
--   種類が決まっているので、あとで「宝箱まで自動で行く」に使える。
--   メモは自由文なので機械には使えない。
--
-- ⚠ 種類を勝手に増やさない。増やすなら
--   `retroux/core/navigation/models.py` の `LandmarkKind` に足す
--   （文字列を直書きすると、綴り違いが静かに別の種類になる）。
CREATE TABLE IF NOT EXISTS MapLandmark (
    rom_hash    TEXT NOT NULL,
    map_id      INTEGER NOT NULL,
    map_ptr     INTEGER NOT NULL,
    x           INTEGER NOT NULL,
    y           INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    label       TEXT,
    -- 人が置いたか、観測から作ったか。★出どころを混ぜない
    source      TEXT NOT NULL DEFAULT 'manual',
    confidence  TEXT NOT NULL DEFAULT 'confirmed',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (rom_hash, map_id, map_ptr, x, y, kind)
);
CREATE INDEX IF NOT EXISTS idx_maplandmark_map
    ON MapLandmark(rom_hash, map_id, map_ptr);

-- 観測のまとまり。★各歩行ステップは入れない（開始・終了・結果だけ）。
CREATE TABLE IF NOT EXISTS NavigationSession (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rom_hash        TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    start_map_id    INTEGER,
    start_map_ptr   INTEGER,
    start_x         INTEGER,
    start_y         INTEGER,
    end_map_id      INTEGER,
    end_map_ptr     INTEGER,
    end_x           INTEGER,
    end_y           INTEGER,
    mode            TEXT NOT NULL,
    result          TEXT,
    steps_moved     INTEGER NOT NULL DEFAULT 0,
    transitions     INTEGER NOT NULL DEFAULT 0,
    replans         INTEGER NOT NULL DEFAULT 0,
    battles         INTEGER NOT NULL DEFAULT 0,
    stop_reason     TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """SQLite への薄いリポジトリ。

    使い方:
        with Database(path) as db:
            db.register_rom(...)
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        # ★書き込みが**1件あたり 127ms** かかっていた（実測 / MVP2 Phase 1）。
        #   1イベント = 1コミット = 1回の fsync だったため、
        #   溜まった 4820 件の取り込みに10分近くかかり、GUI が固まって見えた。
        #
        #   WAL にすると、コミットのたびにデータ本体を fsync しなくてよくなる。
        #   synchronous=NORMAL は「OSが落ちたら**最後の数コミットが失われうる**」
        #   という妥協で、ここでは許容できる:
        #     ・失うのは戦闘ログの末尾数件だけ（ゲームの進行には影響しない）
        #     ・events.jsonl が残っているので、取り込み位置を戻せば復元できる
        #   金勘定を扱う DB ならこの妥協はしない。
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._bulk_depth = 0
        self._conn.commit()

    # 後から足した列。★`CREATE TABLE IF NOT EXISTS` は
    #   **既にある表に列を足さない**ので、別に足す必要がある。
    #
    # ⚠⚠ これを忘れて実害が出た（2026-07-29）。`VisitedTile.color` を
    #   スキーマに書き足しただけで済ませたため、**すでに DB を持っている
    #   環境（＝実際に遊んでいる人）だけ**が地図の記録に失敗する状態になった。
    #   新規の DB では通るのでテストも通ってしまう。
    ADDED_COLUMNS = [
        ("VisitedTile", "color", "TEXT"),
        # ★ネームテーブルのタイルID（2026-08-01 / 課題 #65）。
        #   ⚠ 色より確かで、主人公のスプライトが混ざらない。
        ("VisitedTile", "tile", "TEXT"),
        # --- 背景キャラクタ方式（2026-08-02 / マップ指示書 §12.1）--------
        #
        # ★★ **画像を直接持たず、メタタイルの鍵を参照する。** ★★
        #   同じ見た目のマスが何百とあるので、画像を重複させない。
        #   実物は `work/map-assets/metatiles/<key>/` にある。
        ("VisitedTile", "metatile_key", "TEXT"),
        # ★何回そのメタタイルを見たか（指示書 §12.2）
        ("VisitedTile", "seen_count", "INTEGER"),
        # ★確度（provisional / probable / confirmed / conflict）§12.3
        ("VisitedTile", "confidence", "TEXT"),
        # ★どの状態で採ったか。⚠ FIELD_IDLE 以外は正式保存しない（§6.2）
        ("VisitedTile", "source_state", "TEXT"),
    ]

    def _migrate(self) -> None:
        """後から足した列を、既存の DB にも足す。"""
        for table, column, decl in self.ADDED_COLUMNS:
            try:
                have = {r["name"] for r in self._conn.execute(
                    f"PRAGMA table_info({table})")}
            except sqlite3.Error:
                continue
            if not have or column in have:
                continue
            try:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            except sqlite3.Error:
                # ⚠ 足せなくても本体は動かす（その列を使う機能だけが効かない）
                pass

    @contextmanager
    def bulk(self):
        """複数の書き込みを1つのコミットにまとめる。

        ★取り込みのように「まとまって届くもの」は、1件ずつコミットすると
          件数ぶんの fsync が並ぶ。溜まったぶんを流し込むときに効く。
          途中で失敗したら**まとめて捨てる**（半端な状態で残さない）。
        """
        depth = self._bulk_depth
        self._bulk_depth = depth + 1
        try:
            yield self
        except Exception:
            self._bulk_depth = depth
            if depth == 0:
                self._conn.rollback()
            raise
        # ★深さを戻して**から**コミットする。戻す前に _commit() を呼ぶと
        #   「bulk の中」と判定されて何もコミットされない（一度そう書いて踏んだ）。
        self._bulk_depth = depth
        if depth == 0:
            self._conn.commit()

    def _commit(self) -> None:
        """bulk() の中ではコミットしない（外側でまとめて1回にする）。"""
        if self._bulk_depth == 0:
            self._conn.commit()

    # --- Repository へ貸すもの（2026-08-01 / 指示書 §9.1）---------------
    #
    # ★★ 機能別の SQL は Repository が持つ（§9.2）★★
    #   ⚠ そのとき接続をどう渡すかが要る。`db._conn` を触らせていたが、
    #     **私的な名前を外から使うのは、規約が無いのと同じ**。
    #     ここに正面口を置き、変えてよい所と変えてはいけない所を分ける。

    @property
    def connection(self) -> sqlite3.Connection:
        """Repository が SQL を出すための接続。

        ⚠ **接続の開け閉めは Database の仕事**。借りた側は閉じないこと。
        """
        return self._conn

    def commit(self) -> None:
        """Repository からの確定。★`bulk()` の中なら外側まで待つ。

        ⚠ ここを飛ばして `connection.commit()` を直に呼ぶと、
          `bulk()` でまとめている途中でも確定してしまう。
        """
        self._commit()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    # --- Rom ---------------------------------------------------------

    def register_rom(self, rom_hash: str, title: str, region: str,
                     mapper: int | None = None) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO Rom(rom_hash, title, region, mapper, first_seen)"
            " VALUES (?, ?, ?, ?, ?)",
            (rom_hash, title, region, mapper, _now()),
        )
        self._commit()

    # --- EncounteredMonster ------------------------------------------

    def encountered_ids(self, rom_hash: str) -> set[int]:
        rows = self._conn.execute(
            "SELECT monster_id FROM EncounteredMonster WHERE rom_hash = ?",
            (rom_hash,),
        ).fetchall()
        return {int(r["monster_id"]) for r in rows}

    def mark_encountered(self, rom_hash: str, monster_ids: Iterable[int]) -> set[int]:
        """遭遇を記録し、**今回はじめて登録されたID**を返す。

        既知のIDは encounter_count を増やすだけで、戻り値には含めない。
        """
        newly: set[int] = set()
        for monster_id in monster_ids:
            cur = self._conn.execute(
                "INSERT INTO EncounteredMonster(rom_hash, monster_id, first_seen_at)"
                " VALUES (?, ?, ?)"
                " ON CONFLICT(rom_hash, monster_id)"
                " DO UPDATE SET encounter_count = encounter_count + 1",
                (rom_hash, int(monster_id), _now()),
            )
            # ON CONFLICT の UPDATE でも rowcount は 1 になるため、
            # 新規かどうかは挿入前の状態で判断する必要がある。
            if cur.rowcount and self._was_new(rom_hash, int(monster_id)):
                newly.add(int(monster_id))
        self._commit()
        return newly

    def _was_new(self, rom_hash: str, monster_id: int) -> bool:
        row = self._conn.execute(
            "SELECT encounter_count FROM EncounteredMonster"
            " WHERE rom_hash = ? AND monster_id = ?",
            (rom_hash, monster_id),
        ).fetchone()
        return bool(row) and int(row["encounter_count"]) == 1

    # --- VisitedTile（歩いたマス）--------------------------------------

    def mark_visited(self, rom_hash: str, map_id: int, map_ptr: int,
                     x: int, y: int, color: str | None = None,
                     tile: str | None = None) -> bool:
        """そのマスに居たことを記録する。初めてなら True。

        ★同じマスに何度も居るのが普通（1マス歩くのに十数フレームかかる）。
          呼ばれるたびに INSERT すると行が爆発するので**主キーで潰す**。

        ★★ `tile` はネームテーブルのタイルID（2026-08-01 / 課題 #65）★★
          ⚠ `color` は各マスの中心1画素なので、洞窟の床（黒地に赤い点）が
            ほぼ黒になり、**主人公自身の色**まで拾っていた。
            タイルIDならぶれず、スプライトも混ざらない。
          ★`color` は残す（古い記録と、タイルIDを読めない環境のため）。
        """
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO VisitedTile"
            " (rom_hash, map_id, map_ptr, x, y, visits, color, tile,"
            "  first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)"
            " ON CONFLICT(rom_hash, map_id, map_ptr, x, y) DO UPDATE SET"
            "   visits = visits + 1, last_seen = excluded.last_seen,"
            # ★色は**分かったときだけ**上書きする。読めなかった回で
            #   すでに分かっている色を消さない。
            "   color = COALESCE(excluded.color, VisitedTile.color),"
            # ★タイルIDも同じ。読めなかった回で消さない
            "   tile = COALESCE(excluded.tile, VisitedTile.tile)",
            (rom_hash, map_id, map_ptr, x, y, color, tile, now, now),
        )
        self._commit()
        # ★rowcount では判別できない（UPSERT でも 1 になる）。
        #   「1回だけ」かどうかを引き直して見る。
        row = self._conn.execute(
            "SELECT visits FROM VisitedTile WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ? AND x = ? AND y = ?",
            (rom_hash, map_id, map_ptr, x, y),
        ).fetchone()
        del cur
        return bool(row) and int(row["visits"]) == 1

    #: 確度の段階（マップ指示書 §12.3）。★上に行くほど確か
    CONFIDENCE_ORDER = ("provisional", "probable", "confirmed")

    def record_metatile(self, rom_hash: str, map_id: int, map_ptr: int,
                        x: int, y: int, metatile_key: str,
                        source_state: str = "FIELD_IDLE") -> str:
        """そのマスで見た**メタタイル**を記録する（マップ指示書 §12.2）。

        戻り値は記録後の確度。

        ★★ **1回の食い違いで既存の地形を上書きしない。** ★★
          同じマスで違うメタタイルが1回出ただけなら、`conflict` の印を
          付けるだけにする。⚠ 暗転・メニュー・移動途中の1枚で、
          何度も見て確かめた地形を消さないため。

        ⚠ 正式に保存してよいのは `FIELD_IDLE` だけ（指示書 §6.2）。
          それ以外で呼ばれたら**何もしない**。
        """
        if source_state != "FIELD_IDLE":
            return "ignored"
        if not metatile_key:
            return "ignored"

        row = self._conn.execute(
            "SELECT metatile_key, seen_count, confidence FROM VisitedTile"
            " WHERE rom_hash = ? AND map_id = ? AND map_ptr = ?"
            " AND x = ? AND y = ?",
            (rom_hash, map_id, map_ptr, x, y),
        ).fetchone()

        if row is None or row["metatile_key"] is None:
            # ★初めて。1回だけなので provisional
            confidence, count, key = "provisional", 1, metatile_key
        elif row["metatile_key"] == metatile_key:
            # ★同じものをまた見た。回数を増やして確度を上げる
            count = int(row["seen_count"] or 0) + 1
            key = metatile_key
            confidence = "probable" if count == 2 else (
                "confirmed" if count >= 3 else "provisional")
        else:
            # ⚠⚠ **違うものが出た。上書きしない。**
            #   ★印だけ付けて、既存の鍵を残す。回数は増やさない
            #   （増やすと「何度も見た」ように見えてしまう）。
            return self._mark_conflict(rom_hash, map_id, map_ptr, x, y)

        now = _now()
        self._conn.execute(
            "INSERT INTO VisitedTile"
            " (rom_hash, map_id, map_ptr, x, y, visits, metatile_key,"
            "  seen_count, confidence, source_state, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(rom_hash, map_id, map_ptr, x, y) DO UPDATE SET"
            "   metatile_key = excluded.metatile_key,"
            "   seen_count = excluded.seen_count,"
            "   confidence = excluded.confidence,"
            "   source_state = excluded.source_state,"
            "   last_seen = excluded.last_seen",
            (rom_hash, map_id, map_ptr, x, y, key, count, confidence,
             source_state, now, now),
        )
        self._commit()
        return confidence

    def _mark_conflict(self, rom_hash: str, map_id: int, map_ptr: int,
                       x: int, y: int) -> str:
        """★食い違いの印だけ付ける。**中身は変えない**。"""
        self._conn.execute(
            "UPDATE VisitedTile SET confidence = 'conflict', last_seen = ?"
            " WHERE rom_hash = ? AND map_id = ? AND map_ptr = ?"
            " AND x = ? AND y = ?",
            (_now(), rom_hash, map_id, map_ptr, x, y),
        )
        self._commit()
        return "conflict"

    def visited_metatiles(self, rom_hash: str, map_id: int, map_ptr: int):
        """そのマップの `[(x, y, メタタイル鍵, 回数, 確度)]`。

        ⚠ 鍵の無いマス（古い記録）は返さない。★0 と不明を混ぜない。
        """
        rows = self._conn.execute(
            "SELECT x, y, metatile_key, seen_count, confidence"
            " FROM VisitedTile WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ? AND metatile_key IS NOT NULL",
            (rom_hash, map_id, map_ptr),
        ).fetchall()
        return [(int(r["x"]), int(r["y"]), r["metatile_key"],
                 int(r["seen_count"] or 0), r["confidence"]) for r in rows]

    def visited_tiles(self, rom_hash: str, map_id: int,
                      map_ptr: int) -> list[tuple[int, int, int, str | None]]:
        """そのマップで見たマス `[(x, y, 回数, 色)]`。色は無ければ None。"""
        rows = self._conn.execute(
            "SELECT x, y, visits, color FROM VisitedTile"
            " WHERE rom_hash = ? AND map_id = ? AND map_ptr = ?",
            (rom_hash, map_id, map_ptr),
        ).fetchall()
        return [(int(r["x"]), int(r["y"]), int(r["visits"]), r["color"])
                for r in rows]

    def visited_tile_ids(self, rom_hash: str, map_id: int,
                         map_ptr: int) -> dict[tuple[int, int], str]:
        """そのマップの `{(x, y): タイルID}`（2026-08-01 / 課題 #65）。

        ★`visited_tiles` の形を変えずに足す。あちらは 4つ組を返す約束で、
          読む側が `for x, y, n, c in ...` と書いている。
        ⚠ タイルIDが無いマス（古い記録）は**入れない**。
          0 と 不明を混ぜない。
        """
        rows = self._conn.execute(
            "SELECT x, y, tile FROM VisitedTile"
            " WHERE rom_hash = ? AND map_id = ? AND map_ptr = ?"
            "   AND tile IS NOT NULL",
            (rom_hash, map_id, map_ptr),
        ).fetchall()
        return {(int(r["x"]), int(r["y"])): str(r["tile"]) for r in rows}

    def visited_maps(self, rom_hash: str) -> list[tuple[int, int, int]]:
        """歩いたことのあるマップ `[(map_id, map_ptr, マス数)]`。"""
        rows = self._conn.execute(
            "SELECT map_id, map_ptr, COUNT(*) AS n FROM VisitedTile"
            " WHERE rom_hash = ? GROUP BY map_id, map_ptr"
            " ORDER BY map_id, map_ptr",
            (rom_hash,),
        ).fetchall()
        return [(int(r["map_id"]), int(r["map_ptr"]), int(r["n"])) for r in rows]

    def delete_visited(self, rom_hash: str, map_id: int, map_ptr: int) -> int:
        """そのマップの記録を消す。消した行数を返す。

        ⚠⚠ **利用者のデータを消す操作。** 呼び出し側が明示的に頼んだときだけ
          使うこと（`python -m retroux.tools.map_prune`）。
          取り込みや描画の副作用で呼んではいけない。
        """
        cur = self._conn.execute(
            "DELETE FROM VisitedTile WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ?", (rom_hash, map_id, map_ptr))
        self._commit()
        return cur.rowcount

    def delete_visited_outside(self, rom_hash: str, map_id: int, map_ptr: int,
                               width: int, height: int) -> int:
        """マップの外に出てしまった記録を消す。消した行数を返す。"""
        cur = self._conn.execute(
            "DELETE FROM VisitedTile WHERE rom_hash = ? AND map_id = ?"
            " AND map_ptr = ? AND (x >= ? OR y >= ?)",
            (rom_hash, map_id, map_ptr, width, height))
        self._commit()
        return cur.rowcount

    # --- IngestState -------------------------------------------------

    def get_ingest_state(self, source: str) -> tuple[int, str | None]:
        """(次に読む位置, ファイル先頭の署名) を返す。未記録なら (0, None)。"""
        row = self._conn.execute(
            "SELECT offset, head_sig FROM IngestState WHERE source = ?", (source,)
        ).fetchone()
        if not row:
            return 0, None
        return int(row["offset"]), row["head_sig"]

    def set_ingest_state(self, source: str, offset: int,
                         head_sig: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO IngestState(source, offset, head_sig, updated_at)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(source) DO UPDATE SET offset = excluded.offset,"
            " head_sig = excluded.head_sig, updated_at = excluded.updated_at",
            (source, int(offset), head_sig, _now()),
        )
        self._commit()

    # --- BattleLog ---------------------------------------------------

    def insert_battle(
        self,
        rom_hash: str,
        started_at: str,
        ended_at: str | None,
        duration_ms: int | None,
        duration_frames: int | None,
        monster_ids: Iterable[int],
        is_first_encounter: bool,
        is_boss: bool,
        speed_applied: float | None,
        auto_input_used: bool,
        result: str | None = None,
        exp_gained: int | None = None,
        gold_gained: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO BattleLog(rom_hash, started_at, ended_at, duration_ms,"
            " duration_frames, monster_ids, is_first_encounter, is_boss, result,"
            " exp_gained, gold_gained, speed_applied, auto_input_used)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rom_hash, started_at, ended_at, duration_ms, duration_frames,
                json.dumps([int(i) for i in monster_ids]),
                int(is_first_encounter), int(is_boss), result,
                exp_gained, gold_gained, speed_applied, int(auto_input_used),
            ),
        )
        self._commit()
        return int(cur.lastrowid)

    def insert_battle_events(self, battle_id: int, events: list[dict]) -> int:
        """戦闘の出来事をまとめて入れる。

        ★1件ずつコミットしない（Database.bulk と同じ理由）。
          1戦闘で数十件出るので、まとめないと fsync が並ぶ。
        """
        if not events:
            return 0
        now = _now()
        with self.bulk():
            for e in events:
                self._conn.execute(
                    "INSERT INTO BattleEvent(battle_id, turn_no, sequence_no,"
                    " frame_no, kind, actor, target, action_name,"
                    " value_before, value_after, delta, selected_by, reason,"
                    " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        battle_id, e.get("turn", 0), e.get("seq", 0),
                        e.get("frame"), e["kind"], e.get("actor"),
                        e.get("target"), e.get("action_name"),
                        e.get("before"), e.get("after"), e.get("delta"),
                        e.get("selected_by"), e.get("reason"), now,
                    ),
                )
        return len(events)

    def battle_events(self, battle_id: int) -> list:
        return self._conn.execute(
            "SELECT * FROM BattleEvent WHERE battle_id = ?"
            " ORDER BY turn_no, sequence_no, id",
            (battle_id,),
        ).fetchall()

    def battle_count(self, rom_hash: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM BattleLog"
            " WHERE rom_hash = ? AND monster_ids <> '[]'",
            (rom_hash,)
        ).fetchone()
        return int(row["n"])

    def recent_battles(self, rom_hash: str, limit: int = 20) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM BattleLog"
            " WHERE rom_hash = ? AND monster_ids <> '[]'"
            " ORDER BY id DESC LIMIT ?",
            (rom_hash, limit),
        ).fetchall()

    def speedup_summary(self, rom_hash: str) -> dict[str, float | int]:
        """倍速の効果をまとめる。

        ゲーム内フレーム数と実時間の両方を記録してあるため、
        「どれだけ待ち時間を削れたか」を実データで示せる（DEV-7 の狙い）。
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS battles,"
            " SUM(duration_frames) AS frames,"
            " SUM(duration_ms) AS ms,"
            " AVG(speed_applied) AS avg_speed"
            " FROM BattleLog WHERE rom_hash = ? AND monster_ids <> '[]'"
            " AND duration_frames IS NOT NULL",
            (rom_hash,),
        ).fetchone()
        battles = int(row["battles"] or 0)
        frames = int(row["frames"] or 0)
        ms = int(row["ms"] or 0)
        # 等速なら 60fps で何秒かかっていたか
        baseline_ms = int(frames / 60.0 * 1000) if frames else 0
        return {
            "battles": battles,
            "total_frames": frames,
            "actual_ms": ms,
            "baseline_ms": baseline_ms,
            "saved_ms": max(0, baseline_ms - ms),
            "avg_speed": float(row["avg_speed"] or 0.0),
        }
