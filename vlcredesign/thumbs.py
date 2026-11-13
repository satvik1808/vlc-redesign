"""Background thumbnail loader for library rows.

On Windows this asks the shell (IShellItemImageFactory) for the same thumbnail File
Explorer shows: a video frame, or embedded album art for audio. Results are cached in
memory; files without a thumbnail fall back to the row's icon.
"""
from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap

THUMB_PX = 160  # requested size (longest side); drawn smaller, crisp on high-DPI


def _shell_thumbnail(path: str, size: int) -> QImage | None:
    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.WinDLL("ole32")
    ole32.CoInitializeEx.restype = ctypes.c_long
    shell32 = ctypes.OleDLL("shell32")
    gdi32 = ctypes.WinDLL("gdi32")

    class GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16), ("d3", ctypes.c_uint16),
                    ("d4", ctypes.c_ubyte * 8)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    # IID_IShellItemImageFactory {bcc18b79-ba16-442f-80c4-8a59c30c463b}
    iid = GUID(0xBCC18B79, 0xBA16, 0x442F, (ctypes.c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59, 0xC3, 0x0C, 0x46, 0x3B))

    hr_init = ole32.CoInitializeEx(None, 0x2)  # STA; S_FALSE if already initialised
    try:
        factory = ctypes.c_void_p()
        try:
            shell32.SHCreateItemFromParsingName(ctypes.c_wchar_p(os.path.abspath(path)), None,
                                                ctypes.byref(iid), ctypes.byref(factory))
        except OSError:
            return None
        vtbl = ctypes.cast(ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0],
                           ctypes.POINTER(ctypes.c_void_p))
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])
        get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_int,
                                       ctypes.POINTER(wintypes.HBITMAP))(vtbl[3])
        hbm = wintypes.HBITMAP()
        try:
            # SIIGBF_THUMBNAILONLY (0x8): no generic file icons
            hr = get_image(factory, SIZE(size, size), 0x8, ctypes.byref(hbm))
        finally:
            release(factory)
        if hr < 0 or not hbm:
            return None
        try:
            return _hbitmap_to_qimage(hbm, gdi32)
        finally:
            gdi32.DeleteObject(hbm)
    finally:
        if hr_init >= 0:
            ole32.CoUninitialize()


def _hbitmap_to_qimage(hbm, gdi32) -> QImage | None:
    import ctypes
    from ctypes import wintypes

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                    ("bmWidthBytes", ctypes.c_long), ("bmPlanes", wintypes.WORD),
                    ("bmBitsPixel", wintypes.WORD), ("bmBits", ctypes.c_void_p)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    bm = BITMAP()
    if not gdi32.GetObjectW(hbm, ctypes.sizeof(bm), ctypes.byref(bm)):
        return None
    w, h = bm.bmWidth, abs(bm.bmHeight)
    if w <= 0 or h <= 0:
        return None
    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    user32 = ctypes.WinDLL("user32")
    user32.GetDC.restype = ctypes.c_void_p
    hdc = user32.GetDC(None)
    try:
        lines = gdi32.GetDIBits(ctypes.c_void_p(hdc), hbm, 0, h, buf, ctypes.byref(bi), 0)
    finally:
        user32.ReleaseDC(None, ctypes.c_void_p(hdc))
    if lines != h:
        return None
    raw = buf.raw
    # Shell bitmaps are premultiplied BGRA; some come back with an all-zero alpha channel.
    has_alpha = any(raw[i] for i in range(3, len(raw), 4 * 97))
    fmt = QImage.Format_ARGB32_Premultiplied if has_alpha else QImage.Format_RGB32
    return QImage(raw, w, h, w * 4, fmt).copy()


class _Job(QRunnable):
    def __init__(self, loader: "ThumbLoader", path: str):
        super().__init__()
        self.loader = loader
        self.path = path

    def run(self):
        img = None
        try:
            img = _shell_thumbnail(self.path, THUMB_PX)
        except Exception:
            img = None
        self.loader._done.emit(self.path, img if img is not None else QImage())


class ThumbLoader(QObject):
    ready = Signal(str)
    _done = Signal(str, QImage)

    def __init__(self):
        super().__init__()
        self._cache: dict[str, QPixmap | None] = {}
        self._pending: set[str] = set()
        self.ready_at: dict[str, float] = {}   # when each thumbnail arrived (for fade-in)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._done.connect(self._on_done)

    def get(self, path: str) -> QPixmap | None:
        """Cached thumbnail for a local file, or None (requested in the background)."""
        if path in self._cache:
            return self._cache[path]
        if sys.platform == "win32" and path not in self._pending and os.path.isfile(path):
            self._pending.add(path)
            self._pool.start(_Job(self, path))
        return None

    def _on_done(self, path: str, img: QImage) -> None:
        self._pending.discard(path)
        self._cache[path] = None if img.isNull() else QPixmap.fromImage(img)
        if self._cache[path] is not None:
            self.ready_at[path] = time.monotonic()
            self.ready.emit(path)

    def shutdown(self) -> None:
        self._pool.clear()
        self._pool.waitForDone(3000)


_loader: ThumbLoader | None = None


def loader() -> ThumbLoader:
    global _loader
    if _loader is None:
        _loader = ThumbLoader()
    return _loader
