"""Run a console program inside an invisible Windows pseudo console (ConPTY).

The child sees a real console (so prompts that use ReadConsole / _getch work),
but no window is ever shown: we read its output and write its input through
pipes. Requires Windows 10 1809+.
"""
from __future__ import annotations

import ctypes
import re
import subprocess
import threading
from ctypes import wintypes as wt

k32 = ctypes.WinDLL("kernel32", use_last_error=True)

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
INFINITE = 0xFFFFFFFF
WAIT_TIMEOUT = 0x102

HPCON = wt.HANDLE


class COORD(ctypes.Structure):
    _fields_ = [("X", wt.SHORT), ("Y", wt.SHORT)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR), ("lpTitle", wt.LPWSTR),
        ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE),
        ("hStdError", wt.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE), ("dwProcessId", wt.DWORD),
                ("dwThreadId", wt.DWORD)]


k32.CreatePipe.argtypes = [ctypes.POINTER(wt.HANDLE), ctypes.POINTER(wt.HANDLE), ctypes.c_void_p, wt.DWORD]
k32.CreatePseudoConsole.argtypes = [COORD, wt.HANDLE, wt.HANDLE, wt.DWORD, ctypes.POINTER(HPCON)]
k32.CreatePseudoConsole.restype = ctypes.c_long  # HRESULT
k32.ClosePseudoConsole.argtypes = [HPCON]
k32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_size_t)]
k32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                          ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
k32.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL, wt.DWORD,
                               ctypes.c_void_p, wt.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(PROCESS_INFORMATION)]
k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
k32.WaitForSingleObject.restype = wt.DWORD
k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
k32.CloseHandle.argtypes = [wt.HANDLE]

_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][0-9A-Za-z]|\x1b[=>78]")


def strip_vt(text: str) -> str:
    return _ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "")


class PtyProcess:
    """A child process attached to a hidden pseudo console."""

    def __init__(self, argv: list[str], on_output=None, cols: int = 200, rows: int = 50):
        self._on_output = on_output
        self._closed = False
        self._pc_closed = False

        in_read, in_write = wt.HANDLE(), wt.HANDLE()
        out_read, out_write = wt.HANDLE(), wt.HANDLE()
        if not k32.CreatePipe(ctypes.byref(in_read), ctypes.byref(in_write), None, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k32.CreatePipe(ctypes.byref(out_read), ctypes.byref(out_write), None, 0):
            raise ctypes.WinError(ctypes.get_last_error())

        self._hpc = HPCON()
        hr = k32.CreatePseudoConsole(COORD(cols, rows), in_read, out_write, 0, ctypes.byref(self._hpc))
        # the pseudo console owns duplicates now
        k32.CloseHandle(in_read)
        k32.CloseHandle(out_write)
        if hr != 0:
            raise OSError(f"CreatePseudoConsole failed: 0x{hr & 0xFFFFFFFF:08x}")
        self._in = in_write
        self._out = out_read

        size = ctypes.c_size_t()
        k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        self._attr_buf = ctypes.create_string_buffer(size.value)
        if not k32.InitializeProcThreadAttributeList(self._attr_buf, 1, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not k32.UpdateProcThreadAttribute(self._attr_buf, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                                             self._hpc, ctypes.sizeof(HPCON), None, None):
            raise ctypes.WinError(ctypes.get_last_error())

        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si.lpAttributeList = ctypes.cast(self._attr_buf, ctypes.c_void_p)
        # Don't let the child inherit our own (possibly redirected) std handles:
        # with null handles it falls back to the pseudo console.
        si.StartupInfo.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
        self._pi = PROCESS_INFORMATION()
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        if not k32.CreateProcessW(None, cmdline, None, None, False,
                                  EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT,
                                  None, None, ctypes.byref(si), ctypes.byref(self._pi)):
            err = ctypes.get_last_error()
            self._close_pc()
            raise ctypes.WinError(err)
        k32.CloseHandle(self._pi.hThread)

        self._reader = threading.Thread(target=self._read_loop, name="conpty-read", daemon=True)
        self._reader.start()

    # -- io
    def _read_loop(self):
        buf = ctypes.create_string_buffer(4096)
        n = wt.DWORD()
        while True:
            if not k32.ReadFile(self._out, buf, len(buf), ctypes.byref(n), None) or n.value == 0:
                break
            if self._on_output:
                try:
                    self._on_output(buf.raw[:n.value].decode("utf-8", errors="replace"))
                except Exception:  # pragma: no cover - never kill the pump
                    pass

    def write(self, text: str) -> None:
        data = text.encode("utf-8")
        n = wt.DWORD()
        k32.WriteFile(self._in, data, len(data), ctypes.byref(n), None)

    # -- lifetime
    def wait(self, timeout: float | None = None) -> int | None:
        ms = INFINITE if timeout is None else int(timeout * 1000)
        if k32.WaitForSingleObject(self._pi.hProcess, ms) == WAIT_TIMEOUT:
            return None
        code = wt.DWORD()
        k32.GetExitCodeProcess(self._pi.hProcess, ctypes.byref(code))
        return ctypes.c_int32(code.value).value

    def terminate(self) -> None:
        k32.TerminateProcess(self._pi.hProcess, 1)

    def _close_pc(self):
        if not self._pc_closed:
            self._pc_closed = True
            k32.ClosePseudoConsole(self._hpc)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_pc()             # also ends the reader (pipe breaks)
        self._reader.join(timeout=2) if threading.current_thread() is not self._reader else None
        for h in (self._in, self._out, self._pi.hProcess):
            k32.CloseHandle(h)
        k32.DeleteProcThreadAttributeList(self._attr_buf)
