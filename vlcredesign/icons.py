"""Line-icon set (24x24 viewBox, stroke icons) rendered on demand in any colour."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtSvg import QSvgRenderer

# "F:" prefix = filled shape (fill=currentColor, no stroke)
_ICONS: dict[str, str] = {
    "more": 'F:<circle cx="5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="19" cy="12" r="1.6"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
    "folder": '<path d="M20 19a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9l-.8-1.2A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2Z"/>',
    "minimize": '<path d="M5 12h14"/>',
    "maximize": '<rect x="5" y="5" width="14" height="14" rx="1.5"/>',
    "restore": '<rect x="4" y="8" width="12" height="12" rx="1.5"/><path d="M8 8V5.5A1.5 1.5 0 0 1 9.5 4h9A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H16"/>',
    "fullscreen": '<path d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5"/>',
    "unfullscreen": '<path d="M8 3v5H3M21 8h-5V3M3 16h5v5M16 21v-5h5"/>',
    "close": '<path d="M18 6 6 18M6 6l12 12"/>',
    "prev": 'F:<path d="M18.5 5v14L8 12z"/><rect x="5" y="5" width="2.4" height="14" rx="1"/>',
    "next": 'F:<path d="M5.5 5v14L16 12z"/><rect x="16.6" y="5" width="2.4" height="14" rx="1"/>',
    "play": 'F:<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.4-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5z"/>',
    "pause": 'F:<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    "stop": 'F:<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "volume": '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>',
    "volume-x": '<path d="M11 5 6 9H3v6h3l5 4z"/><path d="m22 9-6 6M16 9l6 6"/>',
    "waveform": '<path d="M2 10v4M6 6v12M10 3v18M14 8v8M18 5v14M22 10v4"/>',
    "subtitles": '<rect x="2.5" y="5" width="19" height="14" rx="2"/><path d="M7 15h4M14 15h3M7 11h2M12 11h5"/>',
    "settings": '<path d="M12.2 2h-.4a2 2 0 0 0-2 2v.2a2 2 0 0 1-1 1.7l-.4.3a2 2 0 0 1-2 0l-.2-.1a2 2 0 0 0-2.7.7l-.2.4a2 2 0 0 0 .7 2.7l.2.1a2 2 0 0 1 1 1.7v.5a2 2 0 0 1-1 1.7l-.2.1a2 2 0 0 0-.7 2.7l.2.4a2 2 0 0 0 2.7.7l.2-.1a2 2 0 0 1 2 0l.4.3a2 2 0 0 1 1 1.7v.2a2 2 0 0 0 2 2h.4a2 2 0 0 0 2-2v-.2a2 2 0 0 1 1-1.7l.4-.3a2 2 0 0 1 2 0l.2.1a2 2 0 0 0 2.7-.7l.2-.4a2 2 0 0 0-.7-2.7l-.2-.1a2 2 0 0 1-1-1.7v-.5a2 2 0 0 1 1-1.7l.2-.1a2 2 0 0 0 .7-2.7l-.2-.4a2 2 0 0 0-2.7-.7l-.2.1a2 2 0 0 1-2 0l-.4-.3a2 2 0 0 1-1-1.7V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
    "list": '<path d="M9 6h12M9 12h12M9 18h12"/><path d="M3.5 6h.5M3.5 12h.5M3.5 18h.5"/>',
    "queue": '<path d="M4 6h16M6 11h12M8 16h8"/><path d="M10 20.5h4"/>',
    "bookmark": '<path d="M19 21 12 17l-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    "chapters": '<path d="M3 5h18M11 12h10M11 19h10"/><path d="m3 9 4 3-4 3z"/>',
    "sort": '<path d="M7 3v18M3 7l4-4 4 4M17 21V3M13 17l4 4 4-4"/>',
    "repeat": '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
    "repeat-one": '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10h1v4"/>',
    "shuffle": '<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/><path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/><path d="m18 14 4 4-4 4"/>',
    "minus": '<path d="M5 12h14"/>',
    "plus": '<path d="M5 12h14M12 5v14"/>',
    "grip": '<path d="M5 9h14M5 15h14"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    "videos": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="m10 8 6 4-6 4z"/>',
    "music": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M10 16V8l6-1.5v8"/><circle cx="8.5" cy="16" r="1.5"/><circle cx="14.5" cy="14.5" r="1.5"/>',
    "network": '<circle cx="12" cy="12" r="2"/><path d="M16.2 7.8a6 6 0 0 1 0 8.5M7.8 16.2a6 6 0 0 1 0-8.5M19.1 4.9a10 10 0 0 1 0 14.2M4.9 19.1a10 10 0 0 1 0-14.2"/>',
    "playlist": '<path d="M3 6h13M3 12h10M3 18h7"/><path d="m16 14 5 3.5-5 3.5z"/>',
    "history": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    "arrow-left": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    "arrow-right": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "external": '<path d="M15 3h6v6M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "view": '<rect x="3" y="4" width="5" height="5" rx="1"/><rect x="3" y="15" width="5" height="5" rx="1"/><path d="M12 6.5h9M12 17.5h9"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "refresh": '<path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/>',
    "pencil": '<path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "film": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m10 9 5 3-5 3z"/>',
    "note": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "playback": '<path d="M6 4v16l14-8z"/>',
    "video-tab": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/>',
    "file-plus": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M12 12v6M9 15h6"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
}


def _svg(name: str, color: str, stroke: float) -> bytes:
    body = _ICONS[name]
    if body.startswith("F:"):
        attrs = f'fill="{color}" stroke="none"'
        body = body[2:]
    else:
        attrs = (
            f'fill="none" stroke="{color}" stroke-width="{stroke}" '
            'stroke-linecap="round" stroke-linejoin="round"'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" {attrs}>{body}</svg>'
    ).encode()


@lru_cache(maxsize=1024)
def pixmap(name: str, size: int, color: str, dpr: float = 2.0, stroke: float = 1.8) -> QPixmap:
    px = QPixmap(int(size * dpr), int(size * dpr))
    px.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, px.width(), px.height()))
    p.end()
    px.setDevicePixelRatio(dpr)
    return px


def icon(name: str, size: int = 16, color: str = "#d6d6d6") -> QIcon:
    return QIcon(pixmap(name, size, color))


# ---------------------------------------------------------------------------
# The VLC cone, drawn with vector paths (title bar) and as pixel art (idle).

def paint_cone(p: QPainter, rect: QRectF) -> None:
    """Small vector traffic cone, as in the title bar of the design."""
    w, h = rect.width(), rect.height()
    x, y = rect.x(), rect.y()
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    body = QPainterPath()
    body.moveTo(x + w * 0.42, y + h * 0.04)
    body.lineTo(x + w * 0.58, y + h * 0.04)
    body.lineTo(x + w * 0.84, y + h * 0.80)
    body.lineTo(x + w * 0.16, y + h * 0.80)
    body.closeSubpath()
    p.setBrush(QColor("#f08a1c"))
    p.drawPath(body)
    p.setBrush(QColor("#f4f4f4"))
    for top, bot in ((0.28, 0.40), (0.56, 0.66)):
        stripe = QPainterPath()
        lx_t = 0.42 - (0.26 * top / 0.76)
        lx_b = 0.42 - (0.26 * bot / 0.76)
        stripe.moveTo(x + w * lx_t, y + h * top)
        stripe.lineTo(x + w * (1 - lx_t), y + h * top)
        stripe.lineTo(x + w * (1 - lx_b), y + h * bot)
        stripe.lineTo(x + w * lx_b, y + h * bot)
        stripe.closeSubpath()
        p.drawPath(stripe)
    p.setBrush(QColor("#c86a0c"))
    p.drawRoundedRect(QRectF(x + w * 0.04, y + h * 0.80, w * 0.92, h * 0.16), 1.5, 1.5)
    p.restore()


PIXEL_CONE = [
    ".......OO.......",
    "......OOOO......",
    "......OOOO......",
    ".....WWWWWW.....",
    ".....WWWWWW.....",
    "....OOOOOOOO....",
    "....OOOOOOOO....",
    "...WWWWWWWWWW...",
    "...WWWWWWWWWW...",
    "..OOOOOOOOOOOO..",
    "..OOOOOOOOOOOO..",
    "..OOOOOOOOOOOO..",
    ".DDDDDDDDDDDDDD.",
    "DDDDDDDDDDDDDDDD",
    "DDDDDDDDDDDDDDDD",
]
_PIXEL_COLORS = {"O": "#f08a1c", "W": "#ececec", "D": "#b85f0a"}


def paint_pixel_cone(p: QPainter, cx: float, bottom: float, cell: float) -> None:
    cols = len(PIXEL_CONE[0])
    left = cx - cols * cell / 2
    top = bottom - len(PIXEL_CONE) * cell
    p.save()
    p.setPen(Qt.NoPen)
    for r, row in enumerate(PIXEL_CONE):
        for c, ch in enumerate(row):
            if ch in _PIXEL_COLORS:
                p.setBrush(QColor(_PIXEL_COLORS[ch]))
                p.drawRect(QRectF(left + c * cell, top + r * cell, cell + 0.5, cell + 0.5))
    p.restore()
