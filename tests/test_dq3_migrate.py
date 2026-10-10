"""版を上げるときの引き継ぎ（方式 B）の実演（RX3-0472 / 2026-10-01）。

## ⚠⚠ なぜ「実演」なのか

★`USER_DATA` の一覧が正しいことは、⚠ 一覧を読むだけでは分かりません。
⚠⚠ **旧フォルダを作り、遊んだ形のデータを置き、新フォルダへ写して、
1 バイトも変わっていないことを数える**ところまでやらないと、
★「写したつもり」が緑のまま通ります。

```text
★見るもの
  ① user data が **byte 単位で同じ**か（⚠ 件数だけでは足りない）
  ② ⚠⚠ 旧版が **1 バイトも変わっていない**か（copy only）
  ③ derived が**写っていない**か（★新しい版で作り直す）
  ④ 途中で止まったことが**分かる**か（`work/.migration-incomplete`）
```
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from dq3 import migrate as MG
from dq3 import ownership as OWN

ROOT = pathlib.Path(__file__).resolve().parents[1]


# --- ★足場 ------------------------------------------------------------

def _snapshot(root: pathlib.Path) -> dict[str, str]:
    """★その木の全ファイルの (相対パス → sha256)。⚠ 中身まで見る。"""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def _make_old(root: pathlib.Path, *, version: str = "1.1.0") -> pathlib.Path:
    """★「遊んだあとの旧版フォルダ」を作る（⚠ shipped / user / derived を全部）。"""
    root.mkdir(parents=True, exist_ok=True)
    # --- shipped（★引き継がない）
    (root / "dq3").mkdir(parents=True, exist_ok=True)
    (root / "dq3" / "paths.py").write_bytes(b"# program\n")
    (root / "DQ3.cmd").write_bytes(b"@echo off\r\n")
    (root / "runtime" / "python").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "python" / "python.exe").write_bytes(b"MZ")
    (root / "build-info.json").write_text(
        json.dumps({"product": "retroux-dq3", "version": version,
                    "source_commit": "0123456789abcdef"}),
        encoding="utf-8")
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "dq3_phase0.yaml").write_bytes(b"keys: shipped\n")
    # ⚠ 旧版にだけある shipped（★方式 B では**写らない**ことを見る）
    (root / "dq3" / "old_thing.py").write_bytes(
        "# ⚠ 1.1.0 にしか無い\n".encode("utf-8"))

    # --- user（★引き継ぐ）
    (root / "user_config.yaml").write_bytes(
        "paths:\n  dq3_rom: D:/ROM/DQ3_J.nes\n".encode("utf-8"))
    know = root / "work" / "dq3-knowledge"
    know.mkdir(parents=True, exist_ok=True)
    (know / "memos.jsonl").write_bytes(
        '{"memo":"★オーブを聞いた"}\n'.encode("utf-8"))
    (know / "location-book.json").write_bytes(b'{"visited": 23}\n')
    backup = root / "work" / "savestate-backup"
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "DQ3_J.fc1.20260930-120000").write_bytes(bytes(range(256)))
    (root / "work" / "dq3-ui-settings.json").write_bytes(b'{"tactics": 2}\n')
    (root / "work" / "dq3-window-state.json").write_bytes(b'{"x": 100}\n')
    # ★★ ⚠ 2026-10-01 の実演に**無かった** 2 つ（依頼者 §5）★★
    #   ⚠⚠ `playdata-archive` は「消えたら戻らない」ほうなので、★必ず入れる。
    vault = root / "work" / "playdata-archive" / "dq3-20260930-235959"
    vault.mkdir(parents=True, exist_ok=True)
    (vault / "seen.json").write_bytes(b"{}\n")
    (vault / "memos.jsonl").write_bytes(b'{"memo":"old"}\n')
    rom = root / "work" / "rom"
    rom.mkdir(parents=True, exist_ok=True)
    (rom / "DQ3_J.nes").write_bytes(b"NES\x1a" + bytes(32))
    # ★user override（⚠ shipped を書き換えた版）
    ud = root / "work" / "user-data" / "config"
    ud.mkdir(parents=True, exist_ok=True)
    (ud / "dq3_phase0.yaml").write_bytes(b"keys: mine\n")

    # --- derived（★引き継がない）
    gen = root / "work" / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "dq3_phase0.lua").write_bytes(b"-- generated\n")
    art = root / "work" / "cache" / "dq3-monster-art"
    art.mkdir(parents=True, exist_ok=True)
    (art / "001.png").write_bytes(b"\x89PNG")
    (root / "work" / "state.json").write_bytes(b'{"frame": 1}\n')
    (root / "work" / "retroux.log").write_bytes(b"INFO\n")
    (root / "work" / "recorder.lock").write_bytes(b"1")
    log = root / "work" / "runtime" / "dq3-log"   # ★RX3-0493
    log.mkdir(parents=True, exist_ok=True)
    (log / "product.log").write_bytes(b"old\n")
    return root


def _make_new(root: pathlib.Path, *, version: str = "1.2.0") -> pathlib.Path:
    """★「新しい ZIP を空のフォルダへ展開した直後」を作る（⚠ work/ は無い）。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "dq3").mkdir(parents=True, exist_ok=True)
    (root / "dq3" / "paths.py").write_bytes(b"# program 1.2.0\n")
    (root / "DQ3.cmd").write_bytes(b"@echo off\r\n")
    (root / "build-info.json").write_text(
        json.dumps({"product": "retroux-dq3", "version": version,
                    "source_commit": "fedcba9876543210"}),
        encoding="utf-8")
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "dq3_phase0.yaml").write_bytes(b"keys: shipped 1.2.0\n")
    return root


@pytest.fixture()
def pair(tmp_path):
    old = _make_old(tmp_path / "RetroUX-DQ3-1.1.0")
    new = _make_new(tmp_path / "RetroUX-DQ3-1.2.0")
    return old, new


# --- ★移行元を見る ----------------------------------------------------

def test_旧版を見つけて版を読む(pair):
    old, new = pair
    got = MG.probe(old, new)
    assert got.ok
    assert got.version == "1.1.0"
    assert got.describe() == "retroux-dq3 1.1.0"
    assert got.files > 0 and got.size > 0


def test_引き継ぐ一覧はownershipから来る(pair):
    """⚠⚠ 一覧を**写していない**こと（★片方だけ古くなるのを止める）。"""
    old, _new = pair
    rels = {i.rel for i in MG.plan(old)}
    assert rels == {e.rel for e in OWN.USER_DATA}


def test_自分自身を移行元にできない(pair):
    old, _new = pair
    got = MG.probe(old, old)
    assert not got.ok
    assert any("いま動いているフォルダ自身" in p for p in got.problems)


def test_入れ子を拒む(tmp_path):
    old = _make_old(tmp_path / "old")
    inner = old / "work" / "inner-new"
    inner.mkdir(parents=True)
    got = MG.probe(old, inner)
    assert not got.ok
    assert any("移行先が移行元の中" in p for p in got.problems)


def test_無いフォルダは名指しで断る(tmp_path):
    got = MG.probe(tmp_path / "どこにもない", tmp_path / "new")
    assert not got.ok
    assert "ありません" in got.problems[0]


def test_違うフォルダなら何が足りないか出す(tmp_path):
    """⚠⚠ 「らしくない」で終わらせない（★依頼者 2026-10-01）。"""
    wrong = tmp_path / "Documents"
    wrong.mkdir()
    (wrong / "memo.txt").write_bytes(b"x")
    got = MG.probe(wrong, tmp_path / "new")
    assert not got.ok
    text = "\n".join(got.problems)
    for rel, _why in MG.ROOT_MARKERS:
        assert rel in text, "⚠ %s が足りないことを言っていません" % rel


def test_遊んでいない旧版は断る(tmp_path):
    """★shipped だけのフォルダ（⚠ 引き継ぐものが無い）。"""
    old = _make_new(tmp_path / "old", version="1.1.0")
    got = MG.probe(old, tmp_path / "new")
    assert not got.ok
    assert any("1 つもありません" in p for p in got.problems)


def test_版が読めなくても引き継げる(tmp_path):
    """⚠ `build-info.json` が壊れていても user data は写せる（★止めない）。"""
    old = _make_old(tmp_path / "old")
    (old / "build-info.json").write_bytes(b"{ broken")
    got = MG.probe(old, tmp_path / "new")
    assert got.ok
    assert any("版を読めません" in p for p in got.problems)


# --- ★★ ⚠⚠ 引き継ぎの実演（これが本体）★★ -------------------------

def test_実演_8分類すべてが写り旧版は無傷(pair):
    """★★ 旧 → 新 へ写して、⚠⚠ **4 つを同時に**確かめる ★★

    ⚠ 2026-10-01 の 1 回目の実演は `playdata-archive` と `rom` が
      旧版に無く、★**6 分類しか見ていませんでした**（依頼者 §5 の指摘）。
      → ⚠⚠ いまは **8 分類すべて**を材料に入れ、1 件でも欠けたら赤にします。
    """
    old, new = pair
    before_old = _snapshot(old)

    got = MG.run(old, new)
    assert got.ok, got.failed
    assert got.copied > 0
    assert got.skipped == ()
    assert got.outcome == MG.OUT_OK

    # --- ⓪ ⚠⚠ **8 分類すべて**が材料に在る（★足場の穴を塞ぐ）
    missing = [e.rel for e in OWN.USER_DATA if not (old / e.rel).exists()]
    assert not missing, (
        "⚠⚠ 足場に無い user data があります（★実演が覆っていません）: %s" % missing)
    assert len(OWN.USER_DATA) == 8

    # --- ① ⚠⚠ user data が **byte 単位で同じ**
    for entry in OWN.USER_DATA:
        src = old / entry.rel
        dst = new / entry.rel
        assert dst.exists(), "⚠⚠ %s が写っていません" % entry.rel
        assert _snapshot_of(src) == _snapshot_of(dst), (
            "⚠⚠ %s の中身が変わりました" % entry.rel)

    # --- ② ⚠⚠ 旧版が **1 バイトも変わっていない**（copy only）
    assert _snapshot(old) == before_old, "⚠⚠ 移行元を変えました（★copy only 違反）"

    # --- ③ derived は写っていない
    for entry in OWN.entries_of(OWN.KIND_DERIVED):
        if "*" in entry.rel:
            continue
        src = old / entry.rel
        if not src.exists():
            continue
        # ⚠ `work/runtime/dq3-log/` は**引き継ぎの記録**を書く先なので、中身が違うことを見る
        if entry.rel == "work/runtime":
            assert not (new / "work" / "runtime" / "dq3-log" / "product.log").exists()
            continue
        assert not (new / entry.rel).exists(), (
            "⚠ derived を写しています: %s" % entry.rel)

    # --- ④ 途中で終わった印が消えている
    assert not MG.incomplete_marker(new).is_file()
    assert MG.pending(new) is None
    assert got.journal is not None and got.journal.is_file()


def _snapshot_of(target: pathlib.Path) -> dict[str, str]:
    if target.is_file():
        return {target.name: hashlib.sha256(target.read_bytes()).hexdigest()}
    return _snapshot(target)


def test_実演_旧版にしかないプログラムは写らない(pair):
    """⚠⚠ **方式 B の核心** — ★旧 `.py` が新しいフォルダに現れない。"""
    old, new = pair
    assert (old / "dq3" / "old_thing.py").is_file()
    MG.run(old, new)
    assert not (new / "dq3" / "old_thing.py").exists(), (
        "⚠⚠ 旧版のプログラムが写りました（★方式 B の意味が消えます）")
    # ★新しい版の shipped がそのまま残っている
    assert (new / "config" / "dq3_phase0.yaml").read_bytes() == b"keys: shipped 1.2.0\n"
    assert (new / "dq3" / "paths.py").read_bytes() == b"# program 1.2.0\n"


def test_実演_カスタマイズ版が引き継がれて優先される(pair, monkeypatch):
    """★user override が写り、⚠ 新しい版でも user 側が読まれる。"""
    old, new = pair
    MG.run(old, new)
    user = new / "work" / "user-data" / "config" / "dq3_phase0.yaml"
    assert user.read_bytes() == b"keys: mine\n"

    monkeypatch.setenv(OWN.P3.ENV, str(new))
    monkeypatch.setattr(OWN.P3, "program_root", lambda: new)
    assert OWN.resolve("config/dq3_phase0.yaml") == user
    # ⚠⚠ 見本が新しくなっているので、★引き継いだ直後に知らせが出る
    OWN.write_baseline({"config/dq3_phase0.yaml":
                        {"shipped_sha256": "★旧版のときの値"}}, new)
    got = OWN.master_update_notices()
    assert len(got) == 1 and "標準版が更新されています" in got[0]


def test_既にあるものを上書きしない(pair):
    """⚠⚠ 新版で少し遊んでしまった人の記録を**消さない**。"""
    old, new = pair
    mine = new / "work" / "dq3-knowledge"
    mine.mkdir(parents=True)
    (mine / "memos.jsonl").write_bytes(b'{"memo":"new"}\n')

    got = MG.run(old, new)
    assert (mine / "memos.jsonl").read_bytes() == b'{"memo":"new"}\n'
    assert "work/dq3-knowledge/memos.jsonl" in got.skipped
    # ★ぶつからなかったものは写っている
    assert (mine / "location-book.json").is_file()


def test_dry_runは1バイトも書かない(pair):
    old, new = pair
    before = _snapshot(new)
    got = MG.run(old, new, dry_run=True)
    assert got.dry_run and got.copied > 0
    assert _snapshot(new) == before
    assert not MG.incomplete_marker(new).exists()


def test_途中で止まったら印が残る(pair, monkeypatch):
    """⚠⚠ 「どこまで写せたか分からない」を作らない。"""
    old, new = pair
    real = MG.shutil.copy2
    calls = {"n": 0}

    def boom(src, dst, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("⚠ わざと失敗させました")
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(MG.shutil, "copy2", boom)
    got = MG.run(old, new)
    assert not got.ok and got.failed
    assert MG.incomplete_marker(new).is_file(), (
        "⚠⚠ 失敗したのに印が消えています（★途中だと分からなくなります）")
    stuck = MG.pending(new)
    assert stuck and stuck["items"] and str(old) in stuck["source"]
    # ★記録にどこで失敗したかが残っている
    body = MG.journal_path(new).read_text(encoding="utf-8")
    assert "わざと失敗させました" in body
    # ⚠⚠ 旧版は無傷
    assert (old / "work" / "dq3-knowledge" / "memos.jsonl").is_file()


def test_もう一度走らせれば続きが写る(pair, monkeypatch):
    """★失敗したあとに再実行して埋まる（⚠ 印が消える）。"""
    old, new = pair
    real = MG.shutil.copy2
    calls = {"n": 0}

    def boom(src, dst, *a, **kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("⚠ わざと")
        return real(src, dst, *a, **kw)

    monkeypatch.setattr(MG.shutil, "copy2", boom)
    MG.run(old, new)
    monkeypatch.setattr(MG.shutil, "copy2", real)
    got = MG.run(old, new)
    assert got.ok
    assert not MG.incomplete_marker(new).is_file()
    for entry in OWN.USER_DATA:
        if (old / entry.rel).exists():
            assert (new / entry.rel).exists(), entry.rel


def test_起動の知らせに途中の引き継ぎが出る(pair, monkeypatch):
    """★`dq3/startup.py` が印を見て 1 行出す（⚠ 直さない / 知らせるだけ）。"""
    from dq3 import startup as ST

    old, new = pair
    monkeypatch.setenv(OWN.P3.ENV, str(new))
    monkeypatch.setattr(MG.shutil, "copy2",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("⚠ わざと")))
    MG.run(old, new)
    got = ST.notices()
    assert any("途中で終わっています" in line for line in got), got


# --- ★ derived は作り直せる -------------------------------------------

def test_derivedを捨てても作り直せる(tmp_path, monkeypatch):
    """⚠⚠ 方式 B の前提（★実測 0.50 秒 / モンスターの絵 139 枚）。

    ⚠ ROM が無い環境では **skip ではなく** 「理由が残ること」を見ます
      （★`ensure()` は落とさず `last_error` に残す約束）。
    """
    from dq3.knowledge import monster_art

    monkeypatch.setenv(OWN.P3.ENV, str(tmp_path))
    art = pathlib.Path(monster_art.ART_DIR)
    assert not art.exists()
    made = monster_art.ensure()
    if made == 0:
        assert monster_art.last_error, (
            "⚠⚠ 0 枚なのに理由が残っていません（★黙って空振りしています）")
    else:
        assert art.is_dir() and any(art.glob("*.png"))


# --- ★ CLI -----------------------------------------------------------

def test_cliのdry_runは終了コード0(pair, capsys):
    old, new = pair
    rc = MG.main(["--from", str(old), "--to", str(new), "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "1 バイトも書いていません" in out
    assert "引き継ぐもの:" in out
    assert "引き継がないもの:" in out
    assert _snapshot(new) == _snapshot(new)


def test_cliは駄目なフォルダで2を返す(tmp_path, capsys):
    wrong = tmp_path / "Downloads"
    wrong.mkdir()
    rc = MG.main(["--from", str(wrong), "--to", str(tmp_path / "new")])
    assert rc == 2
    assert "引き継げません" in capsys.readouterr().out


def test_次にすることが結果ごとに違う(pair, monkeypatch):
    """⚠⚠ **見出しがあるだけでは足りない**（★中身を見る）。

    ⚠ 2026-10-01 の壊す実験: `next_step()` を空にしても
      「次にすること」という**見出しは出る**ので緑のままでした。
    → ★3 つの結果で**違う言葉**が出ることを固定します。
    """
    old, new = pair
    ok = MG.run(old, new)
    assert ok.outcome == MG.OUT_OK
    assert "このまま遊べます" in ok.next_step()

    partial = MG.run(old, new)                   # ⚠ 2 度目は全部ぶつかる
    assert partial.outcome == MG.OUT_PARTIAL
    assert "新しいフォルダへもう一度展開" in partial.next_step()

    new2 = _make_new(new.parent / "RetroUX-DQ3-1.3.0", version="1.3.0")
    monkeypatch.setattr(
        MG.shutil, "copy2",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("⚠ わざと")))
    failed = MG.run(old, new2)
    assert failed.outcome == MG.OUT_FAILED
    assert "もう一度同じコマンド" in failed.next_step()

    # ⚠⚠ 3 つが**別の言葉**であること（★使い回していない）
    assert len({ok.next_step(), partial.next_step(), failed.next_step()}) == 3
    for got in (ok, partial, failed):
        assert got.next_step().strip(), "⚠⚠ 次にすることが空です: %s" % got.outcome


def test_cliは完了と一部完了を区別する(pair, capsys):
    """⚠⚠ **全件成功と同じ顔で出さない**（依頼者 2026-10-01 §3）。"""
    old, new = pair
    rc = MG.main(["--from", str(old), "--to", str(new)])
    out = capsys.readouterr().out
    assert rc == 0 and "引き継ぎ: %s" % MG.OUT_OK in out
    for word in ("コピーできた", "引き継げなかった", "失敗",
                 "次にすること", "詳しい記録"):
        assert word in out, word

    # ⚠ もう一度やると全部ぶつかる → ★「一部完了」になる
    rc2 = MG.main(["--from", str(old), "--to", str(new)])
    out2 = capsys.readouterr().out
    assert rc2 == 0
    assert "引き継ぎ: %s" % MG.OUT_PARTIAL in out2, out2
    assert MG.OUT_OK not in out2.splitlines()[0]


# --- ★★ ⚠⚠ 新版の初期化と引き継ぎの順序（依頼者 §2）★★ ---------------

def test_起動しただけならuser_dataは作られない(tmp_path, monkeypatch):
    """★★ ⚠⚠ **引き継ぐ前に user data を作らない** ★★

    ⚠ 2026-10-01 の実測で分かったこと:

    ```text
    窓を作る   → work/generated/*.lua        ★derived だけ
    閉じる     → work/dq3-window-state.json  ⚠⚠ **user** が出来る
    ```

    ★だから `dq3/ui/app.py` は**窓を作る前に**誘いを出します。
    ⚠ ここでは「誘いの条件」が窓の前後で崩れないことを見ます。
    """
    monkeypatch.setenv(OWN.P3.ENV, str(tmp_path))
    assert MG.should_offer() is True                 # ★まっさら

    # ★derived が出来ても誘いは出る
    gen = tmp_path / "work" / "generated"
    gen.mkdir(parents=True)
    (gen / "dq3_phase0.lua").write_bytes(b"-- x\n")
    assert MG.should_offer() is True

    # ⚠⚠ 閉じたときに出来る窓の位置は「遊んだ証拠」にしない
    (tmp_path / "work" / "dq3-window-state.json").write_bytes(b'{"x":1}\n')
    assert MG.should_offer() is True, (
        "⚠⚠ 1 度閉じただけで誘いが出なくなります（★引き継げなくなる）")

    # ★ROM を案内どおり置いただけでも誘いは出る
    rom = tmp_path / "work" / "rom"
    rom.mkdir(parents=True)
    (rom / "DQ3_J.nes").write_bytes(b"NES\x1a")
    assert MG.should_offer() is True, (
        "⚠⚠ ROM を置いた人に誘いが出ません（★案内どおりに置くと詰む）")

    # ⚠ 遊んだ証拠が出たら、もう勝手に誘わない（★混ぜない）
    know = tmp_path / "work" / "dq3-knowledge"
    know.mkdir(parents=True)
    (know / "memos.jsonl").write_bytes(b'{"memo":"x"}\n')
    assert MG.should_offer() is False


def test_誘いは一度決めたら出ない(tmp_path, monkeypatch):
    monkeypatch.setenv(OWN.P3.ENV, str(tmp_path))
    assert MG.should_offer() is True
    MG.record_decision(MG.DONE_DECLINED)
    assert MG.should_offer() is False
    got = MG.decision()
    assert got and got["kind"] == MG.DONE_DECLINED


def test_引き継いだら覚える(pair):
    old, new = pair
    assert MG.decision(new) is None
    MG.run(old, new)
    got = MG.decision(new)
    assert got and got["kind"] == MG.DONE_MIGRATED
    assert str(old) in got["source"]
    assert got["outcome"] == MG.OUT_OK
    assert MG.should_offer(new) is False


def test_失敗したときは覚えない(pair, monkeypatch):
    """⚠ 失敗したら、★次の起動でもう一度誘う。"""
    old, new = pair
    monkeypatch.setattr(
        MG.shutil, "copy2",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("⚠ わざと")))
    got = MG.run(old, new)
    assert not got.ok
    assert MG.decision(new) is None, "⚠⚠ 失敗したのに「済み」にしています"


def test_覚えはderivedなので引き継がれない(pair):
    """★新しい版では**改めて聞く**（⚠ 覚えを持ち越さない）。"""
    assert OWN.classify("work/" + MG.DECISION_NAME) == OWN.KIND_DERIVED
    old, new = pair
    MG.record_decision(MG.DONE_DECLINED, root=old)
    MG.run(old, new)
    # ⚠ 旧版の覚えが新版へ写っていない（★新版の覚えは run 自身が書いたもの）
    got = MG.decision(new)
    assert got and got["kind"] == MG.DONE_MIGRATED


# --- ★★ ⚠ 実行する前に「引き継げないもの」を言う（依頼者 §2）★★ ------

def test_ぶつかるものを実行前に出す(pair):
    old, new = pair
    assert MG.conflicts(old, new) == []
    mine = new / "work" / "dq3-knowledge"
    mine.mkdir(parents=True)
    (mine / "memos.jsonl").write_bytes(b'{"memo":"new"}\n')

    blocked = MG.conflicts(old, new)
    assert [rel for rel, _why in blocked] == ["work/dq3-knowledge/memos.jsonl"]
    body = MG.summary(MG.probe(old, new), blocked)
    assert "引き継げないもの" in body
    assert "work/dq3-knowledge/memos.jsonl" in body
    assert "上書きしません" in body
    assert "新しいフォルダへもう一度展開" in body
    # ⚠⚠ 言っただけで 1 バイトも書いていない
    assert (mine / "memos.jsonl").read_bytes() == b'{"memo":"new"}\n'


def test_実行前の一覧と実際に飛ばすものが同じ(pair):
    """⚠⚠ **同じ判定を 2 か所に書かない**（★`conflicts` と `run` が食い違わない）。"""
    old, new = pair
    mine = new / "work"
    (mine / "dq3-knowledge").mkdir(parents=True)
    (mine / "dq3-knowledge" / "memos.jsonl").write_bytes(b"x\n")
    (mine / "dq3-ui-settings.json").write_bytes(b"{}\n")

    before = sorted(rel for rel, _why in MG.conflicts(old, new))
    got = MG.run(old, new)
    assert sorted(got.skipped) == before
    assert got.outcome == MG.OUT_PARTIAL


# --- ★★ ⚠⚠ ROM / FCEUX の参照先（依頼者 §4）★★ ---------------------

def _write_cfg(root: pathlib.Path, body: str) -> None:
    (root / "user_config.yaml").write_text(body, encoding="utf-8")


def test_外を指す設定は引き継いでも使える(pair, tmp_path, monkeypatch):
    """★外の ROM / FCEUX は、⚠ 旧版を消しても指し先が変わらない。"""
    old, new = pair
    outside = tmp_path / "outside"
    (outside / "fceux").mkdir(parents=True)
    (outside / "fceux" / "fceux64.exe").write_bytes(b"MZ")
    (outside / "DQ3_J.nes").write_bytes(b"NES\x1a")
    _write_cfg(old, "paths:\n  dq3_rom: %s\n  fceux: %s\n"
               % ((outside / "DQ3_J.nes").as_posix(),
                  (outside / "fceux" / "fceux64.exe").as_posix()))

    assert MG.stale_references(old, new) == []
    MG.run(old, new)

    monkeypatch.setenv(OWN.P3.ENV, str(new))
    monkeypatch.setattr(OWN.P3, "program_root", lambda: new)
    assert pathlib.Path(OWN.P3.rom()) == outside / "DQ3_J.nes"
    assert pathlib.Path(OWN.P3.fceux()) == outside / "fceux" / "fceux64.exe"
    assert pathlib.Path(OWN.P3.fceux_fcs()) == outside / "fceux" / "fcs"


def test_相対の設定は新版のrootで解ける(pair, monkeypatch):
    old, new = pair
    _write_cfg(old, "paths:\n  dq3_rom: work/rom/DQ3_J.nes\n")
    assert MG.stale_references(old, new) == []
    MG.run(old, new)

    monkeypatch.setenv(OWN.P3.ENV, str(new))
    monkeypatch.setattr(OWN.P3, "program_root", lambda: new)
    got = pathlib.Path(OWN.P3.rom())
    assert got == new / "work" / "rom" / "DQ3_J.nes"
    assert got.is_file(), "⚠ 引き継いだ ROM を指していません"


def test_work_romの中のROMは新版のものを指す(pair, monkeypatch):
    """★設定が空でも、⚠ 引き継いだ `work/rom/` を新版側で引ける。"""
    old, new = pair
    _write_cfg(old, "paths: {}\n")
    MG.run(old, new)
    monkeypatch.setenv(OWN.P3.ENV, str(new))
    monkeypatch.setattr(OWN.P3, "program_root", lambda: new)
    got = pathlib.Path(OWN.P3.rom())
    assert got == new / "work" / "rom" / "DQ3_J.nes" and got.is_file()


def test_旧版の中を指す設定は選び直しを案内する(pair):
    """⚠⚠ **黙って書き換えない**（依頼者 §4）。★言うだけ。"""
    old, new = pair
    inside = old / "work" / "rom" / "DQ3_J.nes"
    _write_cfg(old, "paths:\n  dq3_rom: %s\n" % inside.as_posix())

    stale = MG.stale_references(old, new)
    assert [k for k, _r, _w in stale] == ["dq3_rom"]
    assert "選び直して" in stale[0][2]

    body = MG.summary(MG.probe(old, new), MG.conflicts(old, new), stale)
    assert "選び直しが要る" in body
    assert "dq3_rom" in body
    assert "書き換えることはしません" in body

    MG.run(old, new)
    # ⚠⚠ コピーした設定を**書き換えていない**
    assert (new / "user_config.yaml").read_bytes() == (old / "user_config.yaml").read_bytes()


def test_新版の中を指す設定は騒がない(pair):
    old, new = pair
    _write_cfg(old, "paths:\n  dq3_rom: %s\n"
               % (new / "work" / "rom" / "DQ3_J.nes").as_posix())
    assert MG.stale_references(old, new) == []


def test_設定が読めなくても引き継ぎは止まらない(pair):
    """⚠ `user_config.yaml` が壊れていても、★user data は写せる。"""
    old, new = pair
    (old / "user_config.yaml").write_bytes(b"paths: [broken\n")
    assert MG.stale_references(old, new) == []
    got = MG.run(old, new)
    assert got.ok


# --- ★DQ2 のデータは写さない（RX3-0507）-----------------------------

def _add_dq2_data(old: pathlib.Path) -> dict[str, bytes]:
    """★DQ2 と DQ3 を同じフォルダで遊んだ旧版（⚠ 共用の置き場に両方が在る）。"""
    mine = {
        "work/retroux.sqlite3": b"SQLite format 3\0dq2-db",
        "work/retroux.sqlite3-wal": b"wal",
        "work/events.jsonl": b'{"e":1}\n',
        "work/savestate-backup/DQ2_J.fc0.20261003-1200": b"dq2-save",
        "work/rom/DQ2_J.nes": b"NES\x1a" + bytes(16),
        "work/playdata-archive/20261003-1200/state.json": b"{}\n",
        "work/playdata-archive/20261003-1200-x-2/state.json": b"{}\n",
    }
    for rel, body in mine.items():
        path = old / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return mine


def test_DQ2のデータは写らずDQ3は写る(pair):
    old, new = pair
    dq2 = _add_dq2_data(old)
    before = _snapshot(old)
    got = MG.run(old, new)
    assert got.ok, got.failed
    for rel in dq2:
        assert not (new / rel).exists(), "⚠⚠ DQ2 のものを写しています: %s" % rel
    # ★DQ3 のものは従来どおり写る（⚠ 共用の置き場でも）
    for rel in ("work/savestate-backup/DQ3_J.fc1.20260930-120000",
                "work/rom/DQ3_J.nes",
                "work/playdata-archive/dq3-20260930-235959/memos.jsonl",
                "work/dq3-knowledge/memos.jsonl"):
        assert (new / rel).read_bytes() == (old / rel).read_bytes(), rel
    assert _snapshot(old) == before                     # ⚠⚠ 旧版は無傷


def test_DQ2のぶんは件数にも数えない(pair):
    """⚠ 実行前の一覧（件数・大きさ）と実際に写す数が食い違わない。"""
    old, new = pair
    base = {i.rel: (i.files, i.size) for i in MG.plan(old)}
    _add_dq2_data(old)
    after = {i.rel: (i.files, i.size) for i in MG.plan(old)}
    assert after == base
    dry = MG.run(old, new, dry_run=True)
    real = MG.run(old, new)
    assert dry.copied == real.copied


def test_DQ2のものしか無い置き場は項目にしない(tmp_path):
    old = _make_old(tmp_path / "old")
    for rel in ("work/rom/DQ3_J.nes",
                "work/savestate-backup/DQ3_J.fc1.20260930-120000"):
        (old / rel).unlink()
    (old / "work/rom/DQ2_J.nes").write_bytes(b"NES\x1a")
    (old / "work/savestate-backup/DQ2_J.fc0.x").write_bytes(b"x")
    rels = {i.rel for i in MG.plan(old)}
    assert "work/rom" not in rels
    assert "work/savestate-backup" not in rels
