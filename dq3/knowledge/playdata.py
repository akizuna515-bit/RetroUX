"""DQ3 のプレイデータ（RetroUX が貯めた記録）を数える・退避する・消す・戻す（RX3-0059）。

## ★何がプレイデータか（⚠ ROM / セーブステート / 解析の採取データ / 設定は違う）

```text
seen      見た地図          work/dq3-knowledge/seen.json, seen-v1.json
memos     勇者メモ          work/dq3-knowledge/memos.jsonl, player-knowledge.json（訪れた地点 / 名前）
monsters  モンスター情報    work/dq3-knowledge/enemy-names.json（会った敵）
hearing   聞き込み履歴      work/dq3-knowledge/npc-heard.json, npc-conversations.json + memos.jsonl の npc_talk 行
```

★CLI と GUI はどちらもここを呼ぶ（★同じ初期化ロジックを 2 つ持たない）。

```text
python -m dq3.knowledge.playdata status
python -m dq3.knowledge.playdata backup [--label x]
python -m dq3.knowledge.playdata clear --items hearing[,seen,...] --apply
python -m dq3.knowledge.playdata restore [latest|<name>] --apply
```

## ★退避の形（⚠ 世代管理は作らない）

`work/playdata-archive/dq3-<yyyymmdd-HHMMSS>[-label]/` に該当ファイルをそのまま写す。★消す前に必ず退避する。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import shutil

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
KNOWLEDGE = paths.lazy_work("dq3-knowledge")
VAULT = paths.lazy_work("playdata-archive")
PREFIX = "dq3-"

#: ★項目（key → 表示名, ファイル）。★順番は画面の並び
ITEMS = (
    ("seen", "見た地図", ("seen.json", "seen-v1.json")),
    ("memos", "勇者メモ", ("memos.jsonl", "player-knowledge.json")),
    ("monsters", "モンスター情報", ("enemy-names.json",)),
    ("hearing", "聞き込み履歴", ("npc-heard.json", "npc-conversations.json")),
    ("topics", "攻略の進み具合", ("topic-state.json", "progress.json", "location-book.json")),
)
ITEM_KEYS = tuple(k for k, _, _ in ITEMS)
LABELS = {k: label for k, label, _ in ITEMS}
#: ★聞き込み履歴に含める勇者メモの行（★source）。⚠ 地図・モンスター・ふつうの会話メモは消さない
HEARING_MEMO_SOURCES = ("npc_talk",)
#: ★場所ごとのクリアで消す勇者メモ（RX3-0235 / 指示書 §10-1）。⚠ discovery は残す
PLACE_MEMO_SOURCES = ("npc_talk", "conversation")
MEMOS_FILE = "memos.jsonl"

#: ⚠⚠ 絶対に触らないもの（★検査で見張る）
NEVER_TOUCH = (ROOT / "work" / "rom", ROOT / "tools", ROOT / "input", ROOT / "work" / "runtime" / "dq3-probe",
               ROOT / "work" / "tests" / "evidence", ROOT / "data")


def _count_lines(path: pathlib.Path) -> int:
    try:
        return sum(1 for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
    except OSError:
        return 0


class PlayDataService:
    def __init__(self, knowledge_dir=None, vault=None) -> None:
        self.dir = pathlib.Path(knowledge_dir) if knowledge_dir else KNOWLEDGE
        self.vault = pathlib.Path(vault) if vault else VAULT

    # ------------------------------------------------------------------
    def files_of(self, key: str) -> list[pathlib.Path]:
        for k, _label, names in ITEMS:
            if k == key:
                return [self.dir / n for n in names]
        raise KeyError(key)

    def all_files(self) -> list[pathlib.Path]:
        seen: list[pathlib.Path] = []
        for k in ITEM_KEYS:
            for p in self.files_of(k):
                if p not in seen:
                    seen.append(p)
        return seen

    def status(self) -> dict:
        """★何があるか（★何も変えない）。"""
        out = {}
        for key, label, names in ITEMS:
            rows = []
            for n in names:
                p = self.dir / n
                rows.append({"name": n, "exists": p.exists(), "size": p.stat().st_size if p.exists() else 0,
                             "lines": _count_lines(p) if p.suffix == ".jsonl" and p.exists() else None})
            out[key] = {"label": label, "files": rows}
        out["hearing"]["heard_npcs"] = self.heard_count()
        out["hearing"]["memo_lines"] = self._memo_lines(HEARING_MEMO_SOURCES)
        out["latest_backup"] = self.latest_backup()
        return out

    def heard_count(self) -> int:
        p = self.dir / "npc-heard.json"
        if not p.exists():
            return 0
        try:
            body = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return 0
        return sum(len(v) for v in body.values() if isinstance(v, dict))

    def _memo_lines(self, sources) -> int:
        p = self.dir / MEMOS_FILE
        if not p.exists():
            return 0
        n = 0
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                if json.loads(ln).get("source") in sources:
                    n += 1
            except ValueError:
                continue
        return n

    # ------------------------------------------------------------------
    def backup(self, label: str | None = None) -> pathlib.Path:
        """★あるファイルを全部写す（⚠ 消さない）。"""
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        name = PREFIX + stamp + ("-" + label if label else "")
        target = self.vault / name
        target.mkdir(parents=True, exist_ok=True)
        copied = []
        for p in self.all_files():
            if p.exists():
                shutil.copy2(p, target / p.name)
                copied.append(p.name)
        (target / "manifest.json").write_text(json.dumps({"at": stamp, "label": label, "files": copied,
                                                          "source": str(self.dir)}, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
        return target

    def backups(self) -> list[pathlib.Path]:
        if not self.vault.exists():
            return []
        return sorted(p for p in self.vault.iterdir() if p.is_dir() and p.name.startswith(PREFIX))

    def latest_backup(self) -> str | None:
        got = self.backups()
        return got[-1].name if got else None

    def restore(self, name: str = "latest") -> dict:
        """★退避を書き戻す（⚠ いまの記録は上書き。★その前にいまの状態も退避する）。"""
        if name == "latest":
            if not self.backups():
                raise FileNotFoundError("⚠ 退避がまだありません")
            source = self.backups()[-1]
        else:
            source = self.vault / name
        if not source.is_dir():
            raise FileNotFoundError("⚠ そんな退避はありません: %s" % name)
        safety = self.backup("before-restore")
        restored, removed = [], []
        for p in self.all_files():
            src = source / p.name
            if src.exists():
                self.dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, p)
                restored.append(p.name)
            elif p.exists():
                # ★退避に無いファイルは「退避の時点で無かった」→ 消して揃える
                p.unlink()
                removed.append(p.name)
        return {"source": source.name, "restored": restored, "removed": removed, "safety": safety.name}

    # ------------------------------------------------------------------
    def clear(self, items, *, backup: bool = True) -> dict:
        """★選んだ項目だけ消す（★消す前に退避）。⚠ 選んでいない項目のファイルは触らない。"""
        items = [k for k in ITEM_KEYS if k in set(items)]
        if not items:
            return {"items": [], "removed": [], "backup": None}
        bak = self.backup("before-clear") if backup else None
        removed = []
        for key in items:
            if key == "hearing":
                removed += self._clear_hearing()
                continue
            for p in self.files_of(key):
                if p.exists():
                    p.unlink()
                    removed.append(p.name)
        return {"items": items, "removed": removed, "backup": bak.name if bak else None}

    # ------------------------------------------------------------------
    # ★場所ごとの会話記録クリア（RX3-0235 / 依頼者の指示書 §8〜§17）
    # ------------------------------------------------------------------
    def places(self, location_of_map=None) -> list[dict]:
        """★会話の記録がある場所（★場所ごとのクリアの選択肢）。`[{location_id, memos, heard, conversations}]`。

        ★場所は location_id（★`location_of_map(map_id)` で map → 場所。無ければ `L<map_id>`）。⚠ 何も変えない。
        """
        loc_of = location_of_map or (lambda m: "L%d" % m)
        rows: dict = {}

        def add(loc, key, n=1):
            if loc:
                got = rows.setdefault(loc, {"location_id": loc, "memos": 0, "heard": 0, "conversations": 0})
                got[key] += n

        memos = self.dir / MEMOS_FILE
        if memos.exists():
            for ln in memos.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("source") in PLACE_MEMO_SOURCES:
                    loc = row.get("location_id")
                    if loc is None and isinstance(row.get("map_id"), int):
                        loc = loc_of(row["map_id"])
                    add(loc, "memos")
        for m, npcs in self._json("npc-heard.json").items():
            if str(m).isdigit() and isinstance(npcs, dict):
                add(loc_of(int(m)), "heard", len(npcs))
        for key in self._json("npc-conversations.json"):
            head = str(key).split("/")[0]
            if head.isdigit():
                add(loc_of(int(head)), "conversations")
        from dq3.knowledge.locations import sort_key

        # ★数の順（RX3-0438 / ⚠ 文字列の順だと L10 が L1 の直後に来る）
        return sorted(rows.values(), key=lambda r: sort_key(r["location_id"]))

    def clear_location(self, location_id: str, map_ids=None, *, backup: bool = True) -> dict:
        """★その場所の会話記録だけを消す（★勇者メモの会話・会話の記録・聞いた人の台帳をセットで / 指示書 §10）。

        ★残す: discovery のメモ・LocationBook（memo_done）・Topic / Fact・地名（指示書 §11 / ⚠ ファイルごと触らない）。
        ★場所は location_id（⚠ `map_ids` を渡さなければ `L<map_id>` から / 指示書 §9）。★消す前に全体を退避（§16）。
        """
        maps = [int(m) for m in (map_ids if map_ids is not None else default_maps(location_id))]
        bak = self.backup("before-clear-place-%s" % location_id) if backup else None
        from dq3.knowledge.memos import MemoStore

        memos = MemoStore(self.dir / MEMOS_FILE).remove_conversations(location_id, maps)
        conversations = self._drop_json("npc-conversations.json",
                                        lambda k: str(k).split("/")[0] in {str(m) for m in maps})
        heard = self._drop_json("npc-heard.json", lambda k: str(k) in {str(m) for m in maps},
                                count=lambda v: len(v) if isinstance(v, dict) else 1)
        return {"location_id": location_id, "map_ids": maps, "memos": memos,
                "conversations": conversations, "heard": heard, "backup": bak.name if bak else None}

    def _json(self, name: str) -> dict:
        p = self.dir / name
        try:
            got = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except ValueError:
            return {}
        return got if isinstance(got, dict) else {}

    def _drop_json(self, name: str, drop, *, count=None) -> int:
        """★JSON の鍵を消して書き戻す（★書き方は HeardLedger.save と同じ / 改行コードは元のまま）。戻り値: 消した数。"""
        p = self.dir / name
        if not p.exists():
            return 0
        body = self._json(name)
        gone = [k for k in body if drop(k)]
        if not gone:
            return 0
        removed = sum((count(body[k]) if count else 1) for k in gone)
        for k in gone:
            del body[k]
        eol = "\r\n" if b"\r\n" in p.read_bytes() else "\n"
        text = json.dumps(body, ensure_ascii=False, indent=1) + "\n"
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(text.replace("\n", eol).encode("utf-8"))
        os.replace(tmp, p)
        return removed

    def rebuild_hearing_memos(self) -> dict:
        """★聞き込みの記録（会話）から、⚠ 消えた勇者メモを作り直す（RX3-0098）。

        ## ⚠⚠ なぜ要るか

          ★「勇者メモ」だけを初期化すると、⚠ `heard` は残ります。
          → 聞き込みは「もう聞いた」と判定して**走りません**
            （`town_service.unheard_reachable_npcs`）。
          ⚠⚠ つまり **1 人ずつ話し直す以外に戻す道がありません**（★本末転倒）。
          → ★本文は `npc-conversations.json` に**残っている**ので、そこから起こします。

        ⚠ 足すのは `npc_talk` の行だけです。★ふつうの会話メモ・地図のメモは触りません。
        ⚠ 同じ本文が同じ map に既にあれば足しません（★何度押しても増えない）。
        """
        from dq3.knowledge import memos as _memos
        from dq3.knowledge import npc_heard as _heard
        from dq3.knowledge.town_service import TownService

        conv_path = self.dir / "npc-conversations.json"
        if not conv_path.exists():
            return {"added": 0, "skipped": 0, "reason": "会話の記録がありません"}
        ledger = _heard.HeardLedger(self.dir)
        store = _memos.MemoStore(self.dir / MEMOS_FILE)
        have = {(m.map_id, m.text) for m in store}
        #: ★話者の字を除いた本文（RX3-0236）。⚠ 「兵「…」」があるのに「？「…」」を別物として足していた（重複「？」30 件）
        bodies = {(m.map_id, _memos.talk_body(m.text)) for m in store}
        rows = []
        for key, items in sorted((ledger.conversations or {}).items()):
            try:
                map_id, npc_id = (int(x) for x in key.split("/"))
            except ValueError:
                continue
            for it in items:
                rows.append((it.get("first_heard_at") or "", map_id, npc_id, it.get("text") or ""))
        rows.sort()                                          # ★聞いた順に並べる
        added = skipped = 0
        for _at, map_id, npc_id, text in rows:
            if not text:
                continue
            label = _npc_label(map_id, npc_id)
            line = TownService.memo_text(label, text)
            if (map_id, line) in have:
                skipped += 1
                continue
            speaker = None if label == "？" else label
            if (map_id, _memos.talk_body(line)) in bodies:
                # ★同じ本文がもうある（⚠ 話者の字だけ違う行を足さない）。★話者が分かれば「？」の行に埋める
                if speaker is not None:
                    store.fill_speaker(line, location_id="L%d" % map_id, speaker=speaker, npc_id=npc_id)
                skipped += 1
                continue
            # ★話者も残す（RX3-0118。⚠ `？` は「分からない」なので記録しない）
            store.add(line, source="npc_talk", map_id=map_id, npc_id=npc_id,
                      location_id="L%d" % map_id, speaker=speaker)
            have.add((map_id, line))
            bodies.add((map_id, _memos.talk_body(line)))
            added += 1
        return {"added": added, "skipped": skipped}

    def _clear_hearing(self) -> list[str]:
        """★聞き込み履歴: heard / conversations を消し、勇者メモの npc_talk 行だけ抜く（⚠ 他の行は残す）。"""
        removed = []
        for p in self.files_of("hearing"):
            if p.exists():
                p.unlink()
                removed.append(p.name)
        memos = self.dir / MEMOS_FILE
        if memos.exists():
            raw = memos.read_bytes()
            eol = b"\r\n" if b"\r\n" in raw else b"\n"
            keep, dropped = [], 0
            for ln in raw.decode("utf-8", errors="replace").splitlines():
                if not ln.strip():
                    continue
                try:
                    if json.loads(ln).get("source") in HEARING_MEMO_SOURCES:
                        dropped += 1
                        continue
                except ValueError:
                    pass
                keep.append(ln)
            if dropped:
                text_eol = eol.decode("ascii")
                memos.write_bytes((text_eol.join(keep) + (text_eol if keep else "")).encode("utf-8"))
                removed.append("%s の npc_talk %d 行" % (MEMOS_FILE, dropped))
        return removed


def _npc_label(map_id: int, npc_id: int) -> str:
    """★見た目の字（⚠ ROM が無ければ「？」）。"""
    try:
        from dq3.knowledge import npc_master
        from dq3.knowledge.town_service import TownService

        for time_byte in (None, 0x90):
            master = npc_master.master_for(map_id, time_byte)
            npc = next((n for n in master.get("npcs", []) if n["npc_id"] == npc_id), None)
            if npc is not None:
                return TownService().appearance_label(npc["appearance_id"])
    except Exception:                                        # noqa: BLE001 ★名前が出ないだけ
        pass
    return "？"


def default_maps(location_id: str) -> list[int]:
    """★`L<map_id>` → `[map_id]`（⚠ いまは 1 map = 1 場所 / 別の形なら空）。"""
    text = str(location_id or "")
    return [int(text[1:])] if text[:1] == "L" and text[1:].isdigit() else []


def describe_place(name: str) -> str:
    """★場所ごとのクリアの確認の文（★指示書 §17・§16）。"""
    return ("%sの会話記録をクリアします。\n\n"
            "削除されるもの:\n・勇者メモの会話\n・聞き込み履歴\n・保存済み会話\n\n"
            "残るもの:\n・場所を発見した記録\n・地名\n・攻略の進行状況\n\n"
            "クリア後は、この場所で再び「聞き込み」ができます。\n\n"
            "⚠ クリアの前に全体を退避します。★復元すると、クリア後に追加した他の場所の新しい記録も"
            "巻き戻る可能性があります。" % name)


def describe(items) -> str:
    """★確認ダイアログの文（★消すもの / 消さないもの）。"""
    chosen = [LABELS[k] for k in ITEM_KEYS if k in set(items)]
    rest = [LABELS[k] for k in ITEM_KEYS if k not in set(items)]
    lines = ["次の記録を初期化します。", "", "  " + " / ".join(chosen) if chosen else "  （何も選ばれていません）", ""]
    if "hearing" in items:
        lines.append("聞き込み履歴: 聞いた会話（heard / conversations）と、勇者メモの聞き込みの行が消えます。")
    # ⚠⚠ 2026-09-07（RX3-0096）: 入れ物が 2 つあり、★別々に消せます。
    #   ⚠ 勇者メモだけ消すと、聞いた会話は残ったままなので **食い違って見えます**。
    if "memos" in items and "hearing" not in items:
        lines.append("⚠ 勇者メモだけを消すと、聞いた会話は残ります。"
                     "→ [メモ詳細] には出たまま、[図] の勇者メモからは消えます。")
        lines.append("⚠ 聞き込みは「もう聞いた」と判定して走りません。"
                     "→ 戻すときは「勇者メモを聞き込みの記録から作り直す」を使ってください。")
    lines.append("変わらないもの: " + (" / ".join(rest) if rest else "（なし）") + " / ROM / セーブステート / 解析データ / 設定")
    lines.append("")
    lines.append("★消す前に退避します（work/playdata-archive/）。")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="DQ3 のプレイデータを数える / 退避 / 消す / 戻す")
    ap.add_argument("command", choices=("status", "backup", "clear", "restore", "list"))
    ap.add_argument("name", nargs="?", default="latest")
    ap.add_argument("--items", default="", help="clear: seen,memos,monsters,hearing")
    ap.add_argument("--label", default=None)
    ap.add_argument("--apply", action="store_true", help="⚠ clear / restore は付けないと数えるだけ")
    args = ap.parse_args(argv)
    svc = PlayDataService()
    if args.command == "status":
        print(json.dumps(svc.status(), ensure_ascii=False, indent=1))
        return 0
    if args.command == "list":
        for p in svc.backups():
            print(p.name)
        return 0
    if args.command == "backup":
        print("★退避:", svc.backup(args.label))
        return 0
    items = [s for s in args.items.split(",") if s]
    if args.command == "clear":
        print(describe(items))
        if not args.apply:
            print("\n⚠ 数えただけです。消すには --apply")
            return 0
        print(json.dumps(svc.clear(items), ensure_ascii=False, indent=1))
        return 0
    if args.command == "restore":
        if not args.apply:
            print("★戻す元:", args.name, "/ ⚠ --apply を付けると上書きします")
            return 0
        print(json.dumps(svc.restore(args.name), ensure_ascii=False, indent=1))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
