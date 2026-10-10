"""DQ2 のデータの移行（RX-0157 / RX-0158 / D-45）。

```text
runner.py                      番号つき step を当てる（staging・journal・本番への入れ替え・印）
m0001_legacy_to_portable.py    旧 DQ2 フォルダ（schema 0）→ Portable DQ2（schema 1）
regenerate.py                  移行のあとの作り直し（★移行先のプログラムで動かす）
```

★使い方: `python -m retroux.migration --source <旧フォルダ> --dest <新しいフォルダ>`
"""

from .runner import MigrationStop, Options, Result, migrate, plan

__all__ = ["MigrationStop", "Options", "Result", "migrate", "plan"]
