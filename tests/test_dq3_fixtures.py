"""実機テストの固定入力を名前で扱う（RX3-0129 / 2026-09-08）。

```text
A  名前で引くと、正しいセーブへ辿り着く
B  中身を変えたら、使う前に断る
C  隔離先へ写す。⚠ 原本は変わらない
D  同じ fixture から 2 回 run しても、初期状態の hash は同じ
E  無い名前は、理由をつけて断る
```

⚠⚠ 本物の fixture は**読むだけ**です。★壊す試験は写しを作ってそこで壊します。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3.testing import fixtures as FX
from dq3.testing import sandbox as SB

ROOT = pathlib.Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not FX.MANIFEST.exists(), reason="fixture がまだありません")


def _copy_env(tmp_path, monkeypatch):
    """★本物の fixture を写して、そこを台帳の置き場に見せる（⚠ 原本は触らない）。"""
    import shutil

    got = tmp_path / "fixtures"
    shutil.copytree(FX.DIR, got)
    monkeypatch.setattr(FX, "DIR", got)
    monkeypatch.setattr(FX, "STATES", got / "states")
    monkeypatch.setattr(FX, "MANIFEST", got / "fixtures.json")
    return got


# --- ★Case A ------------------------------------------------------------

def test_A_名前で引ける():
    fx = FX.get("battle_ai_injured_party")
    assert fx.path.exists() and fx.path.stat().st_size > 1000
    assert fx.expected["in_battle"] is True
    assert fx.expected["party_count"] == 4 and fx.expected["party_injured"] is True
    assert fx.expected["enemy_count"] >= 1
    assert fx.source_slot is not None, "⚠ 由来（元のスロット）を残していない"


def test_A_台帳の全部が検算を通る():
    bad = FX.verify_all()
    assert bad == [], chr(10).join(bad)
    ids = [f.id for f in FX.all_fixtures()]
    assert "battle_ai_injured_party" in ids and "battle_ai_easy_battle" in ids


def test_A_場面はセーブから読んでいる():
    """⚠ 台帳の値を信じない。★セーブステートを実際に読み直して比べる。"""
    fx = FX.get("battle_ai_easy_battle", check=False)
    now = FX.conditions_of(fx.path)
    assert now["in_battle"] == fx.expected["in_battle"]
    assert now["party_count"] == fx.expected["party_count"]
    assert now["map_id"] == fx.expected["map_id"]


# --- ★Case B（破壊試験）------------------------------------------------

def test_B_中身を変えたら使う前に断る(tmp_path, monkeypatch):
    got = _copy_env(tmp_path, monkeypatch)
    target = got / "states" / "battle_ai_injured_party.fcs"
    target.write_bytes(target.read_bytes() + b"!")
    with pytest.raises(FX.FixtureChanged) as err:
        FX.get("battle_ai_injured_party")
    assert "sha256" in str(err.value)


def test_B_場面が変わっても断る(tmp_path, monkeypatch):
    """★sha256 は合わせても、⚠ 中の場面が違えば止める（★台帳を書き換えた場合）。"""
    got = _copy_env(tmp_path, monkeypatch)
    data = json.loads((got / "fixtures.json").read_text(encoding="utf-8"))
    for row in data["fixtures"]:
        if row["id"] == "battle_ai_easy_battle":
            row["expected"]["party_count"] = 2          # ⚠ 台帳だけ嘘にする
    (got / "fixtures.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FX.FixtureChanged) as err:
        FX.get("battle_ai_easy_battle")
    assert "場面が違います" in str(err.value)


def test_B_実体が無ければ断る(tmp_path, monkeypatch):
    got = _copy_env(tmp_path, monkeypatch)
    (got / "states" / "town_aliahan_hearing.fcs").unlink()
    with pytest.raises(FX.FixtureError):
        FX.get("town_aliahan_hearing")


# --- ★Case C / D --------------------------------------------------------

def test_C_隔離先へ写しても原本は変わらない(tmp_path):
    prod = tmp_path / "prod"
    (prod / "tools" / "fceux" / "fcs").mkdir(parents=True)
    (prod / "tools" / "fceux" / "sav").mkdir(parents=True)
    sbx = SB.create("fx", production_root=prod, sandbox_root=tmp_path / "sandbox")
    fx = FX.get("battle_ai_injured_party")
    before = FX.digest(fx.path)
    slot = FX.install(fx, sbx)
    target = sbx.saves / ("DQ3_J.fc%d" % slot)
    assert target.exists() and FX.digest(target) == before
    target.write_bytes(b"broken-by-test")               # ⚠ 隔離先を壊しても…
    assert FX.digest(fx.path) == before, "⚠⚠ 原本が変わった"
    used = json.loads((sbx.root / "fixtures-used.json").read_text(encoding="utf-8"))
    assert used[0]["id"] == fx.id and used[0]["sha256"] == before, "⚠ 証跡に残っていない"


def test_D_同じfixtureから2回runしても初期状態は同じ(tmp_path):
    prod = tmp_path / "prod"
    (prod / "tools" / "fceux" / "fcs").mkdir(parents=True)
    (prod / "tools" / "fceux" / "sav").mkdir(parents=True)
    fx = FX.get("battle_ai_easy_battle")
    seen = []
    for i in range(2):
        sbx = SB.create("fx%d" % i, production_root=prod, sandbox_root=tmp_path / "sandbox")
        slot = FX.install(fx, sbx)
        seen.append(FX.digest(sbx.saves / ("DQ3_J.fc%d" % slot)))
        (sbx.saves / ("DQ3_J.fc%d" % slot)).write_bytes(b"dirty")   # ⚠ run が汚しても
    assert seen[0] == seen[1] == fx.sha256, "⚠⚠ 2 回目の初期状態が違う"


# --- ★Case E ------------------------------------------------------------

def test_E_無い名前は理由をつけて断る():
    with pytest.raises(FX.FixtureError) as err:
        FX.get("battle_ai_nonexistent")
    text = str(err.value)
    assert "battle_ai_nonexistent" in text and "battle_ai_injured_party" in text


# --- ★つなぎ ------------------------------------------------------------

def test_fixtureは本番と同じく見張られている():
    """⚠⚠ fixture 自体も WRITE 禁止（★`sandbox` の見張りに入っていること）。"""
    guarded = [str(p) for p in SB.production_files(ROOT)]
    assert any("work/tests/fixtures" in p.replace(chr(92), "/") for p in guarded), "⚠ fixture が見張りの外にある"


def test_実機のrunnerは名前でfixtureを指定できる():
    src = (ROOT / "scripts" / "dq3_battle_ai_run.py").read_text(encoding="utf-8")
    assert "--fixture" in src and "FX.install(fx, sbx)" in src
    assert "fixture_sha256" in src, "⚠ 報告に hash を残していない"


def test_CLIで一覧できる():
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert FX.main(["list"]) == 0
    assert "battle_ai_injured_party" in buf.getvalue()
