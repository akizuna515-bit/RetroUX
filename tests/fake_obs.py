"""偽の obs-websocket（RX3-0031 / 2026-09-01）。

★OBS を起動せずに、⚠ **やり取りの手順そのもの**を確かめるための足場です。

## ⚠⚠ ここで再現する「本番と同じ形」

  ★HTTP の応答と最初の frame が **1 つの塊で届く**ことがあります。
  ⚠ 2026-09-01 に、ヘッダを読むとき**最初の frame の先頭まで飲み込み**、
    `Expecting value: line 1 column 1` で落ちました。
  → ★`glued=True` がその形です（⚠ 消さないこと）。
"""
import base64
import hashlib
import json
import socket
import sys
import threading

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
from dq3.testing import obs

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def send_unmasked(conn, obj):
    """server → client は mask しない。"""
    p = json.dumps(obj).encode("utf-8")
    if len(p) < 126:
        conn.sendall(bytes([0x81, len(p)]) + p)
    else:
        conn.sendall(bytes([0x81, 126]) + len(p).to_bytes(2, "big") + p)


def serve(listener, auth, password, glued):
    conn, _ = listener.accept()
    head = b""
    while b"\r\n\r\n" not in head:
        head += conn.recv(1024)
    key = ""
    for line in head.decode("latin1").split("\r\n"):
        if line.lower().startswith("sec-websocket-key:"):
            key = line.split(":", 1)[1].strip()
    accept = base64.b64encode(
        hashlib.sha1((key + GUID).encode()).digest()).decode()
    resp = ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode()

    hello = {"op": 0, "d": {"rpcVersion": 1}}
    if auth:
        hello["d"]["authentication"] = {"salt": "S", "challenge": "C"}
    body = json.dumps(hello).encode("utf-8")
    frame = bytes([0x81, len(body)]) + body

    if glued:
        # ⚠⚠ ここが本番と同じ形: HTTP の応答と最初の frame が**1 つの塊**で来る
        conn.sendall(resp + frame)
    else:
        conn.sendall(resp)
        conn.sendall(frame)

    try:
        _, ident = obs.read_frame(conn)
    except (ConnectionError, OSError):
        conn.close()          # ⚠ client が鍵を持たずに諦めた（★正しい姿）
        return
    got = json.loads(ident)
    if auth:
        want = obs.auth_string(password, "S", "C")
        assert got["d"]["authentication"] == want, "認証文字列が違う"
    send_unmasked(conn, {"op": 2, "d": {"negotiatedRpcVersion": 1}})

    _, req = obs.read_frame(conn)
    d = json.loads(req)["d"]
    send_unmasked(conn, {"op": 7, "d": {
        "requestType": d["requestType"], "requestId": d["requestId"],
        "requestStatus": {"result": True, "code": 100},
        "responseData": {"obsVersion": "32.2.2", "outputActive": False}}})
    conn.close()


def run(auth, glued, password="pw"):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    thread = threading.Thread(target=serve,
                              args=(listener, auth, "pw", glued))
    thread.daemon = True
    thread.start()
    kw = {"port": port, "timeout": 3.0}
    if auth:
        kw["password"] = password
    ok, got = obs.talk("GetVersion", **kw)
    thread.join(timeout=3)
    listener.close()
    return ok, got
