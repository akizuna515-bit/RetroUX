"""`work/events.jsonl` の世代交代（製品版ログ整理 Phase 7 / 指示書 §25）。

## ⚠⚠ なぜ `retroux.log` と同じ作りにできないか

`retroux.log` は Python の `RotatingFileHandler` が面倒を見ています
（10MB × 5 世代）。★あちらは**書き手が1人**（Logger）で、
サイズを見て自分で切り替えられます。

`events.jsonl` は違います:

  ・**書き手は Lua**（`Bridge:emit`）
  ・**読み手は Python**（`Recorder`）で、`IngestState` に
    「どこまで読んだか」を持っている

⚠⚠ したがって、ただ rename すると壊れ方が2つあります:

  1. **Lua が名前の変わった側へ書き続ける**
     → ★`Bridge:emit` を「書くたびに開き直す」形に変えて塞ぎました
        （`bridge.lua` の説明を参照。実測 99us/回・1戦闘で 20ms 未満）
  2. **取り込み位置が古いファイルのものを指したまま残る**
     → ★新しいファイルは空なので、位置が残っていると
        **次に書かれた行を読み飛ばします**（しかも静かに）

## ★ この実装が守ること

  1. **取り込みが済んでいるときだけ**切り替える
     ⚠ 未取り込みの行があるまま切り替えると、その行は DB に入りません
  2. 切り替えたら**必ず取り込み位置を 0 へ戻す**（★同じ処理の中で）
  3. 上限に届いていなければ何もしない（★静かに）
  4. 古い世代は決めた数だけ残し、あふれたものは消す

## ⚠ いつ呼ぶか

★**取り込み役（`Recorder`）を作る前**に一度だけ呼びます。
⚠ 遊んでいる最中に呼ばないこと（1 の条件で弾かれますが、
  そもそも切り替えるべき場面ではありません）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: 既定の上限。⚠ `retroux.log`（10MB）より小さくしています。
#:   ★1行が JSON なので、同じバイト数でも行数が多く、取り込みが重くなります。
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
#: 残す世代の数。★`retroux.log` と揃えています。
DEFAULT_GENERATIONS = 5

#: 世代ファイルの名前。★時刻を入れて、順番が名前で分かるようにします。
_STAMP = "%Y%m%d-%H%M%S"
_ARCHIVE_RE = re.compile(r"^(?P<stem>.+)-(?P<stamp>\d{8}-\d{6})(?P<suffix>\.jsonl)$")


@dataclass
class RotationResult:
    """何が起きたか。★呼び出し側がログに出せる形で返す。"""

    rotated: bool
    reason: str
    archived: Path | None = None
    removed: list[Path] | None = None
    size: int = 0

    def message(self) -> str:
        if not self.rotated:
            return f"イベントの世代交代はしませんでした: {self.reason}"
        removed = len(self.removed or [])
        tail = f" / 古い世代を {removed} 件消しました" if removed else ""
        return (f"イベントを世代交代しました: {self.archived.name if self.archived else '?'}"
                f"（{self.size:,} バイト）{tail}")


def archives(path: Path) -> list[Path]:
    """世代ファイルを新しい順に返す。"""
    got = []
    for candidate in path.parent.glob(f"{path.stem}-*{path.suffix}"):
        m = _ARCHIVE_RE.match(candidate.name)
        if m and m.group("stem") == path.stem:
            got.append(candidate)
    # ★名前に時刻が入っているので、名前の降順＝新しい順
    return sorted(got, reverse=True)


def rotate(
    path: Path | str,
    *,
    ingested_offset: int,
    max_bytes: int = DEFAULT_MAX_BYTES,
    generations: int = DEFAULT_GENERATIONS,
    now: datetime | None = None,
) -> RotationResult:
    """条件を満たせば `events.jsonl` を世代交代させる。

    `ingested_offset` … `IngestState` が持っている「どこまで読んだか」。

    ⚠⚠ **戻り値が `rotated=True` のときは、呼び出し側で必ず
      取り込み位置を 0 へ戻すこと。** ★そこまでやって初めて安全です。
      （`retroux/core/recorder.py` の `rotate_events` がその形にしてあります）
    """
    target = Path(path)
    if not target.exists():
        return RotationResult(False, "ファイルがありません")

    size = target.stat().st_size
    if size < max_bytes:
        return RotationResult(False, f"上限まで達していません（{size:,} バイト）",
                              size=size)

    # ★★ ⚠ ここが要 ★★
    #   取り込みが追いついていないのに切り替えると、
    #   **まだ DB に入っていない行を置き去りにします**。
    if ingested_offset < size:
        behind = size - ingested_offset
        return RotationResult(
            False, f"取り込みが {behind:,} バイト遅れています（★追いつくまで待ちます）",
            size=size)

    stamp = (now or datetime.now(timezone.utc)).strftime(_STAMP)
    archived = target.with_name(f"{target.stem}-{stamp}{target.suffix}")
    if archived.exists():
        # ⚠ 同じ秒に2回来た。★上書きせず、諦める（記録を消さない）
        return RotationResult(False, f"同じ名前の世代が既にあります: {archived.name}",
                              size=size)

    target.rename(archived)
    # ★空のファイルを作り直す。⚠ Lua は書くたびに開き直すので、
    #   ここで作っておかなくても動きますが、**存在するほうが分かりやすい**。
    target.touch()

    # ★あふれた世代を消す（古いものから）
    removed: list[Path] = []
    for old in archives(target)[generations:]:
        try:
            old.unlink()
            removed.append(old)
        except OSError:
            # ⚠ 消せなくても止めない（★次回また試します）
            pass

    return RotationResult(True, "上限に達しました", archived=archived,
                          removed=removed, size=size)
