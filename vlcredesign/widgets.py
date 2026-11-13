"""Custom-painted controls that match the design: icon buttons, the orange play pill,
seek bar, volume wedge, OFF/ON toggles, tab bars, sliders and segmented buttons."""
from __future__ import annotations

import sys

from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QHBoxLayout, QLabel, QSizePolicy, QToolTip, QWidget,
)

from . import anim, icons, theme
from .anim import Tween, lerp, mix
from .store import fmt_time


class IconButton(QAbstractButton):
    """Flat icon button: dim normally, bright on hover, orange when active/checked."""

    def __init__(self, name: str, size: int = 16, box: int = 28, tip: str = "", parent=None,
                 checkable: bool = False, color: str | None = None, hover_bg: bool = True):
        super().__init__(parent)
        self._name = name
        self._size = size
        self._color = color
        self._hover_bg = hover_bg
        self._active = False
        self.setCheckable(checkable)
        self.setFixedSize(box, box)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setFocusPolicy(Qt.NoFocus)

    def set_icon(self, name: str) -> None:
        self._name = name
        self.update()

    def set_active(self, on: bool) -> None:
        self._active = on
        self.update()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        hover = self.underMouse() and self.isEnabled()
        if hover and self._hover_bg:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 14))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 5, 5)
        if not self.isEnabled():
            col = theme.TEXT_FAINT
        elif self._active or self.isChecked():
            col = theme.ACCENT
        elif self._color:
            col = self._color
        else:
            col = theme.TEXT if hover else "#a8a8a8"
        pm = icons.pixmap(self._name, self._size, col)
        x = (self.width() - self._size) / 2
        y = (self.height() - self._size) / 2
        p.drawPixmap(QPointF(x, y), pm)


class PlayButton(QAbstractButton):
    """Orange pill with a dark play / pause glyph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._playing = False
        self.setToolTip("Play / Pause (Space)")
        self._morph = Tween(self, 0.0, 180)          # 0 = play triangle, 1 = pause bars
        self._scale = Tween(self, 1.0, 140)          # press bounce
        self._hover = Tween(self, 0.0, anim.FAST)

    def set_playing(self, playing: bool) -> None:
        if playing != self._playing:
            self._playing = playing
            self._morph.to(1.0 if playing else 0.0)

    @staticmethod
    def _glyph(m: float, cx: float, cy: float, s: float) -> tuple[QPolygonF, QPolygonF]:
        """Play triangle (m=0) morphing into two pause bars (m=1)."""
        x0, x1 = cx - s * 0.42, cx + s * 0.5
        y0, y1 = cy - s / 2, cy + s / 2
        xm = (x0 + x1) / 2
        q = s / 4
        play_l = [(x0, y0), (xm, y0 + q), (xm, y1 - q), (x0, y1)]
        play_r = [(xm, y0 + q), (x1, cy), (x1, cy), (xm, y1 - q)]
        bw = s * 0.32
        px0, px1 = cx - s * 0.42, cx + s * 0.42
        pause_l = [(px0, y0), (px0 + bw, y0), (px0 + bw, y1), (px0, y1)]
        pause_r = [(px1 - bw, y0), (px1, y0), (px1, y1), (px1 - bw, y1)]

        def poly(a, b):
            return QPolygonF([QPointF(lerp(ax, bx, m), lerp(ay, by, m)) for (ax, ay), (bx, by) in zip(a, b)])
        return poly(play_l, pause_l), poly(play_r, pause_r)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self._scale.value
        if s != 1.0:
            p.translate(self.width() / 2, self.height() / 2)
            p.scale(s, s)
            p.translate(-self.width() / 2, -self.height() / 2)
        col = mix(theme.ACCENT, QColor(theme.ACCENT).lighter(112), self._hover.value)
        if self.isDown():
            col = QColor(theme.ACCENT).darker(115)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(self.rect()), 5, 5)
        p.setBrush(QColor("#1a1a1a"))
        for poly in self._glyph(self._morph.value, self.width() / 2, self.height() / 2, 11):
            p.drawPolygon(poly)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self._scale.to(0.9, 90, QEasingCurve.OutQuad)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._scale.to(1.0, 260, QEasingCurve.OutBack)

    def enterEvent(self, e):
        self._hover.to(1.0)

    def leaveEvent(self, e):
        self._hover.to(0.0)


class SeekBar(QWidget):
    """Dark track, brown progress fill, orange handle. Chapter ticks and subtitle cues optional."""
    seekRequested = Signal(int)   # ms
    scrubbing = Signal(int)
    hoverAt = Signal(int, int)    # ms, global x of the pointer  (for frame previews)
    hoverLeft = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(80)
        self.setFixedHeight(24)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self._len = 0
        self._pos = 0
        self._drag = False
        self._hover_x: float | None = None
        self._hover = Tween(self, 0.0, anim.FAST)
        self.previews = False         # True: the owner shows a frame preview instead of a tooltip
        self.chapters: list[int] = []
        self.cues: list[tuple[int, int]] = []

    def set_length(self, ms: int) -> None:
        self._len = max(0, ms)
        self.update()

    def set_position(self, ms: int) -> None:
        if not self._drag:
            self._pos = ms
            self.update()

    def _track(self) -> QRectF:
        h = 12 + 4 * self._hover.value
        return QRectF(4, (self.height() - h) / 2, self.width() - 8, h)

    def enterEvent(self, e):
        self._hover.to(1.0)

    def _ms_at(self, x: float) -> int:
        t = self._track()
        frac = min(1.0, max(0.0, (x - t.left()) / max(1.0, t.width())))
        return int(frac * self._len)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._track()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.TRACK))
        p.drawRoundedRect(t, 3, 3)
        if self.cues and self._len:
            p.setBrush(QColor(255, 255, 255, 28))
            for a, b in self.cues:
                x1 = t.left() + t.width() * a / self._len
                x2 = t.left() + t.width() * b / self._len
                p.drawRect(QRectF(x1, t.top() + 2, max(1.0, x2 - x1), t.height() - 4))
        frac = (self._pos / self._len) if self._len else 0.0
        fx = t.left() + t.width() * min(1.0, frac)
        if frac > 0:
            p.setBrush(QColor(theme.ACCENT_DARK))
            p.drawRoundedRect(QRectF(t.left(), t.top(), fx - t.left(), t.height()), 3, 3)
        if self._len:
            p.setBrush(QColor(255, 255, 255, 60))
            for c in self.chapters:
                cx = t.left() + t.width() * c / self._len
                p.drawRect(QRectF(cx - 0.5, t.top() + 3, 1.2, t.height() - 6))
        if self._hover_x is not None and self._len:
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRect(QRectF(self._hover_x - 0.5, t.top(), 1.2, t.height()))
        if self._len:
            hv = self._hover.value
            hw, hh = 6 + 2 * hv, 16 + 4 * hv
            p.setBrush(QColor(theme.ACCENT))
            p.drawRoundedRect(QRectF(fx - hw / 2, t.center().y() - hh / 2, hw, hh), 2, 2)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._len:
            self._drag = True
            self._pos = self._ms_at(e.position().x())
            self.scrubbing.emit(self._pos)
            self.update()

    def mouseMoveEvent(self, e):
        x = e.position().x()
        self._hover_x = x
        if self._len:
            ms = self._ms_at(x)
            if self.previews:
                self.hoverAt.emit(ms, int(e.globalPosition().x()))
            else:
                QToolTip.showText(e.globalPosition().toPoint() + QPointF(0, -38).toPoint(),
                                  fmt_time(ms, force_hours=self._len >= 3_600_000), self)
            if self._drag:
                self._pos = ms
                self.scrubbing.emit(ms)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.seekRequested.emit(self._pos)
            self.update()

    def leaveEvent(self, e):
        self._hover_x = None
        QToolTip.hideText()
        self.hoverLeft.emit()
        self._hover.to(0.0)
        self.update()

    def length(self) -> int:
        return self._len

    def wheelEvent(self, e):
        step = 5000 if e.angleDelta().y() > 0 else -5000
        self.seekRequested.emit(int(max(0, min(self._len, self._pos + step))))


class VolumeWedge(QWidget):
    """Wedge-shaped volume control (thin at 0, tall at max), lime fill."""
    volumeChanged = Signal(int)

    MAX = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(70, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._v = 80
        self._muted = False
        self._shown = Tween(self, 80.0, 160)      # displayed level glides to the real one
        self._mute_t = Tween(self, 0.0, anim.FAST)
        self._dragging = False

    def set_volume(self, v: int, muted: bool = False) -> None:
        self._v, self._muted = v, muted
        self.setToolTip(f"Volume {v}%" + (" (muted)" if muted else ""))
        if self._dragging or not self.isVisible():
            self._shown.snap(v)
        else:
            self._shown.to(v)
        self._mute_t.to(1.0 if muted else 0.0)
        self.update()

    def _shape(self, upto: float) -> QPolygonF:
        r = QRectF(2, 3, self.width() - 4, self.height() - 6)
        w = r.width() * upto
        h_left, h_right = r.height() * 0.30, r.height()
        h_at = h_left + (h_right - h_left) * upto
        cy = r.center().y()
        return QPolygonF([
            QPointF(r.left(), cy - h_left / 2), QPointF(r.left() + w, cy - h_at / 2),
            QPointF(r.left() + w, cy + h_at / 2), QPointF(r.left(), cy + h_left / 2),
        ])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.TRACK))
        p.drawPolygon(self._shape(1.0))
        frac = max(0.0, min(1.0, self._shown.value / self.MAX))
        if frac > 0.002:
            p.setBrush(mix(theme.VOLUME, "#4a4a4a", self._mute_t.value))
            p.drawPolygon(self._shape(frac))

    def _set_from(self, x: float) -> None:
        frac = min(1.0, max(0.0, (x - 2) / (self.width() - 4)))
        self.volumeChanged.emit(int(round(frac * self.MAX)))

    def mousePressEvent(self, e):
        self._set_from(e.position().x())   # a click glides to the new level
        self._dragging = True

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._set_from(e.position().x())

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def wheelEvent(self, e):
        self.volumeChanged.emit(max(0, min(self.MAX, self._v + (5 if e.angleDelta().y() > 0 else -5))))


class Toggle(QAbstractButton):
    """OFF / ON switch in the style of the design (square knob + label)."""

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(52, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self._t = Tween(self, 1.0 if checked else 0.0, 180)
        # animate user clicks and programmatic changes alike (only while visible)
        self.toggled.connect(lambda on: self._t.to(1.0 if on else 0.0) if self.isVisible()
                             else self._t.snap(1.0 if on else 0.0))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        t = self._t.value
        p.setPen(QPen(QColor("#2c2c2c"), 1))
        p.setBrush(mix("#1a1a1a", theme.ACCENT_BG, t))
        p.drawRoundedRect(r, 4, 4)
        kw = 18
        knob = QRectF(lerp(r.left() + 2, r.right() - 2 - kw, t), r.top() + 2, kw, r.height() - 4)
        if not self.isEnabled():
            p.setOpacity(0.4)
        p.setPen(Qt.NoPen)
        p.setBrush(mix("#4a4a4a", theme.ACCENT, t))
        p.drawRoundedRect(knob, 3, 3)
        f = QFont(self.font())
        f.setPointSizeF(7.5)
        p.setFont(f)
        base = p.opacity()
        # OFF label sits right of the knob, ON label left of it; cross-fade them
        for label, rect, a, col in (
            ("OFF", QRectF(r.left() + 22, r.top(), r.width() - 24, r.height()), 1 - t, "#9a9a9a"),
            ("ON", QRectF(r.left() + 2, r.top(), r.width() - 24, r.height()), t, theme.ACCENT),
        ):
            if a > 0.01:
                p.setOpacity(base * a)
                p.setPen(QColor(col))
                p.drawText(rect, Qt.AlignCenter, label)
        p.setOpacity(base)


class TabBar(QWidget):
    """Row of icon+label tabs with an orange underline on the selected tab."""
    currentChanged = Signal(int)

    def __init__(self, tabs: list[tuple[str, str]], parent=None):
        super().__init__(parent)
        self._tabs = tabs
        self._cur = 0
        self._hover = -1
        self._ind = Tween(self, 0.0, 220)   # underline position, as a fractional tab index
        self.setFixedHeight(40)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def current(self) -> int:
        return self._cur

    def set_current(self, i: int, emit: bool = True) -> None:
        if i != self._cur:
            self._cur = i
            if self.isVisible():
                self._ind.to(i)
            else:
                self._ind.snap(i)
            self.update()
            if emit:
                self.currentChanged.emit(i)

    def _rect(self, i: int) -> QRectF:
        w = self.width() / len(self._tabs)
        return QRectF(i * w, 0, w, self.height())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.DIVIDER), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        fm = QFontMetrics(self.font())
        for i, (ic, label) in enumerate(self._tabs):
            r = self._rect(i)
            sel = i == self._cur
            col = theme.ACCENT if sel else (theme.TEXT if i == self._hover else theme.TEXT_DIM)
            text_col = theme.TEXT if sel else col
            tw = fm.horizontalAdvance(label)
            total = 14 + 8 + tw
            x = r.center().x() - total / 2
            p.drawPixmap(QPointF(x, r.center().y() - 7), icons.pixmap(ic, 14, col))
            p.setPen(QColor(text_col))
            p.drawText(QRectF(x + 22, r.top(), tw + 4, r.height()), Qt.AlignVCenter | Qt.AlignLeft, label)
        # sliding underline
        w = self.width() / len(self._tabs)
        ux = self._ind.value * w
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(ux + 10, self.height() - 2, w - 20, 2), 1, 1)

    def mouseMoveEvent(self, e):
        w = self.width() / len(self._tabs)
        h = int(e.position().x() // w)
        if h != self._hover:
            self._hover = h
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mousePressEvent(self, e):
        w = self.width() / len(self._tabs)
        self.set_current(min(len(self._tabs) - 1, int(e.position().x() // w)))


class GoldSlider(QWidget):
    """Horizontal slider in the design's style. Fill grows from `origin` to the value."""
    valueChanged = Signal(float)
    released = Signal(float)

    def __init__(self, lo: float, hi: float, value: float, origin: float | None = None,
                 ticks: list[float] | None = None, labels: list[tuple[float, str]] | None = None,
                 step: float = 0.0, parent=None):
        super().__init__(parent)
        self.lo, self.hi, self._v = lo, hi, value
        self.origin = lo if origin is None else origin
        self.ticks = ticks or []
        self.labels = labels or []
        self.step = step
        self._drag = False
        self.setFixedHeight(40 if self.labels else 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def value(self) -> float:
        return self._v

    def set_value(self, v: float) -> None:
        self._v = min(self.hi, max(self.lo, v))
        self.update()

    def _track(self) -> QRectF:
        pad = 16 if self.labels else 5   # room for the end labels
        return QRectF(pad, 6, self.width() - 2 * pad, 10)

    def _x(self, v: float) -> float:
        t = self._track()
        return t.left() + t.width() * (v - self.lo) / (self.hi - self.lo)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = self._track()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.TRACK))
        p.drawRoundedRect(t, 3, 3)
        x0, x1 = sorted((self._x(self.origin), self._x(self._v)))
        if x1 - x0 > 0.5:
            p.setBrush(QColor(theme.ACCENT_DARK))
            p.drawRect(QRectF(x0, t.top(), x1 - x0, t.height()))
        p.setBrush(QColor(255, 255, 255, 50))
        for tk in self.ticks:
            p.drawRect(QRectF(self._x(tk) - 0.5, t.top() + 3, 1, t.height() - 6))
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(self._x(self._v) - 3, t.center().y() - 8, 6, 16), 2, 2)
        if self.labels:
            f = QFont(self.font())
            f.setPointSizeF(7.5)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT_DIM))
            for v, lab in self.labels:
                x = self._x(v)
                p.drawText(QRectF(x - 20, t.bottom() + 6, 40, 14), Qt.AlignCenter, lab)

    def _from_x(self, x: float) -> None:
        t = self._track()
        frac = min(1.0, max(0.0, (x - t.left()) / t.width()))
        v = self.lo + frac * (self.hi - self.lo)
        if self.step:
            v = round(v / self.step) * self.step
        v = min(self.hi, max(self.lo, v))
        if v != self._v:
            self._v = v
            self.update()
            self.valueChanged.emit(v)

    def mousePressEvent(self, e):
        self._drag = True
        self._from_x(e.position().x())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._from_x(e.position().x())

    def mouseReleaseEvent(self, e):
        self._drag = False
        self.released.emit(self._v)

    def mouseDoubleClickEvent(self, e):
        self.set_value(self.origin if self.origin != self.lo else self._v)
        self.valueChanged.emit(self._v)
        self.released.emit(self._v)


class Segmented(QWidget):
    """Segmented control (e.g. Flip: None / Horizontal / Vertical)."""
    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for i, lab in enumerate(labels):
            b = _SegButton(lab)
            self.group.addButton(b, i)
            lay.addWidget(b)
        self.group.button(0).setChecked(True)
        self._ind = Tween(self, 0.0, 200)   # highlight position as a fractional segment index
        self.group.idToggled.connect(self._moved)
        self.group.idClicked.connect(self.changed)

    def _moved(self, i: int, on: bool) -> None:
        if on:
            self._ind.to(i) if self.isVisible() else self._ind.snap(i)

    def set_index(self, i: int) -> None:
        self.group.button(i).setChecked(True)

    def paintEvent(self, _):
        btns = self.group.buttons()
        if not btns:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1a1a1a"))
        for b in btns:
            p.drawRoundedRect(QRectF(b.geometry()), 3, 3)
        v = self._ind.value
        i0 = max(0, min(len(btns) - 1, int(v)))
        i1 = min(len(btns) - 1, i0 + 1)
        f = v - i0
        g0, g1 = QRectF(btns[i0].geometry()), QRectF(btns[i1].geometry())
        r = QRectF(lerp(g0.left(), g1.left(), f), g0.top(), lerp(g0.width(), g1.width(), f), g0.height())
        p.setBrush(QColor(theme.ACCENT_DARK))
        p.drawRoundedRect(r, 3, 3)


class _SegButton(QAbstractButton):
    def __init__(self, text: str):
        super().__init__()
        self.setText(text)
        self.setCheckable(True)
        self.setFixedHeight(30)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def sizeHint(self):
        return QSize(80, 30)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        # the parent Segmented paints the base and the sliding highlight
        if not on and self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 8))
            p.drawRoundedRect(QRectF(self.rect()), 3, 3)
        p.setPen(QColor(theme.ACCENT if on else theme.TEXT_DIM))
        p.drawText(self.rect(), Qt.AlignCenter, self.text())

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()


OVERLAY_OPACITY = 0.86   # translucency of the floating panels over the video


class Panel(QWidget):
    """Rounded, opaque panel. Rendered as a native child window so it can sit above the
    libVLC video surface (which is itself a native window)."""

    def __init__(self, parent=None, radius: int = 8, color: str = theme.PANEL):
        super().__init__(parent)
        self._radius = radius
        self._color = color
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WA_StyledBackground, False)
        # open/close animation state (see animate_open)
        self.max_opacity = 1.0
        self.slide = (0, 0)           # offset (px) the panel slides in from
        self._open = False
        self._t = 0.0
        self._base: QRect | None = None
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._anim_step)
        self._anim.finished.connect(self._anim_done)

    # -- open / close animation -------------------------------------------------------
    def is_open(self) -> bool:
        return self._open

    def place(self, rect: QRect) -> None:
        """Set the panel's resting geometry; the slide offset is applied on top of it."""
        self._base = QRect(rect)
        self._apply_geometry()

    def _apply_geometry(self) -> None:
        if self._base is None:
            return
        k = 1.0 - self._t
        self.setGeometry(self._base.translated(round(self.slide[0] * k), round(self.slide[1] * k)))

    def animate_open(self, open_: bool, duration: int = 200) -> None:
        """Slide + fade the panel in or out. Hides it when the close animation ends."""
        if open_ == self._open and (self._anim.state() == QVariantAnimation.Running or self.isVisible() == open_):
            return
        self._open = open_
        if open_ and not self.isVisible():
            self._t = 0.0
            self.set_opacity(0.0)
            self._apply_geometry()
            self.show()
            self.raise_()
        elif open_:
            self.raise_()
        end = 1.0 if open_ else 0.0
        self._anim.stop()
        self._anim.setEasingCurve(QEasingCurve.OutCubic if open_ else QEasingCurve.InCubic)
        self._anim.setDuration(max(1, int(duration * abs(end - self._t))))
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(end)
        self._anim.start()

    def _anim_step(self, v) -> None:
        self._t = float(v)
        self.set_opacity(self.max_opacity * self._t)
        self._apply_geometry()

    def _anim_done(self) -> None:
        if not self._open:
            self.hide()

    def reapply_opacity(self) -> None:
        if self.isVisible():
            self.set_opacity(self.max_opacity * self._t)

    def set_opacity(self, alpha: float) -> None:
        """Whole-panel opacity (0..1). Panels are native child windows above libVLC's video
        window, so Qt's own opacity can't blend them; use a layered child window instead."""
        if sys.platform != "win32":
            return
        import ctypes
        u32 = ctypes.windll.user32
        u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        h = int(self.winId())
        ex = u32.GetWindowLongPtrW(h, -20)              # GWL_EXSTYLE
        if not ex & 0x80000:                              # WS_EX_LAYERED
            u32.SetWindowLongPtrW(h, -20, ctypes.c_ssize_t(ex | 0x80000))
        u32.SetLayeredWindowAttributes(h, 0, max(0, min(255, round(alpha * 255))), 2)  # LWA_ALPHA

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._radius:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
            from PySide6.QtGui import QRegion
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self._color))

    def nativeEvent(self, event_type, message):
        # let the window's resize border work where a panel touches the window edge
        from . import winframe
        res = winframe.handle_child_edge(self, message)
        return res if res is not None else super().nativeEvent(event_type, message)


def dim_label(text: str, size: float | None = None, color: str = theme.TEXT_DIM) -> QLabel:
    lab = QLabel(text)
    css = f"color: {color};"
    if size:
        css += f" font-size: {size}px;"
    lab.setStyleSheet(css)
    return lab


def heading(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"color: {theme.TEXT}; font-size: 14px; font-weight: 600;")
    return lab


def rect_center(outer: QRect, w: int, h: int) -> QRect:
    return QRect(outer.center().x() - w // 2, outer.center().y() - h // 2, w, h)
