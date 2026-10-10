"""展開先が深すぎないかを、起動の前に見る（RX-0166 / RX3-0517 / 2026-10-05）。

⚠⚠ **深い場所へ展開すると、Qt がエラーも出さずに止まります**（2026-10-04 実測）。

```text
展開先の最も長いパス 280 文字（260 超え 15 件 / PySide6/plugins の下）→ QApplication([]) が黙って止まる
同じ中身を短い場所（194 文字）に置く                                 → 動く
```

★timeout も faulthandler も効かない止まり方なので、⚠ **起こしてからでは気づけません**。
→ ★起動スクリプト・移行の入口が、**Qt を起こす前に**ここで見て、理由を出して止めます
  （依頼者 2026-10-05「深い場所に展開しようとしたらチェックエラーにしてOK」）。

## ★測り方

```text
最も長いパス = 展開先の文字数 + 1（区切り）+ 配布物の中で最も長い相対パス
相対パス     = build-info.json の longest_path（★build が焼く / 正本）と、いまの中身を歩いた値の大きい方
```

⚠ 中身だけを歩くと、展開ツールが長すぎるファイルを**黙って飛ばした**とき短く測れてしまう → ★build の値も見る。
⚠ 開発 repo（build-info に longest_path が無い・runtime/ が無い）は、ほぼ 0 になり止めません。

CLI（★起動スクリプト用 / ⚠ 出力は ASCII だけ。PowerShell 5.1 の文字化けを避ける）:

```text
python -m retroux.core.path_depth --root <展開先>
  → OK total=<n> limit=259            終了コード 0
  → TOO_DEEP total=<n> limit=259 root=<展開先の文字数> allowed=<展開先の上限>   終了コード 3
```
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib

#: ★Windows の MAX_PATH は終端を含めて 260 → ★使える文字は 259 まで
LIMIT = 259
#: ★build-info.json の欄（★`scripts/build_runtime.py` が焼く）
INFO_KEY = "longest_path"
#: ★歩いて測るのは配布物の中身だけ（⚠ 利用者の work/ は入れない）
WALK_DIRS = ("runtime", "retroux", "dq2rom", "dq3", "dq3rom", "scripts", "tools")


def longest_relative(root, dirs=WALK_DIRS) -> int:
    """★`root` からの相対パスで、いちばん長い文字数（⚠ 無ければ 0）。"""
    root = pathlib.Path(root)
    best = 0
    for name in dirs:
        top = root / name
        if not top.is_dir():
            continue
        for here, folders, files in os.walk(top):
            for item in list(folders) + list(files):
                rel = os.path.relpath(os.path.join(here, item), root)
                best = max(best, len(rel))
    return best


def built_longest(root) -> int:
    """★build が焼いた値（⚠ 無ければ 0）。"""
    try:
        data = json.loads((pathlib.Path(root) / "build-info.json").read_text(encoding="utf-8"))
        return int(data.get(INFO_KEY) or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def measure(root) -> dict:
    """★いちばん長いパスの見込み（`total`）と、展開先に許される文字数（`allowed`）。"""
    root = pathlib.Path(root)
    rel = max(longest_relative(root), built_longest(root))
    root_len = len(str(root).rstrip("\\/"))
    total = root_len + 1 + rel if rel else root_len
    return {"total": total, "root": root_len, "relative": rel,
            "allowed": LIMIT - 1 - rel if rel else LIMIT, "ok": total <= LIMIT}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="展開先が深すぎないかを見る（★Qt を起こす前に）")
    ap.add_argument("--root", required=True)
    args = ap.parse_args(argv)
    got = measure(args.root)
    if got["ok"]:
        print("OK total=%d limit=%d" % (got["total"], LIMIT))
        return 0
    print("TOO_DEEP total=%d limit=%d root=%d allowed=%d"
          % (got["total"], LIMIT, got["root"], got["allowed"]))
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
