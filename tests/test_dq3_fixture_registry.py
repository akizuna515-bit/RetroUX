"""固定入力を「意味の分かる registry」で管理する（RX3-0129 拡張 / 2026-09-09）。

```text
A  スロットから登録できる（★写し / hash / 台帳の行）
B  一覧が意味名で出る（⚠ fc4 ではなく battle_ai_injured_party）
C  test → fixture が逆に引ける
D  hash を変えたら checker が赤
E  隔離先へ写して壊しても、★原本は無傷
F  知らない test 名は**空**で返す（⚠ 例外で落とさない）
```

⚠⚠ 本物の fixture は**読むだけ**です。★壊す試験は写しを作ってそこで壊します。

台帳が答えるべき 3 つ（指示書 §21）:

```text
Q1 このセーブは何のため？      → description / tags / expected
Q2 どのテストで使う？          → fixture.tests
Q3 このテストには何が要る？    → FX.for_test(test_id)
```
"""
from __future__ import annotations

import json
import pathlib

import pytest

from dq3.testing import e2e_tests as E2E
from dq3.testing import fixtures as FX
from dq3.testing import sandbox as SB

ROOT = pathlib.Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(not FX.MANIFEST.exists(), reason="fixture がまだありません")


def _copy_env(tmp_path, monkeypatch):
    """★本物の台帳を写して、そこを置き場に見せる（⚠ 原本は触らない）。

    ⚠⚠ 見張り（`production_files`）も写しへ向けます。★向けないと**全件が
      「見張りの外」で赤くなり**、⚠ 仕込んだ 1 件の失敗が紛れて見えなくなります
      （★「何でも赤い」検査は、何も見ていないのと同じ）。
    """
    import shutil

    got = tmp_path / "fixtures"
    shutil.copytree(FX.DIR, got)
    monkeypatch.setattr(FX, "DIR", got)
    monkeypatch.setattr(FX, "STATES", got / "states")
    monkeypatch.setattr(FX, "MANIFEST", got / "fixtures.json")
    monkeypatch.setattr(SB, "production_files",
                        lambda *a, **k: sorted(p for p in got.rglob("*") if p.is_file()))
    return got


def _only(bad: list, word: str) -> None:
    """★仕込んだ 1 件だけが赤いこと（⚠ 巻き添えで全部赤い状態を通さない）。"""
    assert bad, "⚠⚠ 壊したのに 1 件も赤くならない"
    assert any(word in line for line in bad), bad
    noise = [line for line in bad if word not in line]
    assert not noise, "⚠ 関係のない問題まで出ている: %r" % noise


def _cli(*argv) -> str:
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = FX.main(list(argv))
    return "%d%s%s" % (code, chr(10), buf.getvalue())


# --- ★Case A: 登録 ------------------------------------------------------

def test_A_スロットから登録できる(tmp_path, monkeypatch):
    """★本番は読むだけ。⚠ 写しが増え、hash と由来と場面が台帳に載ること。"""
    got = _copy_env(tmp_path, monkeypatch)
    src_dir = tmp_path / "prod"
    src_dir.mkdir()
    seed = FX.get("battle_ai_easy_battle", check=False).path.read_bytes()
    (src_dir / "DQ3_J.fc8").write_bytes(seed)
    before = FX.digest(src_dir / "DQ3_J.fc8")

    fx = FX.capture("battle_ai_poisoned_party", 8, description="毒",
                    purpose="毒状態の戦闘 AI", tags=("battle", "ai", "poison"),
                    tests=("battle_ai_survival",), source_dir=src_dir)

    assert (got / "states" / "battle_ai_poisoned_party.fcs").exists(), "⚠ 写しが無い"
    assert fx.sha256 == before and fx.source_slot == 8
    assert fx.tags == ("battle", "ai", "poison")
    assert fx.expected["party_count"] == 4, "⚠ 場面を観ていない"
    rows = json.loads((got / "fixtures.json").read_text(encoding="utf-8"))["fixtures"]
    assert any(r["id"] == "battle_ai_poisoned_party" for r in rows), "⚠ 台帳に載っていない"
    assert FX.digest(src_dir / "DQ3_J.fc8") == before, "⚠⚠ 元のセーブが変わった"


def test_A_登録しても本番は読むだけ(tmp_path, monkeypatch):
    """⚠⚠ 「登録」で本番のスロットへ書き戻さないこと。"""
    src = (ROOT / "dq3" / "testing" / "fixtures.py").read_text(encoding="utf-8")
    body = src.split("def capture(")[1].split(chr(10) + "def ")[0]
    assert "shutil.copyfile(src, dst)" in body, "⚠ 写していない"
    assert "copyfile(dst, src)" not in body, "⚠⚠ 本番へ書き戻している"


def test_A_世代の控えからも登録できる(tmp_path, monkeypatch):
    """★スロット以外（★`work/savestate-backup` の控え）からも登録できること（RX3-0402）。

    ⚠⚠ そのとき `source_slot` を**書かない**こと。
      ★スロット 0 の中身は遊ぶたびに変わるので、★「slot 0 から採った」は
      ⚠ 半日後には**別のセーブ**を指します（★`source_path` に実物の場所を残す）。
    """
    got = _copy_env(tmp_path, monkeypatch)
    src = tmp_path / "backup" / "20260922-164724-739822-000004.bak"
    src.parent.mkdir(parents=True)
    src.write_bytes(FX.get("battle_ai_easy_battle", check=False).path.read_bytes())
    before = FX.digest(src)

    fx = FX.capture("economy_bench_test", None, description="控えから",
                    purpose="世代の控えを固定入力にする", tags=("battle",),
                    tests=("battle_ai_survival",), source=src)

    assert (got / "states" / "economy_bench_test.fcs").exists()
    assert fx.source_slot is None, "⚠⚠ スロット番号を書いてはいけない"
    assert fx.source_path and fx.source_path.endswith("000004.bak")
    assert fx.sha256 == before
    assert FX.digest(src) == before, "⚠⚠ 元の控えが変わった"
    assert not FX.check_registry(), "⚠ 台帳の検査が赤"


# --- ★Case B: 一覧 ------------------------------------------------------

def test_B_一覧は意味名で出る():
    out = _cli("list")
    assert out.startswith("0")
    assert "battle_ai_injured_party" in out
    assert "tags:" in out and "tests:" in out
    assert "DQ3_J.fc4" not in out, "⚠ 物理ファイル名を外へ出している"


def test_B_由来のスロットは残っているが名前ではない():
    fx = FX.get("battle_ai_injured_party", check=False)
    assert fx.source_slot == 4, "⚠ 由来（provenance）を捨てている"
    assert "fc4" not in fx.id and "slot" not in fx.id


def test_B_showが3つの問いに答える():
    out = _cli("show", "battle_ai_injured_party")
    assert "Purpose:" in out, "⚠ Q1（何のためのデータか）に答えていない"
    assert "Tests:" in out and "battle_ai_survival" in out, "⚠ Q2（どのテストで使うか）"
    assert "Tags:" in out


# --- ★Case C: 逆引き ----------------------------------------------------

def test_C_testからfixtureを引ける():
    got = FX.for_test("battle_ai_survival")
    assert [fx.id for fx in got] == ["battle_ai_injured_party"], "⚠ Q3 に答えられない"
    assert FX.for_test("world_walker_encounter")[0].id == "field_encounter_safe"


#: ★`--test <名前>` だけで回せる必要があるもの（⚠ 文書とコマンド例で名指ししている）
AUTO_TESTS = ("battle_ai_survival", "battle_ai_mp_forbidden", "world_walker_encounter")


def test_C_名前だけで回せるテストは行き先が1つ():
    """⚠⚠ `--test <名前>` は fixture が **1 件のとき**だけ自動で決まります。

    ★2 件紐づくと、⚠ runner は「どちらか選べ」で止まります
      （2026-09-09 に毒 fixture を足して実際に踏んだ）。
    ★複数あってよいテストもあります（`battle_ai_economy` は 2 つの場面で回したい）。
      ⚠ その場合は `--fixture` で選ぶ、を**分かって**そうしていること。
    """
    for test_id in AUTO_TESTS:
        got = FX.for_test(test_id)
        assert len(got) == 1, (
            "⚠⚠ %s は名前だけで回せる必要があります（いま %d 件: %r）"
            % (test_id, len(got), [fx.id for fx in got]))


def test_C_行き先が複数のときrunnerは黙って選ばない():
    """⚠ 曖昧なまま**片方を勝手に**選ぶと、★別の場面の結果を同じ名前で報告します。"""
    src = (ROOT / "scripts" / "dq3_battle_ai_run.py").read_text(encoding="utf-8")
    body = src.split("if args.test:")[1].split("stamp =")[0]
    assert "len(found) != 1" in body, "⚠ 件数を見ていない"
    assert "ap.error" in body, "⚠⚠ 曖昧でも進んでいる"


def test_C_CLIでも逆引きできる():
    out = _cli("for-test", "battle_ai_survival")
    assert out.startswith("0") and "battle_ai_injured_party" in out


def test_C_fixtureからtestを引ける():
    assert "battle_ai_survival" in FX.tests_of("battle_ai_injured_party")
    assert FX.tests_of("town_aliahan_hearing") == [], "⚠ 空でもよい（★形は正しい）"


# --- ★Case D: 台帳の検査（破壊試験）------------------------------------

def test_D_hashを変えたら赤(tmp_path, monkeypatch):
    got = _copy_env(tmp_path, monkeypatch)
    target = got / "states" / "battle_ai_easy_battle.fcs"
    target.write_bytes(target.read_bytes() + b"!")
    _only(FX.check_registry(), "変わっています")


def test_D_id重複は赤(tmp_path, monkeypatch):
    got = _copy_env(tmp_path, monkeypatch)
    data = json.loads((got / "fixtures.json").read_text(encoding="utf-8"))
    data["fixtures"].append(dict(data["fixtures"][0]))
    (got / "fixtures.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _only(FX.check_registry(), "重複")


def test_D_実体を消したら赤(tmp_path, monkeypatch):
    got = _copy_env(tmp_path, monkeypatch)
    (got / "states" / "town_shop_restock.fcs").unlink(missing_ok=True)
    (got / "states" / "field_encounter_safe.fcs").unlink(missing_ok=True)
    _only(FX.check_registry(), "実体がありません")


def test_D_テスト名の打ち間違いは赤(tmp_path, monkeypatch):
    """⚠⚠ 「3 件のテストで使う」と嘘の表示になるのを止める。"""
    got = _copy_env(tmp_path, monkeypatch)
    data = json.loads((got / "fixtures.json").read_text(encoding="utf-8"))
    data["fixtures"][0]["tests"] = ["battle_ai_survivall"]        # ⚠ l が 1 つ多い
    (got / "fixtures.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _only(FX.check_registry(), "そんなテストはありません")


def test_D_場面の欄の打ち間違いは赤(tmp_path, monkeypatch):
    got = _copy_env(tmp_path, monkeypatch)
    data = json.loads((got / "fixtures.json").read_text(encoding="utf-8"))
    data["fixtures"][0]["expected"]["in_battel"] = True           # ⚠ 綴り違い
    (got / "fixtures.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    bad = FX.check_registry()
    assert any("知らない場面の欄" in line for line in bad), bad
    # ⚠ 綴り違いは 2 通りに出ます（★欄の名前 / ★合わせる相手が居ない）。
    #   ★どちらも**同じ 1 か所**を指していること（⚠ 巻き添えで他が赤くなっていない）。
    assert all("in_battel" in line for line in bad), bad


def test_D_tagsの形が違えば赤(tmp_path, monkeypatch):
    got = _copy_env(tmp_path, monkeypatch)
    data = json.loads((got / "fixtures.json").read_text(encoding="utf-8"))
    data["fixtures"][0]["tags"] = "battle,ai"                     # ⚠ 一覧ではない
    (got / "fixtures.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _only(FX.check_registry(), "文字列の一覧")


def test_D_いまの台帳は通る():
    assert FX.check_registry() == [], FX.check_registry()


# --- ★Case E: 隔離先 ----------------------------------------------------

def test_E_隔離先で壊しても原本は無傷(tmp_path):
    prod = tmp_path / "prod"
    (prod / "tools" / "fceux" / "fcs").mkdir(parents=True)
    (prod / "tools" / "fceux" / "sav").mkdir(parents=True)
    sbx = SB.create("reg", production_root=prod, sandbox_root=tmp_path / "sandbox")
    fx = FX.get("town_shop_restock")
    before = FX.digest(fx.path)
    slot = FX.install(fx, sbx)
    (sbx.saves / ("DQ3_J.fc%d" % slot)).write_bytes(b"broken-by-test")
    assert FX.digest(fx.path) == before, "⚠⚠ 原本が変わった"
    used = json.loads((sbx.root / "fixtures-used.json").read_text(encoding="utf-8"))
    assert used[0]["tags"] and used[0]["tests"], "⚠ 証跡に意味が残っていない"


def test_E_fixtureは見張りの中にある():
    """⚠⚠ 隔離の外から直接 WRITE される場所に置かれていないこと。"""
    guarded = {str(p) for p in SB.production_files(ROOT)}
    for fx in FX.all_fixtures():
        assert str(fx.path) in guarded, "⚠⚠ 見張りの外: %s" % fx.id


# --- ★Case F: 知らない名前 ----------------------------------------------

def test_F_知らないtestは空で返す():
    assert FX.for_test("battle_ai_nonexistent") == []
    assert FX.tests_of("nonexistent_fixture") == []
    assert FX.resolve_test("battle_ai_nonexistent") is None


def test_F_CLIも落ちない():
    out = _cli("for-test", "battle_ai_nonexistent")
    assert out.startswith("0"), "⚠ 例外で落としている"
    assert "そんなテストはありません" in out


# --- ★テストの名簿 ------------------------------------------------------

def test_名簿の作戦は製品の定義と揃っている():
    """⚠ 名簿だけ増やして製品に無い作戦を書けないこと。"""
    from dq3.battle_ai import settings as S

    for t in E2E.TESTS.values():
        if t.scenario:
            assert t.strategy in S.STRATEGIES and t.mp in S.MP_POLICIES, t.id


def test_名簿のrunnerが実在する():
    for t in E2E.TESTS.values():
        assert (ROOT / t.runner).exists(), "⚠ 無い script を指している: %s" % t.runner


def test_意味の分かるテスト名になっている():
    assert "battle_ai_survival" in E2E.TESTS and "world_walker_encounter" in E2E.TESTS
    assert not any(t.startswith("case_") for t in E2E.TESTS), "⚠ case_a のような名前"


def test_実機のrunnerは名前1つで回せる():
    src = (ROOT / "scripts" / "dq3_battle_ai_run.py").read_text(encoding="utf-8")
    assert '"--test"' in src, "⚠ テスト名で回せない"
    assert "FX.for_test(args.test)" in src, "⚠ 名前から fixture を引いていない"
    assert "fixture_tests" in src, "⚠ 報告へ対応を残していない"


def test_checkerが単体で回せる():
    import subprocess
    import sys

    got = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_fixtures.py")],
                         capture_output=True, text=True, encoding="utf-8",
                         env={**__import__("os").environ, "PYTHONUTF8": "1"})
    assert got.returncode == 0, got.stdout + got.stderr
    assert "問題なし" in got.stdout
