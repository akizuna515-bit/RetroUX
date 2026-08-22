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


# --- 敵の表（RX-0090 / 2026-08-21）-------------------------------------------
#
# ★memory_map.yaml には敵の表が**入っていない**（利用者の ROM から起こす）。
#   図鑑・戦況パネルのテストは実値（スライムの HP 6 など）を見るので、
#   ROM（またはそのキャッシュ）が無い環境では**スキップ**する。
#   ⚠ 0 や空で埋めて通さない（「動いた」と嘘をつくことになる）。

import pytest  # noqa: E402


def load_memory_map_with_enemies() -> dict:
    """YAML + ROM 由来の5表。無ければ pytest.skip。"""
    import yaml
    from retroux.core import enemy_tables

    mm = yaml.safe_load((ROOT / "retroux" / "plugins" / "dq2" / "memory_map.yaml")
                        .read_text(encoding="utf-8"))
    enemy_tables.attach(mm, ROOT / "work" / "rom" / "DQ2_J.nes",
                        ROOT / "work" / "generated" / enemy_tables.CACHE_NAME)
    if "monsters" not in mm:
        pytest.skip("敵の表が無い（ROM もキャッシュも無い環境）")
    return mm


@pytest.fixture(scope="session")
def memory_map_with_enemies() -> dict:
    return load_memory_map_with_enemies()
