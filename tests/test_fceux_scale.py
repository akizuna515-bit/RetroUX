"""FCEUX の映像倍率を fceux.cfg に書く（2026-08-20 / UAT）。

★★ --xscale は効かない（実測）。窓倍率は winsizemulx/y（base64 の倍精度）。
"""

from __future__ import annotations

import base64
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retroux.tools.fceux_scale import encoded, set_scale  # noqa: E402


def test_encoded_matches_fceux_double():
    # ★2.0 は dev の fceux.cfg と一致する（little-endian double）。
    assert encoded(2) == "base64:AAAAAAAAAEA="
    assert encoded(1) == "base64:" + base64.b64encode(
        struct.pack("<d", 1.0)).decode()


def test_patches_existing_keys_without_touching_others(tmp_path):
    cfg = tmp_path / "fceux.cfg"
    cfg.write_text(
        "someKey 1\nwinsizemulx base64:OLD\nwinsizemuly base64:OLD\nother 5\n",
        encoding="utf-8")
    set_scale(cfg, 2)
    text = cfg.read_text(encoding="utf-8")
    assert "winsizemulx base64:AAAAAAAAAEA=" in text
    assert "winsizemuly base64:AAAAAAAAAEA=" in text
    assert "base64:OLD" not in text
    assert "someKey 1" in text and "other 5" in text     # 他キーは不変


def test_creates_a_missing_cfg(tmp_path):
    cfg = tmp_path / "fceux.cfg"
    set_scale(cfg, 2)
    text = cfg.read_text(encoding="utf-8")
    assert "winsizemulx base64:AAAAAAAAAEA=" in text
    assert "winsizemuly base64:AAAAAAAAAEA=" in text


def test_appends_when_keys_absent(tmp_path):
    cfg = tmp_path / "fceux.cfg"
    cfg.write_text("someKey 1\n", encoding="utf-8")
    set_scale(cfg, 2)
    text = cfg.read_text(encoding="utf-8")
    assert "someKey 1" in text
    assert "winsizemulx base64:AAAAAAAAAEA=" in text


def test_is_idempotent(tmp_path):
    cfg = tmp_path / "fceux.cfg"
    set_scale(cfg, 2)
    first = cfg.read_text(encoding="utf-8")
    msg = set_scale(cfg, 2)
    assert cfg.read_text(encoding="utf-8") == first
    assert "既に" in msg
