"""run ごとの証跡をまとめる（RX3-0031 / 2026-08-31）。

## ★何のためか

    テストが通ったかを見るだけでなく、
    ⚠ **あとから Note / X / 動画の素材として使える形**で残す（PoC② §10）。

## ★置き場

```text
work/evidence/20260831_walk_town_001/
    metadata.json     ★run のまとめ（⚠ ここを読めば何をしたか分かる）
    run.jsonl         ★Lua が 1 歩ずつ書いた生の記録（⚠ 加工前）
    test.log          ★人が読むための記録
    start.png / end.png / error.png
    state_before.fc6  ⚠ セーブも残す（★後から何度でも描き直せる）
```

## ⚠⚠ 役割を分ける

```text
Lua（実機の中）   ★起きたことを 1 行ずつ `run.jsonl` へ**追記する**だけ
Python（ここ）    ★それを読んで `metadata.json` にまとめる
```

⚠ Lua にまとめさせない。★実機の中で落ちたら、まとめごと失われます。
**追記だけなら、途中で落ちてもそこまでは残ります。**
（`RX3-0016` のメモが追記型なのと同じ考え。）

## ⚠ `stop_reason` の語は増やさない

★`auto_v0.lua` / `mantan_v0.lua` の `stop()` が使う語をそのまま使います
（`battle` / `screen_frozen` / `cursor_not_found` / `ppu_unavailable` …）。
⚠ ここで新しい語を作ると、2 つの語彙ができてしまいます。
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import pathlib
import re

from .. import paths

ROOT = pathlib.Path(__file__).resolve().parents[2]
#: ★置き場（⚠ `work/` は Git 管理外。★大きな mp4 を置いても repo が太らない）
EVIDENCE_DIR = paths.lazy_work("evidence")

#: ⚠ run_id に使ってよい字（★folder 名になるので厳しくする）
#:
#:   ```text
#:   20260901_town_run_004                      ★昔の形（⚠ 続き番号）
#:   20260902_091530_field-autobattle-regression ★指示書 A-3 の形（時刻 + 目的）
#:   ```
RUN_ID = re.compile(r"^[0-9]{8}_(?:[a-z0-9_]+_[0-9]{3}|[0-9]{6}_[a-z0-9-]+)$")

#: ⚠ 目的の英字名に使ってよい字（★folder 名になる）
SLUG = re.compile(r"[^a-z0-9-]+")

#: ★結果の語（⚠ 増やさない）
PASS, FAIL, ERROR = "PASS", "FAIL", "ERROR"


class EvidenceError(ValueError):
    """⚠ 証跡を作れなかった。★黙って捨てない。"""


def _now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def slug(text: str) -> str:
    """★`"Field AutoBattle Regression"` → `field-autobattle-regression`。"""
    got = SLUG.sub("-", str(text).lower()).strip("-")
    return got or "run"


def new_run_id_at(feature: str, *, when=None) -> str:
    """★★ 指示書 A-3 の形: `20260902_091530_field-autobattle-regression`。

    ⚠ 時刻が入るので**続き番号が要りません**（★同じ秒に 2 回始めたら衝突する。
      呼ぶ側が folder の有無を見る）。
    """
    when = when or datetime.datetime.now()
    got = "%s_%s" % (when.strftime("%Y%m%d_%H%M%S"), slug(feature))
    if not RUN_ID.match(got):
        raise EvidenceError("⚠ run_id の形が違います: %r" % (got,))
    return got


def new_run_id(feature: str, *, when=None, seq: int = 1) -> str:
    """★`20260831_walk_town_001` の形。

    ⚠ `feature` は小文字と `_` だけ（★folder 名になる）。
    """
    safe = re.sub(r"[^a-z0-9_]", "_", feature.lower()).strip("_")
    if not safe:
        raise EvidenceError("⚠ feature が空です")
    day = (when or datetime.date.today()).strftime("%Y%m%d")
    return "%s_%s_%03d" % (day, safe, seq)


@dataclasses.dataclass
class Run:
    """★1 回のテスト。⚠ `finish()` を呼ぶまで `metadata.json` は書きません。"""

    run_id: str
    feature: str
    save_slot: int
    root: pathlib.Path
    started_at: str
    #: ⚠ 追加で残したいもの（★呼ぶ側が自由に足す）
    extra: dict = dataclasses.field(default_factory=dict)
    #: ★人が読む目的（⚠ 指示書 A-3。★JSON では ASCII の run_id が正）
    purpose: str | None = None

    def video_name(self, suffix: str = ".mkv") -> str:
        """★動画の名前: `20260902_091530_フィールド自動戦闘回帰試験.mkv`。

        ⚠ 目的が無ければ `run.mkv`（★昔の形のまま）。
        """
        if not self.purpose:
            return "run" + suffix
        stamp = self.run_id[:15] if RUN_ID.match(self.run_id) and             self.run_id[8] == "_" and self.run_id[9:15].isdigit() else self.run_id
        return "%s_%s%s" % (stamp, self.purpose, suffix)

    # --- ★書き足す ---------------------------------------------------

    @property
    def log_path(self) -> pathlib.Path:
        return self.root / "test.log"

    @property
    def steps_path(self) -> pathlib.Path:
        """★Lua が 1 歩ずつ書く先（⚠ 追記のみ）。"""
        return self.root / "run.jsonl"

    def say(self, line: str) -> None:
        """★人が読む記録へ 1 行。"""
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (_now(), line))

    def steps(self) -> list[dict]:
        """★Lua が書いた 1 歩ずつを読む。

        ⚠⚠ **壊れた行があっても、残りは読みます**（★途中で落ちた記録も使う）。

        ## ⚠ 「歩」でない行は数えません（2026-09-01 / 実機で分かった）

          ★実機の 1 回目で、Lua が `{"event":"finish", ...}` を同じ
          ファイルへ書いていました。⚠ そのため

          ```text
          歩数        40 → **41**（★まとめの行まで数えた）
          終了位置    ⚠⚠ **null**（★最後の行に x/y が無い）
          ```

          ⚠ Lua 側は直しましたが、★**読む側も強くしておきます**
          （⚠ 別の書き手が現れても、静かに数字が狂わないように）。
        """
        # ⚠ 数え直す（★2 度呼ばれても二重に数えない）
        self.failed_lines = 0
        got = []
        if not self.steps_path.exists():
            return got
        with io_open(self.steps_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    self.failed_lines += 1
                    continue
                # ⚠ 「歩」の行だけ（★`step` を持たない行は数えない）
                if isinstance(row, dict) and "step" in row:
                    got.append(row)
        return got

    failed_lines: int = 0

    # --- ★まとめる -----------------------------------------------------

    def finish(self, *, result: str, stop_reason: str | None = None,
               media: dict | None = None, video_meta: dict | None = None,
               checks: dict | None = None) -> pathlib.Path:
        """★`metadata.json` を書いて、その道を返す。

        @param video_meta ★ffprobe で見た動画の事実（`video.describe()`）
        @param checks     ★ASSERT の結果（`verdict.py`）。⚠ 「動画がある」だけで
                          PASS にしないための置き場
        """
        if result not in (PASS, FAIL, ERROR):
            raise EvidenceError("⚠ result が知らない語です: %r" % (result,))
        steps = self.steps()
        ok = sum(1 for s in steps if s.get("ok"))
        seen = {(s.get("map_id"), s.get("x"), s.get("y"))
                for s in steps if s.get("ok")}
        first = steps[0] if steps else {}
        last = steps[-1] if steps else {}
        meta = {
            "run_id": self.run_id,
            "feature": self.feature,
            "purpose": self.purpose,
            "started_at": self.started_at,
            "ended_at": _now(),
            "save_slot": self.save_slot,
            "start": {k: first.get(k) for k in ("map_id", "x", "y")},
            "end": {k: last.get(k) for k in ("map_id", "x", "y")},
            "steps_attempted": len(steps),
            "steps_success": ok,
            "unique_tiles": len(seen),
            "stop_reason": stop_reason,
            "result": result,
            "evidence": {
                "log": _rel(self.log_path, self.root),
                "steps": _rel(self.steps_path, self.root),
                "start_png": _rel(self.root / "start.png", self.root),
                "end_png": _rel(self.root / "end.png", self.root),
                "error_png": _rel(self.root / "error.png", self.root),
                "video": _video(self.root, self.video_name() if self.purpose else None),
                "video_frames": sorted(p.name for p in self.root.glob("video_*.png")),
                "obs_frame_png": _rel(self.root / "obs_frame.png", self.root),
                "state_before": _rel(self.root / "state_before.json", self.root),
                "state_after": _rel(self.root / "state_after.json", self.root),
                "state_diff": _rel(self.root / "state_diff.json", self.root),
                "savestate": _rel(self.root / ("state_before.fc%d"
                                               % self.save_slot), self.root),
            },
            "video_meta": video_meta,
            "checks": checks,
            "media": media or {"good_for_note": False, "good_for_x": False,
                               "good_for_short_video": False},
        }
        # ⚠ 読めなかった行を隠さない（★「0 件」と「読めなかった」を区別する）
        if self.failed_lines:
            meta["broken_lines"] = self.failed_lines
        meta.update(self.extra)
        path = self.root / "metadata.json"
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return path


def io_open(path):
    return path.open("r", encoding="utf-8", errors="replace")


def _rel(path: pathlib.Path, root: pathlib.Path):
    """★あるものだけ名前を返す（⚠ 無いものは `null`）。"""
    return path.name if path.exists() else None


#: ★動画の名前（⚠ **拡張子は録画する側の設定で変わります**）
#:
#:   ⚠⚠ 2026-09-02 実測: 依頼者の OBS は `mkv` でした。
#:     ★`run.mp4` だけを探していたので、**動画があるのに `null`** と
#:     書くところでした（⚠ 「無い」と「見つけられない」は違います）。
VIDEO_NAMES = ("run.mp4", "run.mkv", "run.mov", "run.webm", "run.avi")


def _video(root: pathlib.Path, preferred: str | None = None):
    """★この run の動画の名前（⚠ 無ければ `None`）。

    ★目的つきの名前（`20260902_091530_…mkv`）があればそれ。⚠ 無ければ `run.*`。
    """
    if preferred and (root / preferred).exists():
        return preferred
    for name in VIDEO_NAMES:
        if (root / name).exists():
            return name
    # ⚠ 拡張子が違う目的つきの名前（★mp4 で録った日など）
    for p in sorted(root.glob("%s_*.*" % root.name[:15])):
        if p.suffix.lower() in (".mkv", ".mp4", ".mov", ".webm", ".avi"):
            return p.name
    return None


def start(feature: str, *, save_slot: int, base: pathlib.Path | None = None,
          seq: int = 1, extra: dict | None = None) -> Run:
    """★run を始める。⚠ folder を作り、`Run` を返す。"""
    from . import slots

    if not slots.can_read(save_slot):
        raise EvidenceError("⚠ スロットが範囲外: %r" % (save_slot,))
    run_id = new_run_id(feature, seq=seq)
    if not RUN_ID.match(run_id):
        raise EvidenceError("⚠ run_id の形が違います: %r" % (run_id,))
    root = (base or EVIDENCE_DIR) / run_id
    root.mkdir(parents=True, exist_ok=True)
    run = Run(run_id=run_id, feature=feature, save_slot=save_slot,
              root=root, started_at=_now(), extra=dict(extra or {}))
    run.say("=== %s start (slot %d) ===" % (run_id, save_slot))
    return run
