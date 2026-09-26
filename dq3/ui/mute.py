"""FCEUX の音だけを消す（RX3-0104 / 2026-09-07）。

## ⚠⚠ FCEUX には「消音」のメニューがありません

★速度は `WM_COMMAND` で変えられます（`emu_speed.py`）。⚠ 音は違いました。
同梱の `fceux64.exe` のメニュー資源を実際に読むと、⚠ **Mute の項目がありません**。

```text
★あるもの   Emulation Speed > Normal Speed / Speed Up / Slow Down / Turbo …
⚠ 無いもの   Mute / Volume（★Config > Sound... は**ダイアログ**で、押しても開くだけ）
⚠ cfg の "sound" 1 は起動時の設定（★変えても再起動しないと効かない）
⚠ Lua の `sound` は `sound.get()` だけ（★setter は無い）
```

★そこで **Windows 側**で消します（⚠ FCEUX の協力が要りません）。

```text
Core Audio のセッション（プロセスごとの音量）→ ISimpleAudioVolume.SetMute
```

## ★この方法を選んだ理由

```text
★FCEUX だけが黙る       （⚠ 他のアプリの音は消さない）
★元の状態へ正確に戻せる （★開始前の Mute を読んでから変える）
★最小化していても効く   （⚠ 速度制御と同じ条件）
★同梱物を差し替えない   （⚠ tools/ は書き込み禁止）
```

## ⚠ 消せなくても、処理は止めません

★音は「あると邪魔」なだけで、⚠ **聞き込みの正しさには関わりません**。
→ ★失敗は `last_error` に残して先へ進みます（⚠ 例外にしない）。

## ⚠ 検査は偽の backend で行います

★COM は環境に依存します。⚠ `backend` を差し替えられるようにして、
検査では**本物の音を触りません**。
"""
from __future__ import annotations

import atexit
import sys

#: ★Core Audio の GUID（⚠ 手で書き写す値なので、まとめてここに置く）
_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_IAudioSessionManager2 = "{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}"
_IID_IAudioSessionEnumerator = "{E2F5BB11-0570-40CA-ACDD-3AA01277DEE8}"
_IID_IAudioSessionControl2 = "{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}"
_IID_ISimpleAudioVolume = "{87CE5498-68D6-44E5-9215-6DA47EF883D8}"

#: ★eRender（出す側）/ eMultimedia
_E_RENDER, _E_MULTIMEDIA = 0, 1
_CLSCTX_ALL = 0x17
_COINIT_APARTMENTTHREADED = 0x2

#: ★vtable の並び（⚠ 数え間違えると**別の関数**を呼びます。順番は MSDN のとおり）
_VT_QUERY_INTERFACE, _VT_RELEASE = 0, 2
_VT_ENUM_GET_DEFAULT_ENDPOINT = 4          # IMMDeviceEnumerator
_VT_DEVICE_ACTIVATE = 3                    # IMMDevice
_VT_MGR_GET_SESSION_ENUMERATOR = 5         # IAudioSessionManager2
_VT_SESSIONS_GET_COUNT, _VT_SESSIONS_GET = 3, 4
_VT_CTL2_GET_PROCESS_ID = 14               # IAudioSessionControl2
_VT_VOL_SET_MUTE, _VT_VOL_GET_MUTE = 5, 6  # ISimpleAudioVolume


class WindowsAudioBackend:
    """★Core Audio を ctypes で叩く（⚠ Windows 以外では何もしない）。"""

    available = sys.platform == "win32"

    def __init__(self) -> None:
        self.last_error: str | None = None

    # ------------------------------------------------------------------
    # ★COM の下ごしらえ（⚠ 生ポインタを扱うので、release を必ず通す）
    # ------------------------------------------------------------------
    @staticmethod
    def _guid(text: str):
        import ctypes
        import ctypes.wintypes as wt

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD),
                        ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

        got = GUID()
        ole32 = ctypes.WinDLL("ole32")
        if ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(got)) != 0:
            raise OSError("⚠ GUID を読めません: %s" % text)
        return got

    @staticmethod
    def _call(ptr, index, argtypes=(), *args):
        """★`ptr` の vtable の `index` 番を呼ぶ（⚠ 戻り値は HRESULT）。

        ⚠⚠ `argtypes` は**呼ぶ側が明示**します。★`byref()` の戻り（`CArgObject`）は
        型を推測できず、⚠ 推測させると `item N in _argtypes_ has no from_param method`
        で静かに全部失敗します（★2026-09-07 に実際に踏んだ）。
        """
        import ctypes

        vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p)).contents.value
        entry = ctypes.cast(vtbl + index * ctypes.sizeof(ctypes.c_void_p),
                            ctypes.POINTER(ctypes.c_void_p)).contents.value
        proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
        return proto(entry)(ptr, *args)

    @classmethod
    def _release(cls, ptr) -> None:
        if ptr:
            try:
                cls._call(ptr, _VT_RELEASE)
            except Exception:                                # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # ★プロセスの音（⚠ 見つからなければ None を返す。**推測しない**）
    # ------------------------------------------------------------------
    def _volumes_of(self, pid: int, sink):
        """`pid` のセッションの `ISimpleAudioVolume` を `sink` へ渡す。"""
        import ctypes

        p_void = ctypes.POINTER(ctypes.c_void_p)
        p_int = ctypes.POINTER(ctypes.c_int)
        p_uint = ctypes.POINTER(ctypes.c_uint)
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        enumerator = device = manager = sessions = None
        try:
            enumerator = ctypes.c_void_p()
            hr = ole32.CoCreateInstance(
                ctypes.byref(self._guid(_CLSID_MMDeviceEnumerator)), None, _CLSCTX_ALL,
                ctypes.byref(self._guid(_IID_IMMDeviceEnumerator)), ctypes.byref(enumerator))
            if hr != 0:
                raise OSError("⚠ MMDeviceEnumerator を作れません（0x%08X）" % (hr & 0xFFFFFFFF))
            device = ctypes.c_void_p()
            hr = self._call(enumerator, _VT_ENUM_GET_DEFAULT_ENDPOINT,
                            (ctypes.c_int, ctypes.c_int, p_void),
                            _E_RENDER, _E_MULTIMEDIA, ctypes.byref(device))
            if hr != 0:
                raise OSError("⚠ 既定の出力先がありません（0x%08X）" % (hr & 0xFFFFFFFF))
            manager = ctypes.c_void_p()
            iid_mgr = self._guid(_IID_IAudioSessionManager2)
            hr = self._call(device, _VT_DEVICE_ACTIVATE,
                            (ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, p_void),
                            ctypes.addressof(iid_mgr), _CLSCTX_ALL, None, ctypes.byref(manager))
            if hr != 0:
                raise OSError("⚠ セッション管理を取れません（0x%08X）" % (hr & 0xFFFFFFFF))
            sessions = ctypes.c_void_p()
            hr = self._call(manager, _VT_MGR_GET_SESSION_ENUMERATOR,
                            (p_void,), ctypes.byref(sessions))
            if hr != 0:
                raise OSError("⚠ セッション一覧を取れません（0x%08X）" % (hr & 0xFFFFFFFF))
            count = ctypes.c_int()
            self._call(sessions, _VT_SESSIONS_GET_COUNT, (p_int,), ctypes.byref(count))
            iid_ctl2 = self._guid(_IID_IAudioSessionControl2)
            iid_vol = self._guid(_IID_ISimpleAudioVolume)
            for i in range(count.value):
                control = ctypes.c_void_p()
                if self._call(sessions, _VT_SESSIONS_GET, (ctypes.c_int, p_void),
                              i, ctypes.byref(control)) != 0:
                    continue
                control2 = volume = None
                try:
                    control2 = ctypes.c_void_p()
                    if self._call(control, _VT_QUERY_INTERFACE, (ctypes.c_void_p, p_void),
                                  ctypes.addressof(iid_ctl2), ctypes.byref(control2)) != 0:
                        continue
                    got = ctypes.c_uint()
                    if self._call(control2, _VT_CTL2_GET_PROCESS_ID,
                                  (p_uint,), ctypes.byref(got)) != 0:
                        continue
                    if got.value != pid:
                        continue
                    volume = ctypes.c_void_p()
                    if self._call(control, _VT_QUERY_INTERFACE, (ctypes.c_void_p, p_void),
                                  ctypes.addressof(iid_vol), ctypes.byref(volume)) != 0:
                        continue
                    sink(volume)
                finally:
                    self._release(volume)
                    self._release(control2)
                    self._release(control)
        finally:
            for ptr in (sessions, manager, device, enumerator):
                self._release(ptr)
            ole32.CoUninitialize()

    def get_mute(self, pid: int):
        """★いま消音か。⚠ 分からなければ `None`（★False と混ぜない）。"""
        if not self.available:
            self.last_error = "⚠ Windows ではありません"
            return None
        import ctypes

        answers: list[bool] = []

        def sink(volume):
            got = ctypes.c_int()
            if self._call(volume, _VT_VOL_GET_MUTE,
                          (ctypes.POINTER(ctypes.c_int),), ctypes.byref(got)) == 0:
                answers.append(bool(got.value))

        try:
            self._volumes_of(pid, sink)
        except Exception as err:                             # noqa: BLE001
            self.last_error = "⚠ 音の状態を読めません: %s" % err
            return None
        if not answers:
            self.last_error = "⚠ FCEUX の音のセッションがありません（★まだ音を出していない）"
            return None
        self.last_error = None
        return any(answers)

    def set_mute(self, pid: int, on: bool) -> bool:
        if not self.available:
            self.last_error = "⚠ Windows ではありません"
            return False
        import ctypes

        done = []

        def sink(volume):
            if self._call(volume, _VT_VOL_SET_MUTE,
                          (ctypes.c_int, ctypes.c_void_p),
                          1 if on else 0, None) == 0:
                done.append(True)

        try:
            self._volumes_of(pid, sink)
        except Exception as err:                             # noqa: BLE001
            self.last_error = "⚠ 音を変えられません: %s" % err
            return False
        if not done:
            self.last_error = "⚠ FCEUX の音のセッションがありません（★まだ音を出していない）"
            return False
        self.last_error = None
        return True


def fceux_pid(finder=None) -> int:
    """★FCEUX の窓からプロセス番号（⚠ 見つからなければ 0）。"""
    if sys.platform != "win32":
        return 0
    import ctypes
    import ctypes.wintypes as wt

    from .emu_speed import find_fceux

    hwnd = (finder or find_fceux)()
    if not hwnd:
        return 0
    pid = wt.DWORD()
    ctypes.WinDLL("user32").GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


class MuteController:
    """★FCEUX の音を消す / 戻す。⚠ 失敗しても例外にしません。"""

    def __init__(self, backend=None, pid_finder=None) -> None:
        self.backend = backend if backend is not None else WindowsAudioBackend()
        self._pid = pid_finder or fceux_pid
        #: ★こちらが消したか（⚠ **人が自分で消していた**なら触らない印にする）
        self.changed = False
        self.last_error: str | None = None
        atexit.register(self._atexit)

    def available(self) -> bool:
        return bool(getattr(self.backend, "available", True)) and bool(self._pid())

    def get(self):
        """★いまの消音の状態（⚠ 分からなければ `None`）。"""
        pid = self._pid()
        if not pid:
            self.last_error = "⚠ FCEUX が見つかりません"
            return None
        got = self.backend.get_mute(pid)
        self.last_error = getattr(self.backend, "last_error", None)
        return got

    def set(self, on: bool) -> bool:
        pid = self._pid()
        if not pid:
            self.last_error = "⚠ FCEUX が見つかりません"
            return False
        ok = bool(self.backend.set_mute(pid, bool(on)))
        self.last_error = getattr(self.backend, "last_error", None)
        if ok:
            self.changed = bool(on)
        return ok

    def _atexit(self) -> None:
        # ⚠⚠ 消したまま終わらない（★次に遊ぶ人には原因が分かりません）
        if self.changed:
            try:
                self.set(False)
            except Exception:                                # noqa: BLE001
                pass


__all__ = ["MuteController", "WindowsAudioBackend", "fceux_pid"]
