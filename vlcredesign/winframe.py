"""Make the custom-drawn window a *real* Windows top-level window.

Qt's FramelessWindowHint creates a WS_POPUP window without WS_CAPTION / WS_THICKFRAME.
Windows Snap, Snap Layouts, FancyZones and tiling managers (GlazeWM, komorebi, ...) ignore or
mis-handle such windows. Instead we keep the full overlapped-window styles and:

* answer WM_NCCALCSIZE with "no non-client area", so our own title bar fills the window;
* answer WM_NCHITTEST with HTCAPTION / HTLEFT / ... so moving, resizing, double-click
  maximise, Aero Snap and Win+Arrow are all handled natively by Windows.

This is the same technique Chrome, VS Code and Windows Terminal use for custom title bars.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WIN = sys.platform == "win32"

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
GWL_STYLE = -16
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_SYSMENU = 0x00080000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
SWP_FLAGS = 0x0020 | 0x0002 | 0x0001 | 0x0004 | 0x0010  # FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER|NOACTIVATE
MONITOR_DEFAULTTONEAREST = 2

HTTRANSPARENT = -1
HTCLIENT = 1
HTCAPTION = 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT = 10, 11, 12, 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

if IS_WIN:
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


def apply_native_styles(hwnd: int) -> None:
    """Turn Qt's WS_POPUP frameless window into a normal overlapped window."""
    if not IS_WIN:
        return
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    new = (style & ~WS_POPUP) | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
    if new != style:
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, ctypes.c_ssize_t(ctypes.c_int32(new).value).value)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FLAGS)


def _msg(message) -> "wintypes.MSG":
    return wintypes.MSG.from_address(int(message))


def _point(lparam: int) -> tuple[int, int]:
    return ctypes.c_short(lparam & 0xFFFF).value, ctypes.c_short((lparam >> 16) & 0xFFFF).value


def _window_rect(hwnd: int) -> wintypes.RECT:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r


def handle_top_level(window, message, caption_test, border_logical: int = 6):
    """nativeEvent handler for the main window. Returns (handled, result) or None.

    caption_test(x, y) -> bool gets logical window coordinates and says whether that point
    is draggable title-bar space.
    """
    if not IS_WIN:
        return None
    msg = _msg(message)
    if msg.message == WM_NCCALCSIZE and msg.wParam:
        # Client area = whole window. When maximised Windows hangs the frame off-screen,
        # so clamp the client rect to the monitor's work area instead.
        if user32.IsZoomed(msg.hWnd) and not window.isFullScreen():
            params = NCCALCSIZE_PARAMS.from_address(msg.lParam)
            mon = user32.MonitorFromWindow(msg.hWnd, MONITOR_DEFAULTTONEAREST)
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
                params.rgrc[0] = mi.rcWork
        return True, 0
    if msg.message == WM_NCHITTEST:
        x, y = _point(msg.lParam)
        r = _window_rect(msg.hWnd)
        dpr = window.devicePixelRatioF() or 1.0
        lx, ly = (x - r.left) / dpr, (y - r.top) / dpr
        w, h = (r.right - r.left) / dpr, (r.bottom - r.top) / dpr
        if not (window.isMaximized() or window.isFullScreen()):
            b = border_logical
            left, right, top, bottom = lx < b, lx >= w - b, ly < b, ly >= h - b
            if top and left:
                return True, HTTOPLEFT
            if top and right:
                return True, HTTOPRIGHT
            if bottom and left:
                return True, HTBOTTOMLEFT
            if bottom and right:
                return True, HTBOTTOMRIGHT
            if left:
                return True, HTLEFT
            if right:
                return True, HTRIGHT
            if top:
                return True, HTTOP
            if bottom:
                return True, HTBOTTOM
        if caption_test(lx, ly):
            return True, HTCAPTION
        return True, HTCLIENT
    return None


def handle_child_edge(widget, message, border_logical: int = 6):
    """nativeEvent handler for native child windows (overlay panels, video surface) that
    touch the window border: let the resize edge fall through to the top-level window."""
    if not IS_WIN:
        return None
    msg = _msg(message)
    if msg.message != WM_NCHITTEST:
        return None
    top = widget.window()
    if top.isMaximized() or top.isFullScreen():
        return None
    x, y = _point(msg.lParam)
    root = user32.GetAncestor(msg.hWnd, 2)  # GA_ROOT
    r = _window_rect(root)
    dpr = top.devicePixelRatioF() or 1.0
    b = border_logical * dpr
    if x - r.left < b or r.right - x <= b or y - r.top < b or r.bottom - y <= b:
        return True, HTTRANSPARENT
    return None
