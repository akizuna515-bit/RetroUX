"""pytest の共通設定。

★これがある理由: `dq2rom` はリポジトリ直下の独立パッケージで、
  `retroux` と違って editable install に入っていない環境でも
  テストが通るようにしたい。
  ルートに conftest.py があると pytest がリポジトリ直下を sys.path へ入れるので、
  `import dq2rom` が通る。

  （`pyproject.toml` の `packages` にも `dq2rom` を足してあるので、
  `uv pip install -e .` をやり直せばこの conftest 抜きでも通る。
  どちらか一方に頼らないための二重化。）
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
