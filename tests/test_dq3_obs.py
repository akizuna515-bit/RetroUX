"""OBS へ録画を頼む部品（RX3-0031 / 2026-09-01）。

## ⚠⚠ OBS が居なくても確かめられるところを、先に固める

★実機（OBS）が要るのは「本当に録画されたか」だけです。
⚠ frame の組み立て・認証の計算・**居ないときに落ちないこと**は、
ここで**全部確かめられます**。

⚠ 依頼者が外出中で OBS の設定（WebSocket サーバーの有効化）が
まだできないため、★先にここまでを固めておきます。
"""

from __future__ import annotations

import json
import socket
import threading

import pytest


# --- ★frame の組み立て ------------------------------------------------------


def test_clientのframeは必ずmaskされる():
    """⚠⚠ RFC6455: **client → server は mask 必須**（★しないと切られる）。"""
    from dq3.testing import obs

    got = obs.encode_frame(b"hello")
    assert got[0] == 0x81, "⚠ FIN + text になっていない"
    assert got[1] & 0x80, "⚠⚠ mask ビットが立っていない"
    assert (got[1] & 0x7F) == 5


def test_長さで書き方が変わる():
    """⚠ 126 / 65536 を境に、★長さの書き方が変わります。"""
    from dq3.testing import obs

    assert (obs.encode_frame(b"x" * 10)[1] & 0x7F) == 10
    assert (obs.encode_frame(b"x" * 200)[1] & 0x7F) == 126
    assert (obs.encode_frame(b"x" * 70000)[1] & 0x7F) == 127


def test_maskは毎回変わる():
    """⚠ 固定の mask を使わない（★RFC6455 は乱数を求めます）。"""
    from dq3.testing import obs

    keys = {obs.encode_frame(b"same")[2:6] for _ in range(8)}
    assert len(keys) > 1, "⚠⚠ mask が毎回同じ"


def test_組み立てたframeを読み返せる():
    """★往復（⚠ 自分の組み立てを、自分の読み手で戻せること）。"""
    from dq3.testing import obs

    for size in (0, 5, 200, 70000):
        payload = bytes(range(256)) * (size // 256) + b"x" * (size % 256)
        payload = payload[:size]
        raw = obs.encode_frame(payload)
        server, client = socket.socketpair()
        try:
            server.sendall(raw)
            opcode, got = obs.read_frame(client)
        finally:
            server.close()
            client.close()
        assert opcode == obs.OPC_TEXT
        assert got == payload, "⚠ %d バイトで戻らない" % size


def test_大きすぎるframeは読まない():
    """⚠⚠ 際限なく読むと、★壊れた相手で固まります。"""
    from dq3.testing import obs

    server, client = socket.socketpair()
    try:
        # ⚠ 長さだけ巨大に宣言する（★中身は送らない）
        server.sendall(bytes([0x81, 127]) + (obs.MAX_FRAME + 1).to_bytes(8, "big"))
        with pytest.raises(ConnectionError):
            obs.read_frame(client)
    finally:
        server.close()
        client.close()


# --- ★認証の計算 ------------------------------------------------------------


def test_認証文字列の作り方():
    """★`base64(sha256(base64(sha256(pass+salt)) + challenge))`。

    ⚠ 決まった答えを写せないので、★**性質**で見ます。
    """
    from dq3.testing import obs

    got = obs.auth_string("pw", "salt", "chal")
    assert len(got) == 44, "⚠ sha256 の base64 は 44 文字"
    # ★同じ入力なら同じ答え
    assert got == obs.auth_string("pw", "salt", "chal")
    # ⚠ どれか 1 つでも変われば答えも変わる
    assert got != obs.auth_string("pw2", "salt", "chal")
    assert got != obs.auth_string("pw", "salt2", "chal")
    assert got != obs.auth_string("pw", "salt", "chal2")


def test_設定ファイルからパスワードを読まない():
    """★★★ ⚠⚠ **認証情報を勝手に使わない** ★★★

    ⚠ OBS の `config.json` にはパスワードが入っていますが、
      ★ここからは**読みません**。⚠ 環境変数だけです。
    """
    from dq3.testing import obs

    src = (__import__("pathlib").Path(obs.__file__)).read_text(encoding="utf-8")
    assert "config.json" not in src, "⚠⚠ OBS の設定ファイルを読んでいる"
    assert "APPDATA" not in src
    assert obs.PASSWORD_ENV == "RETROUX_OBS_PASSWORD"


# --- ★★ 居ないときに落ちない（⚠ ここが本体）--------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_OBSが居なくても落ちない():
    """★★★ ⚠⚠ **録画の失敗で run を落とさない** ★★★

    ⚠ 依頼者は遊びながら使います。★OBS が起動していないだけで
      自動移動が止まるのは**受け入れられません**。
    """
    from dq3.testing import obs

    port = _free_port()          # ★誰も待っていない番号
    assert obs.available(port=port, timeout=0.3) is False
    ok, why = obs.talk("GetVersion", port=port, timeout=0.3)
    assert ok is False and "OBS" in why
    ok, why = obs.start_record(port=port, timeout=0.3)
    assert ok is False
    ok, why = obs.stop_record(port=port, timeout=0.3)
    assert ok is False


def test_相手が黙っていても待ち続けない():
    """⚠ つながるが何も返さない相手（★固まらないこと）。"""
    from dq3.testing import obs

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    held = []

    def accept_and_hold():
        try:
            conn, _ = listener.accept()
            held.append(conn)          # ⚠ 何も返さずに握ったまま
        except OSError:
            pass

    thread = threading.Thread(target=accept_and_hold, daemon=True)
    thread.start()
    try:
        ok, why = obs.talk("GetVersion", port=port, timeout=0.5)
        assert ok is False, "⚠⚠ 黙っている相手を成功にした"
    finally:
        for conn in held:
            conn.close()
        listener.close()


def test_二重に録画を始めない(monkeypatch):
    """⚠ すでに録画中なら、★始めずに理由を返す。"""
    from dq3.testing import obs

    monkeypatch.setattr(obs, "talk",
                        lambda kind, data=None, **o:
                        (True, {"outputActive": True})
                        if kind == "GetRecordStatus" else (True, {}))
    ok, why = obs.start_record()
    assert ok is False and "すでに録画中" in why


def test_止めると出力先が返る(monkeypatch):
    from dq3.testing import obs

    monkeypatch.setattr(obs, "talk",
                        lambda kind, data=None, **o:
                        (True, {"outputPath": "C:/videos/run.mkv"}))
    ok, path = obs.stop_record()
    assert ok is True and path.endswith("run.mkv")


# --- ★★ 偽の OBS で手順そのものを通す（⚠ 足場だけで緑にしない）------------


@pytest.mark.parametrize("glued", [True, False])
@pytest.mark.parametrize("auth", [False, True])
def test_偽のOBSと最後まで話せる(glued, auth):
    """★★★ ⚠⚠ **HTTP の応答と最初の frame がくっついて来る形** ★★★

    ⚠ 2026-09-01 に、ヘッダを読むとき**最初の frame の先頭まで飲み込み**、
      `Expecting value: line 1 column 1` で落ちました。
      ★偽サーバで再現して直しました。⚠ `glued=True` がその形です。
    """
    import fake_obs

    ok, got = fake_obs.run(auth=auth, glued=glued)
    assert ok is True, "⚠⚠ くっついて来る=%s 認証=%s で話せない: %s" % (
        glued, auth, got)
    assert got.get("obsVersion")


def test_認証を求められて鍵が無ければ理由を返す():
    """⚠ 黙って失敗しない（★何をすればよいか書く）。"""
    import fake_obs

    ok, why = fake_obs.run(auth=True, glued=True, password="")
    assert ok is False
    assert "RETROUX_OBS_PASSWORD" in why, why
