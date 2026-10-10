"""DQ2 の製品の版（RX-0160 / D-47「DQ2 と DQ3 で版を分ける」）。

★正本は pyproject.toml の [tool.retroux] dq2-version。⚠ [project].version は DQ3 の版のまま。
★配布 Runtime（pyproject が無い）では build-info.json の version を、product が retroux-dq2 のときだけ使う。
"""

from __future__ import annotations

from pathlib import Path

from retroux import version as shared
from retroux.core import dq2_version as V

ROOT = Path(__file__).resolve().parents[1]


def test_DQ2とDQ3の版は別に読む() -> None:
    assert V.get_version() != V.UNKNOWN
    assert shared.get_version() != shared.UNKNOWN
    assert V._from_pyproject() == V.get_version()


def test_節の中の鍵だけを読む(tmp_path, monkeypatch) -> None:
    text = ('[project]\nversion = "9.9.9"\n\n[tool.retroux]\n# 註に [project].version と書いても切れない\n'
            'dq2-version = "2.3.4"\n\n[tool.other]\ndq2-version = "0.0.1"\n')
    sec = V._SECTION.search(text)
    assert sec and V._KEY.search(sec.group(1)).group(1) == "2.3.4"
    other = '[project]\nversion = "1.0"\n[tool.other]\ndq2-version = "0.0.1"\n'
    sec = V._SECTION.search(other)
    assert sec is None


def test_配布物ではDQ2のbuild_infoだけを使う(monkeypatch) -> None:
    monkeypatch.setattr(V, "_from_pyproject", lambda: None)
    monkeypatch.setattr(shared, "build_info", lambda: {"product": "retroux-dq2", "version": "1.2.3"})
    assert V.get_version() == "1.2.3"
    monkeypatch.setattr(shared, "build_info", lambda: {"product": "retroux-dq3", "version": "1.1.1"})
    assert V.get_version() == V.UNKNOWN, "⚠ DQ3 の build-info の版を DQ2 の版として出した"


def test_DQ2の画面と記録はDQ2の版を出す() -> None:
    for rel in ("retroux/gui.py", "retroux/ui/main_window.py", "retroux/core/diagnostics.py"):
        text = (ROOT / rel).read_bytes().decode("utf-8")
        assert "dq2_version" in text, rel
        assert "from .version import VERSION" not in text and "from ..version import" not in text, rel
