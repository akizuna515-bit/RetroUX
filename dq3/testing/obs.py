"""OBS へ「録画を始めて／止めて」と頼む（RX3-0031 / 2026-09-01）。

## ⚠⚠ なぜ FCEUX の AVI ではないのか

依頼者 2026-09-01:

> 周辺の RetroUX 画面も表示したいので、その場合は OBS の方が良くない？

★そのとおりでした。⚠ FCEUX の AVI は**エミュレータの映像だけ**で、
周りの RetroUX の窓（地図・帯・図鑑・ログ）は **1 ピクセルも入りません**。
→ ★証跡の目的が「RetroUX を使っている様子」なら、⚠ AVI では届きません。

## ★依存を増やしません

⚠ `obsws-python` などは入れません。★obs-websocket v5 は

```text
WebSocket（RFC6455）＋ JSON ＋ SHA256
```

だけなので、**標準ライブラリで話せます**（`pyproject.toml` を汚さない）。

## ⚠⚠ 録画は「無くても run は成立する」

```text
★OBS が居ない        → 証跡に「動画なし」と書いて先へ進む
★録画に失敗した      → 理由を残して先へ進む
⚠⚠ してはいけない   録画の失敗で run を落とす（★遊びも止めない）
```

⚠ そのため、この module は**例外を投げません**。★`(ok, 理由)` を返します。

## ★使い方

    from dq3.testing import obs

    ok, why = obs.start_record()
    ...
    ok, path = obs.stop_record()      # ★止めると出力先が返る

⚠ 認証が有効なら、環境変数 `RETROUX_OBS_PASSWORD` から読みます。
⚠⚠ **OBS の設定ファイルからは読みません**（★認証情報を勝手に使わない）。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import struct

#: ★既定の宛先（⚠ obs-websocket v5 の既定）
HOST, PORT = "127.0.0.1", 4455

#: ⚠ 待ち時間（★OBS が居ないときに長く止まらない）
TIMEOUT = 3.0

#: ★環境変数から読む（⚠ 設定ファイルは読まない）
PASSWORD_ENV = "RETROUX_OBS_PASSWORD"

#: ★obs-websocket v5 の op 番号
OP_HELLO, OP_IDENTIFY, OP_IDENTIFIED = 0, 1, 2
OP_REQUEST, OP_RESPONSE = 6, 7

#: ★RFC6455 の opcode
OPC_TEXT, OPC_CLOSE, OPC_PING, OPC_PONG = 0x1, 0x8, 0x9, 0xA

#: ⚠ 大きな frame は来ない想定（★来たら読まずに諦める）
MAX_FRAME = 1 << 20


def auth_string(password: str, salt: str, challenge: str) -> str:
    """★obs-websocket v5 の認証文字列。

    ```text
    secret = base64(sha256(password + salt))
    auth   = base64(sha256(secret + challenge))
    ```

    ⚠ 認証を無効にしているなら呼ばれません。
    """
    secret = base64.b64encode(
        hashlib.sha256((password + salt).encode("utf-8")).digest()).decode()
    return base64.b64encode(
        hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode()


def encode_frame(payload: bytes, opcode: int = OPC_TEXT) -> bytes:
    """★client → server の frame（⚠ client は**必ず mask する**）。"""
    head = bytes([0x80 | opcode])
    size = len(payload)
    if size < 126:
        head += bytes([0x80 | size])
    elif size < (1 << 16):
        head += bytes([0x80 | 126]) + struct.pack(">H", size)
    else:
        head += bytes([0x80 | 127]) + struct.pack(">Q", size)
    mask = secrets.token_bytes(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return head + mask + masked


def _read_exact_sock(sock, n: int) -> bytes:
    """⚠ n バイト読み切る（★足りなければ例外）。"""
    got = b""
    while len(got) < n:
        chunk = sock.recv(n - len(got))
        if not chunk:
            raise ConnectionError("⚠ 途中で切れました")
        got += chunk
    return got


def read_frame(sock=None, *, read_exact=None):
    """★server → client の frame を 1 つ読む。⚠ `(opcode, payload)`。

    @param read_exact ⚠ 読み手を差し替える（★取っておいたバイトを先に使う）
    """
    _read_exact = read_exact or (lambda n: _read_exact_sock(sock, n))
    b0, b1 = _read_exact(2)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    size = b1 & 0x7F
    if size == 126:
        size = struct.unpack(">H", _read_exact(2))[0]
    elif size == 127:
        size = struct.unpack(">Q", _read_exact(8))[0]
    if size > MAX_FRAME:
        raise ConnectionError("⚠ frame が大きすぎます: %d" % size)
    mask = _read_exact(4) if masked else None
    payload = _read_exact(size) if size else b""
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


class Obs:
    """★OBS との 1 回のやり取り（⚠ `with` で閉じる）。"""

    def __init__(self, host: str = HOST, port: int = PORT,
                 timeout: float = TIMEOUT, password: str | None = None):
        self.host, self.port, self.timeout = host, port, timeout
        self.password = password if password is not None else os.environ.get(
            PASSWORD_ENV, "")
        self.sock = None
        self._id = 0
        # ⚠⚠ HTTP のヘッダを読むとき、★**最初の frame の先頭まで**
        #   一緒に読んでしまいます（2026-09-01 に偽サーバで発覚）。
        #   → ★余った分をここへ取っておき、次の読みで先に使います。
        self._spare = b""

    # --- ★つなぐ ---------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def connect(self) -> None:
        """⚠ 失敗すれば例外（★呼ぶ側は `talk()` を使ってください）。"""
        self.sock = socket.create_connection((self.host, self.port),
                                             timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        req = (
            "GET / HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n" % (self.host, self.port, key)
        )
        self.sock.sendall(req.encode("ascii"))
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.sock.recv(1024)
            if len(head) > 8192:
                raise ConnectionError("⚠ 応答が長すぎます")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("⚠ WebSocket になりませんでした")
        # ★★ ヘッダの後ろに付いてきた分を取っておく（2026-09-01 に偽サーバで発覚）
        #   ⚠⚠ 捨てると **最初の返事（Hello）の先頭を失い**、
        #     「Expecting value: line 1 column 1」で落ちます。
        self._spare = head.split(b"\r\n\r\n", 1)[1]
        self._identify()

    def _read_exact(self, n: int) -> bytes:
        """★取っておいたバイトを先に使う（⚠ 足りなければ socket から）。"""
        if self._spare:
            take = self._spare[:n]
            self._spare = self._spare[len(take):]
            if len(take) == n:
                return take
            return take + _read_exact_sock(self.sock, n - len(take))
        return _read_exact_sock(self.sock, n)

    def _identify(self) -> None:
        _, payload = self._recv_json()
        hello = payload.get("d", {})
        msg = {"op": OP_IDENTIFY, "d": {"rpcVersion": hello.get("rpcVersion", 1)}}
        auth = hello.get("authentication")
        if auth:
            if not self.password:
                raise ConnectionError(
                    "⚠⚠ OBS が認証を求めています。★環境変数 %s を設定するか、"
                    "OBS 側で認証を切ってください" % PASSWORD_ENV)
            msg["d"]["authentication"] = auth_string(
                self.password, auth.get("salt", ""), auth.get("challenge", ""))
        self._send_json(msg)
        _, got = self._recv_json()
        if got.get("op") != OP_IDENTIFIED:
            raise ConnectionError("⚠ 名乗りが通りませんでした: %s" % got)

    def close(self) -> None:
        if self.sock is None:
            return
        try:
            self.sock.sendall(encode_frame(b"", OPC_CLOSE))
        except OSError:
            pass                                    # ⚠ 閉じる途中の失敗は無視
        try:
            self.sock.close()
        finally:
            self.sock = None

    # --- ★やり取り -------------------------------------------------------

    def _send_json(self, obj) -> None:
        self.sock.sendall(encode_frame(json.dumps(obj).encode("utf-8")))

    def _recv_json(self):
        while True:
            opcode, payload = read_frame(read_exact=self._read_exact)
            if opcode == OPC_PING:
                self.sock.sendall(encode_frame(payload, OPC_PONG))
                continue
            if opcode == OPC_CLOSE:
                raise ConnectionError("⚠ OBS が切りました")
            if opcode != OPC_TEXT:
                continue                            # ⚠ 知らない種類は読み飛ばす
            return opcode, json.loads(payload.decode("utf-8"))

    def request(self, kind: str, data: dict | None = None) -> dict:
        """★1 つ頼んで、返事を待つ。"""
        self._id += 1
        rid = "retroux-%d" % self._id
        self._send_json({"op": OP_REQUEST, "d": {
            "requestType": kind, "requestId": rid,
            "requestData": data or {}}})
        while True:
            _, got = self._recv_json()
            if got.get("op") != OP_RESPONSE:
                continue                            # ⚠ 途中の通知は読み飛ばす
            body = got.get("d", {})
            if body.get("requestId") != rid:
                continue
            return body


def talk(kind: str, data: dict | None = None, **opts):
    """★1 回つないで 1 つ頼む。⚠ `(ok, 中身 or 理由)`。**例外は投げません**。"""
    try:
        with Obs(**opts) as obs:
            body = obs.request(kind, data)
    except (OSError, ConnectionError, ValueError) as err:
        return False, "⚠ OBS と話せません: %s" % err
    status = body.get("requestStatus", {})
    if not status.get("result"):
        return False, "⚠ OBS が断りました: %s" % (
            status.get("comment") or status.get("code"))
    return True, body.get("responseData") or {}


# --- ★よく使うもの ----------------------------------------------------------


def available(**opts) -> bool:
    """★OBS が居て、話せるか（⚠ 居なくても落ちません）。"""
    return talk("GetVersion", **opts)[0]


def record_status(**opts):
    """★いま録画中か。⚠ `(ok, {"active": bool, ...})`。"""
    return talk("GetRecordStatus", **opts)


def start_record(**opts):
    """★録画を始める。⚠ 既に録画中なら、そう返します（**二重に始めない**）。"""
    ok, got = record_status(**opts)
    if ok and got.get("outputActive"):
        return False, "⚠ すでに録画中です（★止めてから始めてください）"
    return talk("StartRecord", **opts)


def stop_record(**opts):
    """★録画を止める。⚠ 出力先の道が返ります。"""
    ok, got = talk("StopRecord", **opts)
    if not ok:
        return ok, got
    return True, got.get("outputPath") or ""
