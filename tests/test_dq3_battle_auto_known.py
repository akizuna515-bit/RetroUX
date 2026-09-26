"""戦闘開始時 自動 / 手動（2026-09-11 依頼者「勝利済のモンスターなら自動でオート・ターボ」→ RX3-0237）。

★2026-09-13: 画面は管理画面のチェックから戦闘AI設定画面「戦闘開始時」へ移した（★鍵は同じ）。

```text
戦闘AI設定「戦闘開始時 自動 / 手動」→ automation.battle_auto_known
  → dq3/phase0/battle_auto_overlay.py → work/generated/dq3_battle_auto.lua → auto_v0.lua（戦闘ごとに読む）
```

★判断そのもの（倒した敵だけ / ボス候補でない / 死者なし / HP）は Lua の足場
（`dq3_battle_speed_test.lua` / `dq3_auto_ai_test.lua` の 10）で見る。ここは画面 → Lua の道。
"""
from __future__ import annotations

import json
import os
import pathlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dq3.phase0 import battle_auto_overlay as BA      # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Settings:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, section, key, default=None):
        return self.data.get(section, {}).get(key, default)


def test_画面で決めていなければ既定に任せる(tmp_path):
    assert BA.enabled(_Settings()) is None
    path = BA.write_overlay(_Settings(), tmp_path)
    assert path.read_text(encoding="utf-8").splitlines()[-1] == "return {}"


def test_切ったら_false_を渡す(tmp_path):
    s = _Settings({"automation": {"battle_auto_known": False}})
    assert BA.enabled(s) is False
    assert "return {auto_known = false}" in BA.write_overlay(s, tmp_path).read_text(encoding="utf-8")
    s.data["automation"]["battle_auto_known"] = True
    assert "return {auto_known = true}" in BA.write_overlay(s, tmp_path).read_text(encoding="utf-8")


def test_書く名前とLuaが読む名前が同じ():
    """⚠ 「書いてある」検査は片側しか見ない（★読み出し元の名前違いで実機が null になった教訓）。"""
    lua = (ROOT / "dq3" / "phase0" / "auto_v0.lua").read_text(encoding="utf-8")
    assert '"/work/generated/%s"' % BA.OVERLAY_NAME in lua, "⚠⚠ Lua が別の名前を読んでいる"
    assert "auto_known" in lua


def test_YAMLの既定はON():
    import yaml

    cfg = yaml.safe_load((ROOT / "config" / "dq3_phase0.yaml").read_text(encoding="utf-8"))
    assert cfg["dq3_phase0"]["auto_battle"]["auto_start_known"] is True


def _admin(tmp_path, data=None):
    from PySide6.QtWidgets import QApplication

    from dq3.knowledge import playdata as PD
    from dq3.ui.admin_window import AdminWindow
    from dq3.ui.ui_settings import UiSettings

    QApplication.instance() or QApplication([])
    if data is not None:
        (tmp_path / "ui.json").write_text(json.dumps(data), encoding="utf-8")
    k = tmp_path / "k"
    k.mkdir(exist_ok=True)

    class _VM:
        def _raw(self): return {}
        def position(self): return None

    class _Cmd:
        def send(self, action, **p): return 1

    return AdminWindow(_VM(), _Cmd(), speed=None, service=PD.PlayDataService(k, tmp_path / "vault"),
                       confirm=lambda t, x: True, settings=UiSettings(tmp_path / "ui.json"))


def test_管理画面からは消えて戦闘AI設定画面へ移った(tmp_path, monkeypatch):
    """★RX3-0237（2026-09-13 依頼者「戦闘開始時の振る舞いは設定画面へ分離する」）: 置き場を 1 つに。

    ⚠ 管理画面のチェックと戦闘AI設定画面の「戦闘開始時」の 2 か所にしない（★同じ鍵を 2 つの画面が書く）。
    ★画面の動きは `tests/test_dq3_battle_start_setting.py`。
    """
    monkeypatch.setenv("RETROUX_WRITE_ROOT", str(tmp_path))
    w = _admin(tmp_path)
    assert not hasattr(w, "cb_battle_auto"), "⚠⚠ 管理画面にまだチェックがある"
    from dq3.ui import admin_window as AW

    assert not hasattr(AW, "BATTLE_AUTO_TEXT")
    src = (ROOT / "dq3" / "ui" / "battle_ai_window.py").read_text(encoding="utf-8")
    assert "BA.SECTION, BA.KEY" in src, "⚠ 戦闘AI設定画面が同じ鍵に書いていない（★前の設定を引き継ぐ）"
    assert json is not None
