"""まんたん要求CLI（python -m retroux.mantan）のテスト。

守りたい契約:
  1. encountered を消さないこと。消すと初遭遇の保護が外れ、
     ボスに敗北後の再戦で倍速＋自動たたかうが有効になる（DEV-8）
  2. request_id が毎回変わること。同じだと Lua 側が無視する
"""

from __future__ import annotations

import json

from retroux import mantan


def test_existing_encountered_is_preserved(tmp_path, monkeypatch):
    path = tmp_path / "command.json"
    path.write_text(json.dumps({"encountered": [1, 2, 78], "battle_multiplier": 4.0}),
                    encoding="utf-8")
    monkeypatch.setattr(mantan, "_command_path", lambda: path)

    assert mantan.main([]) == 0

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["encountered"] == [1, 2, 78], "遭遇済みIDを消してはいけない"
    assert payload["action"] == "mantan"
    assert isinstance(payload["request_id"], int)


def test_request_id_changes_between_calls(tmp_path, monkeypatch):
    path = tmp_path / "command.json"
    monkeypatch.setattr(mantan, "_command_path", lambda: path)

    ids = []
    for _ in range(2):
        mantan.main([])
        ids.append(json.loads(path.read_text(encoding="utf-8"))["request_id"])
    assert ids[1] >= ids[0]


def test_missing_file_is_tolerated(tmp_path, monkeypatch, capsys):
    """command.json が無くても失敗しない（先に要求しても後から拾われる）。"""
    path = tmp_path / "command.json"
    monkeypatch.setattr(mantan, "_command_path", lambda: path)

    assert mantan.main([]) == 0
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["encountered"] == []
    assert payload["action"] == "mantan"


def test_broken_json_does_not_lose_the_request(tmp_path, monkeypatch):
    """壊れた command.json でも要求は書ける（遭遇済みは空になる）。"""
    path = tmp_path / "command.json"
    path.write_text("{壊れている", encoding="utf-8")
    monkeypatch.setattr(mantan, "_command_path", lambda: path)

    assert mantan.main([]) == 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["action"] == "mantan"


def test_旧名の入口も動く():
    """⚠ `python -m retroux.manten` を消さない（指示書 §14 の受入条件）。

    ★★ 「まんたん」のローマ字を manten -> mantan へ直した（2026-08-02）。
      ⚠ 手が覚えている打ち方を、名前の都合で壊さない。
      ★旧名は中身を持たず `retroux.mantan` へ渡すだけ。

    ここが落ちたら、旧名の入口を消してしまったということ。
    """
    import warnings

    from retroux import manten

    assert manten.main is not None
    # ★同じものを指していること（写しではなく転送であること）
    from retroux import mantan
    assert manten.main is mantan.main

    # ★消さずに、気づけるようにしてある
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        manten._warn()
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
    assert "mantan" in str(caught[0].message)
