"""dq2rom — FC版ドラゴンクエストII の ROM 解析ツール（独立CLI）。

指示書: `input/claude_code_dq2_rom_analysis_tools.md`
仕様検討と疑問点: `docs/design/rom-analysis-tools-spec.md`

★このパッケージは **RetroUX 本体から独立**しています（指示書 §19-9）。
  `retroux` を import しません。成果物は `output/rom-analysis/<sha1>/` に出し、
  本体のデータは書き換えません。

★ROM は同梱しません。テストは自作の極小疑似データだけを使います（指示書 4.4）。
"""

from __future__ import annotations

__version__ = "0.1.0"

# 指示書 §15 の終了コード。CLI 以外からも参照できるようにここに置く。
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ROM_MISMATCH = 2
EXIT_UNSUPPORTED = 3
EXIT_VALIDATION_FAILED = 4
