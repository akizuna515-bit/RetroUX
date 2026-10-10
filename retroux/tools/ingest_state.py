"""DQ2 の取り込み位置（IngestState）を見る・旧い形式を直す（RX-0163 / ★開発用）。

```text
python -m retroux.tools.ingest_state status
    いまの DB の行と、主 events（dq2:events:main）がいまの events の続きかどうか
python -m retroux.tools.ingest_state adopt --from <旧い行の source> [--apply]
    旧い形式の行（鍵 = 絶対パス）を論理 ID へ付け替える。★いまの events の続きだと確かめてから
```

★公開の仕様ではない（★開発中に作った schema 1 のデータ・動かした旧い形式の修理用 / 依頼 RX-0163 §7）。
⚠ `--apply` を付けないと何も変えない。⚠ 確かめに通らなければ付け替えない（★二重の記録・混ざりを防ぐ）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core import dq2_paths
from ..core.config import dq2_user_config
from ..core.db.database import Database
from ..core.recorder import MAIN_STREAM, check_ingest_state, position_problem


def _open(db_path: Path | None) -> Database:
    if db_path is None:
        cfg, _ = dq2_user_config.load()
        db_path = Path(cfg.path("db"))
    if not db_path.exists():
        raise SystemExit(f"DB がありません: {db_path}")     # ★無い DB を作らない
    return Database(db_path)


def status(db: Database, events: Path, out=print) -> int:
    for source in db.ingest_sources():
        row = db.get_ingest_row(source)
        out(f"{source}  offset={row['offset']:,}  path={row['path'] or '—'}")
    got = check_ingest_state(db, MAIN_STREAM, events)
    out(f"events: {events}（{events.stat().st_size if events.exists() else 0:,} バイト）")
    if got.problem:
        out(f"⚠ 取り込みを止める: {got.problem}")
        return 2
    out(f"★続きから取り込める（offset {got.offset:,}" + (f" / 旧い行 {got.adopted_from} を付け替える" if got.adopted_from else "") + "）")
    return 0


def adopt(db: Database, events: Path, old: str, *, apply: bool, out=print) -> int:
    if db.get_ingest_row(MAIN_STREAM) is not None:
        out(f"⚠ 既に {MAIN_STREAM} の行があります（付け替えません）")
        return 2
    row = db.get_ingest_row(old)
    if row is None:
        out(f"⚠ {old} の行がありません")
        return 2
    # ★付け替えたと仮定して確かめる（★DB は変えない）
    problem = position_problem(events, int(row["offset"]), row["head_sig"], row["tail_sig"])
    if problem:
        out(f"⚠ 付け替えません: {problem}")
        return 2
    if not apply:
        out(f"付け替えられます（{old} → {MAIN_STREAM} / offset {int(row['offset']):,}）。--apply で行います")
        return 0
    db.rename_ingest_source(old, MAIN_STREAM)
    out(f"付け替えました（{old} → {MAIN_STREAM}）")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DQ2 の取り込み位置を見る・旧い形式を直す（開発用）")
    ap.add_argument("--db", help="DB（既定: DQ2 の設定の paths.db）")
    ap.add_argument("--events", help="events.jsonl（既定: dq2_paths.events()）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    ad = sub.add_parser("adopt")
    ad.add_argument("--from", dest="old", required=True)
    ad.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    events = Path(args.events) if args.events else dq2_paths.events()
    db = _open(Path(args.db) if args.db else None)
    try:
        if args.cmd == "status":
            return status(db, events)
        return adopt(db, events, args.old, apply=args.apply)
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
