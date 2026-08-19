"""`python -m dq2rom` の入口（指示書 §15）。"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
