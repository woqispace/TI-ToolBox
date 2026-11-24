#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TI 工具箱 - 桌面入口（pywebview + WebView2 宿主）。

窗口：无边框（frameless），最小化 / 最大化 / 关闭 / 拖动 / 边缘缩放 全部走页面按钮 + /api/win。
这里只负责：起本地服务、开窗口、补窗口样式位（WS_THICKFRAME / MINBOX / MAXBOX / SYSMENU）。
"""
from __future__ import annotations
import json
import os

import ctypes
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    HERE = Path(sys.executable).resolve().parent
sys.path.insert(0, str(HERE))

import webview  # noqa: E402

import app as backend  # noqa: E402

TITLE = "TI工具箱"
W, H = 1346, 862

user32 = ctypes.windll.user32 if sys.platform == "win32" else None

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0004, 0x0010
SWP_FRAMECHANGED = 0x0020

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def _hwnd() -> int:
    """按「本进程 + 可见 + 面积最大」取主窗口句柄。"""
    if not user32:
        return 0
    pid = ctypes.windll.kernel32.GetCurrentProcessId()
    best, best_area = 0, -1

    def _cb(hwnd, _lp):
        nonlocal best, best_area
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(wpid))
        if wpid.value != pid or not user32.IsWindowVisible(wintypes.HWND(hwnd)):
            return True
        rc = wintypes.RECT()
        user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rc))
        w, h = rc.right - rc.left, rc.bottom - rc.top
        if w < 600 or h < 400:            # 跳过隐藏的辅助窗口 / 1px 影子窗
            return True
        if rc.left <= -30000 or rc.top <= -30000:
            return True
        area = w * h
        if area > best_area:
            best, best_area = int(hwnd), area
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return best


def _style_win32(hwnd: int) -> dict:
    """补缩放/最小化/最大化/系统菜单位，去 TOOLWINDOW、加 APPWINDOW。"""
    h = wintypes.HWND(hwnd)
    st = user32.GetWindowLongPtrW(h, GWL_STYLE)
    ex = user32.GetWindowLongPtrW(h, GWL_EXSTYLE)
    want = st | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
    want_ex = (ex & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
    user32.SetWindowLongPtrW(h, GWL_STYLE, want)
    user32.SetWindowLongPtrW(h, GWL_EXSTYLE, want_ex)
    user32.SetWindowPos(h, None, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    return {"style": hex(want & 0xFFFFFFFF), "ex": hex(want_ex & 0xFFFFFFFF)}


WS_CAPTION = 0x00C00000
WM_NCCALCSIZE, WM_NCACTIVATE = 0x0083, 0x0086

comctl32 = ctypes.windll.comctl32
gdi32 = ctypes.windll.gdi32
dwmapi = ctypes.windll.dwmapi


class _MARGINS(ctypes.Structure):
    _fields_ = [("cl", ctypes.c_int), ("cr", ctypes.c_int),
                ("ct", ctypes.c_int), ("cb", ctypes.c_int)]


_SUBCLASS_PROC = None
_SUBCLASSED = set()


def _kill_frame(hwnd) -> None:
    """非客户区压成 0：标题栏不可见，但 WS_CAPTION 语义保留（系统最小化动画靠它）。"""
    global _SUBCLASS_PROC
    h = int(hwnd)
    if _SUBCLASS_PROC is None:
        PROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, ctypes.c_uint,
                                  ctypes.c_size_t, ctypes.c_size_t,
                                  ctypes.c_size_t, ctypes.c_size_t)

        def _proc(hh, msg, wparam, lparam, uid, ref):
            if msg == WM_NCCALCSIZE and wparam:
                return 0
            if msg == WM_NCACTIVATE:
                return 1
            return comctl32.DefSubclassProc(hh, msg, wparam, lparam)

        _SUBCLASS_PROC = PROC(_proc)
        comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, PROC, ctypes.c_size_t, ctypes.c_size_t]
        comctl32.SetWindowSubclass.restype = ctypes.c_bool
        comctl32.DefSubclassProc.argtypes = [wintypes.HWND, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t]
        comctl32.DefSubclassProc.restype = ctypes.c_longlong

    if h not in _SUBCLASSED:
        ok = comctl32.SetWindowSubclass(wintypes.HWND(h), _SUBCLASS_PROC, 1, 0)
        print("[ti] SetWindowSubclass ->", bool(ok), flush=True)
        if ok:
            _SUBCLASSED.add(h)
    try:
        marg = _MARGINS(0, 0, 0, 0)
        dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(h), ctypes.byref(marg))
    except Exception as exc:
        print("[ti] dwm failed:", exc, flush=True)


def _add_caption(hwnd) -> None:
    h = wintypes.HWND(int(hwnd))
    st = user32.GetWindowLongPtrW(h, GWL_STYLE)
    user32.SetWindowLongPtrW(h, GWL_STYLE, st | WS_CAPTION)
    user32.SetWindowPos(h, None, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    print("[ti] caption added, style 0x%08X" % ((st | WS_CAPTION) & 0xFFFFFFFF), flush=True)


def _run_on_ui_thread(fn) -> bool:
    try:
        import clr  # noqa: F401
        from System import Action
        from System.Windows.Forms import Application
        forms = list(Application.OpenForms)
        if not forms:
            return False
        forms[-1].BeginInvoke(Action(fn))
        return True
    except Exception as exc:
        print("[ti] ui-thread invoke failed:", exc, flush=True)
        return False


DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


def _round_corners(hwnd) -> None:
    """Win11 圆角；老系统退化成 SetWindowRgn 圆角矩形。"""
    h = wintypes.HWND(int(hwnd))
    try:
        pref = ctypes.c_int(DWMWCP_ROUND)
        hr = dwmapi.DwmSetWindowAttribute(h, DWMWA_WINDOW_CORNER_PREFERENCE,
                                          ctypes.byref(pref), ctypes.sizeof(pref))
        print("[ti] dwm corner ->", hr, flush=True)
        if hr == 0:
            return
    except Exception as exc:
        print("[ti] dwm corner failed:", exc, flush=True)

    try:
        r = wintypes.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        w, hh = r.right - r.left, r.bottom - r.top
        rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, hh + 1, 18, 18)
        user32.SetWindowRgn(h, rgn, True)
        print("[ti] window region rounded", w, hh, flush=True)
    except Exception as exc:
        print("[ti] region round failed:", exc, flush=True)



def _bring_to_front(hwnd: int) -> None:
    """把窗口拎到最前并激活（启动时常见：后台起来、被别的窗口挡住）。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        user32.AllowSetForegroundWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SetWindowPos.restype = wintypes.BOOL

        ASFW_ANY = 0xFFFFFFFF
        SW_SHOW = 5
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOSIZE, SWP_NOMOVE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0040

        try:
            user32.AllowSetForegroundWindow(ASFW_ANY)
        except Exception:
            pass
        user32.ShowWindow(hwnd, SW_SHOW)
        # 先置顶再取消置顶：把窗口提到 Z 序最前，但不留 topmost 状态
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        ok = user32.SetForegroundWindow(hwnd)
        print("[ti] bring-to-front:", bool(ok), flush=True)
    except Exception as exc:
        print("[ti] bring-to-front failed:", exc, flush=True)

def _patch_window_async() -> None:
    def _worker():
        for _ in range(120):
            h = _hwnd()
            if h:
                try:
                    print("[ti] window styled:", _style_win32(h), flush=True)
                except Exception as exc:
                    print("[ti] style failed:", exc, flush=True)

                def _apply():
                    _kill_frame(h)
                    _add_caption(h)
                    _round_corners(h)

                time.sleep(0.30)
                ok = _run_on_ui_thread(_apply)
                print("[ti] caption path on ui thread:", ok, flush=True)
                time.sleep(0.35)
                _bring_to_front(h)
                time.sleep(1.2)
                _bring_to_front(_hwnd() or h)
                return
            time.sleep(0.05)

    threading.Thread(target=_worker, daemon=True).start()


def _apply_perf_env() -> None:
    """把「使用 GPU 加速」写进 WebView2 的启动参数（改完要重启程序才生效）。"""
    try:
        cfg = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    perf = (cfg.get("perf") or {})
    gpu = bool(perf.get("gpu", True))
    if gpu:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
            "--ignore-gpu-blocklist --enable-gpu-rasterization --enable-zero-copy")
    else:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--disable-gpu --disable-gpu-compositing"
    print("[ti] webview gpu:", gpu, flush=True)


def _bg_for_theme() -> str:
    """按 settings.json 的 theme 选窗口底色，避免启动瞬间黑一下。

    ROUND 23: 默认主题已是浅色，所以「没配置」时也必须给浅底，
    以前这里无脑回落 #0b0b0f，于是打开软件会先黑一帧再进启动动画。
    """
    th = ""
    try:
        cfg = json.loads((HERE / "settings.json").read_text(encoding="utf-8"))
        th = str(cfg.get("theme", "")).lower()
    except Exception:
        th = ""
    if th == "dark":
        return "#0b0b0f"
    if th == "pink":
        return "#ffeef5"
    return "#f2f2f4"


def main() -> int:
    port = backend.pick_port()
    srv = backend.ThreadingHTTPServer(("127.0.0.1", port), backend.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("[ti] server on http://127.0.0.1:%d/" % port, flush=True)

    webview.create_window(
        TITLE, "http://127.0.0.1:%d/" % port,
        width=W, height=H,
        frameless=True,
        easy_drag=False,
        background_color=_bg_for_theme(),
        text_select=False,
    )

    _patch_window_async()
    _apply_perf_env()
    webview.start(gui="edgechromium", debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())