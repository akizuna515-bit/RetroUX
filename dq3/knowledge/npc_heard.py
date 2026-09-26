"""会話した事実（heard）の台帳（RX3-0056）。

## ★ROM の Master と分ける

```text
Master（ROM）   その NPC が何を話し得るか（talk_id / role）        → 内部だけ。UI には出さない
heard（ここ）   勇者が**実際に**話した NPC と、画面に出た本文         → 勇者メモに出せるのはこれだけ
```

## ★形

```text
work/dq3-knowledge/npc-heard.json          {"<map_id>": {"<npc_id>": {"talk_ids": [...], "time": [...], "first": f, "last": f, "count": n}}}
work/dq3-knowledge/npc-conversations.json  {"<map_id>/<npc_id>": [{"talk_id", "text_hash", "text", "first_heard_at", "last_heard_at", "count"}]}
```

★同じ NPC に**複数の text_hash**（物語 / 昼夜 / 選択肢で変わる）。⚠ ROM の本文を先読みして入れない。
★昼夜は `time`（day / night）を並べて持つだけで、別人にも同一人物にもしない（★同じ ROM 記録 = 同じ npc_id）。
⚠ UI へはまだ配線していない（★別 WI）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from .. import paths

DEFAULT_DIR = paths.lazy_work("dq3-knowledge")


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


class HeardLedger:
    def __init__(self, dir_path=None):
        self.dir = pathlib.Path(dir_path) if dir_path else DEFAULT_DIR
        self.heard_path = self.dir / "npc-heard.json"
        self.conv_path = self.dir / "npc-conversations.json"
        self.heard: dict = self._load(self.heard_path)
        self.conversations: dict = self._load(self.conv_path)

    @staticmethod
    def _load(path: pathlib.Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return {}

    def reload(self) -> None:
        """★ファイルから読み直す（★管理画面が消したり戻したりした後に、古い中身で判断しないため / RX3-0059）。"""
        self.heard = self._load(self.heard_path)
        self.conversations = self._load(self.conv_path)

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.heard_path.write_text(json.dumps(self.heard, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        self.conv_path.write_text(json.dumps(self.conversations, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    def record(self, map_id: int, npc_id: int, talk_id: int, *, time: str = "day", at: int | str | None = None,
               text: str | None = None, phase: str | None = None) -> dict:
        """★会話開始（+ 本文が取れていれば本文）を記す。

        `phase`: 物語の段階（★眠りの村の asleep / awake / RX3-0210）。⚠ 無ければ段階を残さない。
        """
        m = self.heard.setdefault(str(map_id), {})
        e = m.setdefault(str(npc_id), {"talk_ids": [], "time": [], "first": at, "last": at, "count": 0})
        if talk_id not in e["talk_ids"]:
            e["talk_ids"].append(talk_id)
        if time not in e["time"]:
            e["time"].append(time)
        e["last"] = at
        e["count"] += 1
        if e.get("first") is None:
            e["first"] = at
        if phase and phase not in e.setdefault("phase", []):
            e["phase"].append(phase)
        if text:
            self._record_text(map_id, npc_id, talk_id, text, at)
        return e

    def _record_text(self, map_id: int, npc_id: int, talk_id: int, text: str, at) -> dict:
        key = "%d/%d" % (map_id, npc_id)
        rows = self.conversations.setdefault(key, [])
        h = text_hash(text)
        for r in rows:
            if r["text_hash"] == h:
                r["last_heard_at"] = at
                r["count"] += 1
                return r
        row = {"npc_id": npc_id, "talk_id": talk_id, "text_hash": h, "text": text, "first_heard_at": at,
               "last_heard_at": at, "count": 1}
        rows.append(row)
        return row

    # ------------------------------------------------------------------
    def is_heard(self, map_id: int, npc_id: int, phase: str | None = None, talk_id: int | None = None) -> bool:
        """★話したことがあるか。

        ★★ `phase = "awake"`（眠りの村が目覚めた後 / RX3-0210）: ⚠ **起きている時に**話したときだけ済み。
          ⚠ 眠っている間は全員「ぐうぐう」なので、その記録では済みにしない（★目覚めた後の台詞を聞きに行く）。
          ★段階の無い昔の記録: 本文が眠りの台詞だけなら、眠っている間とみなす（⚠ 本文が無ければ済みのまま）。
        ★★ `talk_id`（差し替え先の表の人 / RX3-0231）: ⚠ **その台詞で**話したときだけ済み。
          ★イベントで台詞が替わった人は、もう一度聞きに行く（⚠ 記録に台詞の番号が無ければ済みのまま）。
        """
        e = self.heard.get(str(map_id), {}).get(str(npc_id))
        if e is None:
            return False
        if talk_id is not None and e.get("talk_ids") and talk_id not in e["talk_ids"]:
            return False
        if phase != "awake":
            return True
        got = e.get("phase") or []
        if "awake" in got:
            return True
        if got:
            return False                         # ★眠っている間だけ話した
        from .story import is_sleep_text

        texts = [r.get("text") or "" for r in self.texts(map_id, npc_id)]
        return not (texts and all(is_sleep_text(t) for t in texts))

    def texts(self, map_id: int, npc_id: int) -> list[dict]:
        return list(self.conversations.get("%d/%d" % (map_id, npc_id), []))

    def get_heard_npcs(self, map_id: int, master_map: dict | None = None, labels: dict | None = None) -> list[dict]:
        """★UI 向け（指示書 §10）: heard = true の NPC だけ。⚠ Master の role / 見た目は添えるだけ。"""
        from dq3.testing import npc_sprites as NS
        from dq3.testing import talk_script as TS

        by_id = {n["npc_id"]: n for n in (master_map or {}).get("npcs", [])}
        out = []
        for npc_id_s, e in sorted(self.heard.get(str(map_id), {}).items(), key=lambda kv: int(kv[0])):
            npc_id = int(npc_id_s)
            m = by_id.get(npc_id)
            texts = self.texts(map_id, npc_id)
            role = TS.classify(m["talk_id"])["role"] if m else None
            out.append({"npc_id": npc_id, "talk_ids": e["talk_ids"],
                        "appearance_id": m["appearance_id"] if m else None,
                        "appearance_label": NS.label_for(m["appearance_id"], labels) if m else NS.UNDEFINED,
                        "role": role, "text": texts[-1]["text"] if texts else None, "texts": texts,
                        "heard_count": e["count"], "time": e["time"]})
        return out

    def get_unheard_npcs(self, map_id: int, master_map: dict, slots: list[dict] | None = None,
                         reachable=None) -> list[dict]:
        """★「ききこみ」用（指示書 §12）: まだ話していない NPC。★現在位置は RAM（slots）があればそれを優先。

        ⚠ 製品の聞き込みはここを通らない（★`town_service.unheard_reachable_npcs`）。⚠ 話しかけない相手
        （王様 / `town_service.hearing_target` / RX3-0194）も外さないので、聞き込みの候補に使わないこと。
        """
        out = []
        for i, n in enumerate(master_map.get("npcs", [])):
            if self.is_heard(map_id, n["npc_id"]):
                continue
            s = slots[i] if slots is not None and i < len(slots) else None
            x, y = (s["x"], s["y"]) if s else (n["initial_x"], n["initial_y"])
            out.append({"npc_id": n["npc_id"], "x": x, "y": y, "position_source": "ram" if s else "rom",
                        "movement": n["movement"], "appearance_id": n["appearance_id"], "talk_id": n["talk_id"],
                        "reachable": None if reachable is None else bool(reachable(x, y))})
        return out

    def counts(self, map_id: int, master_map: dict) -> dict:
        total = len(master_map.get("npcs", []))
        heard = sum(1 for n in master_map.get("npcs", []) if self.is_heard(map_id, n["npc_id"]))
        return {"npc_total": total, "npc_heard": heard}
