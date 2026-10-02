"""⚠⚠ `rom_names` の memo が、**他の検査の ROM 指定**で汚れないこと（RX3-0474）。

```text
⚠ 何が起きていたか
  ある検査が `rom_path=<無い ROM>` を渡して呼ぶ
        ↓
  ★module の memo に「読めなかった」が入る（⚠ 明示の path なのに共有の欄へ）
        ↓
  同じ worker の**あとの検査**が素で呼ぶ → ⚠ 読めるのに空が返る → skip
```

★これで全件の skip 件数が 47 ⇄ 51 で揺れていました（⚠ 走行ごとに worker の
組み合わせが変わるため）。★詳しくは `docs/12-work-items-dq3.md` の `RX3-0474`。
"""
from __future__ import annotations

import pytest

from dq3.knowledge import rom_names as RN


@pytest.fixture(autouse=True)
def _memoを持ち越さない():
    """⚠ この検査自身が次の検査を汚さないこと（★前後で戻す）。"""
    RN.reset()
    yield
    RN.reset()


def _素で読める() -> bool:
    RN.reset()
    return bool(RN.place_maps()) and RN.available()


def test_無いROMを名指しした後も素では読める(tmp_path):
    """⚠⚠ これが 47 ⇄ 51 の正体（★`place_maps`）。"""
    if not _素で読める():
        pytest.skip("ROM が読めません（★この環境では確かめられない）")
    missing = tmp_path / "ない.nes"

    RN.reset()
    assert RN.place_maps(missing) == [], "⚠ 無い ROM から読めている（★検査の前提が崩れた）"
    assert len(RN.place_maps()) == 20, "⚠⚠ 明示の rom_path が共有 memo を汚した"


def test_無いROMを名指しした後も名前辞書は読める(tmp_path):
    """⚠ `_load` も同じ形（★`place_maps` だけ直しても半分残る）。"""
    if not _素で読める():
        pytest.skip("ROM が読めません（★この環境では確かめられない）")
    missing = tmp_path / "ない.nes"

    RN.reset()
    assert RN.available(missing) is False, "⚠ 無い ROM で読めている"
    assert RN.available() is True, "⚠⚠ 明示の rom_path が名前辞書の memo を汚した"


def test_壊れたROMを名指しした後も素では読める(tmp_path):
    """★「無い」ではなく「読めない」でも同じこと（⚠ 例外の側の道）。"""
    if not _素で読める():
        pytest.skip("ROM が読めません（★この環境では確かめられない）")
    broken = tmp_path / "こわれている.nes"
    broken.write_bytes(b"NOT A ROM" * 64)

    RN.reset()
    assert RN.place_maps(broken) == []
    assert len(RN.place_maps()) == 20, "⚠⚠ 壊れた ROM の失敗が共有 memo に残った"


def test_素で読んだ後に無いROMを名指ししても素の値は残る(tmp_path):
    """⚠ 逆順（★先に温めた memo を、あとの名指しが壊さないこと）。"""
    if not _素で読める():
        pytest.skip("ROM が読めません（★この環境では確かめられない）")
    RN.reset()
    want = len(RN.place_maps())
    assert RN.place_maps(tmp_path / "ない.nes") == []
    assert len(RN.place_maps()) == want, "⚠⚠ 温めた memo を名指しが上書きした"


def test_汚した検査と同じ形を並べても後続が読める(tmp_path):
    """★`tests/test_dq3_place_readings.py` が実際にやっていた形（⚠ 再発の歯止め）。

    ⚠ あちらは `reachable.collect(..., rom_path=<無い ROM>)` 経由で呼んでいて、
      ★`rom_names` を直に触っていません。だから「使う側を直す」では足りません。
    """
    if not _素で読める():
        pytest.skip("ROM が読めません（★この環境では確かめられない）")
    from dq3.knowledge import reachable as RE

    RN.reset()
    RE.collect(None, None, None, conversations={}, rom_path=tmp_path / "ない.nes")
    assert len(RE.rura_towns()) == 20, "⚠⚠ collect の rom_path が後続を読めなくした"
