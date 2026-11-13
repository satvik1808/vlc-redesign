"""Main window: frameless shell with the redesigned title bar, video stage and control bar."""
from __future__ import annotations

import os
import random
import re

from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, QRectF, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QCursor, QFont, QKeySequence, QPainter, QPainterPath, QRegion, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from . import icons, theme, winframe
from .engine import Engine, parse_duration_async, parsed_duration
from .library import PANEL_W, RAIL_W, Library, scan_folder
from .panels import QueuePanel, SettingsPanel, TracksPopup, subtitle_args_from_store
from .store import MEDIA_EXT, SUB_EXT, Store, fmt_short, fmt_time, mrl_to_path, title_of, to_mrl
from .widgets import IconButton, Panel, PlayButton, SeekBar, VolumeWedge

APP_TITLE = "VLC Media Player"


# ---------------------------------------------------------------------------
class PlayQueue:
    def __init__(self) -> None:
        self.items: list[dict] = []
        self.index = -1
        self.repeat = "off"     # off | all | one
        self.shuffle = False
        self._next_id = 1
        self._played: set[int] = set()

    def make(self, mrl: str, duration: int = 0) -> dict:
        e = {"id": self._next_id, "mrl": mrl, "title": title_of(mrl), "duration": duration}
        self._next_id += 1
        return e

    def current(self) -> dict | None:
        return self.items[self.index] if 0 <= self.index < len(self.items) else None

    def pos_of(self, qid: int) -> int:
        for i, e in enumerate(self.items):
            if e["id"] == qid:
                return i
        return -1

    def next(self, auto: bool) -> int | None:
        n = len(self.items)
        if not n:
            return None
        if auto and self.repeat == "one":
            return self.index
        if self.shuffle:
            self._played.add(self.index)
            pool = [i for i in range(n) if i not in self._played]
            if not pool:
                if auto and self.repeat == "off":
                    return None
                self._played = {self.index}
                pool = [i for i in range(n) if i != self.index] or [self.index]
            return random.choice(pool)
        i = self.index + 1
        if i >= n:
            return 0 if (self.repeat == "all" or not auto) else None
        return i

    def prev(self) -> int | None:
        n = len(self.items)
        if not n:
            return None
        i = self.index - 1
        return (n - 1 if self.repeat == "all" else 0) if i < 0 else i


def parse_srt(path: str) -> list[tuple[int, int]]:
    cues = []
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return cues
    pat = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")
    for m in pat.finditer(text):
        a = ((int(m[1]) * 60 + int(m[2])) * 60 + int(m[3])) * 1000 + int(m[4][:3].ljust(3, "0"))
        b = ((int(m[5]) * 60 + int(m[6])) * 60 + int(m[7])) * 1000 + int(m[8][:3].ljust(3, "0"))
        cues.append((a, b))
    return cues


# ---------------------------------------------------------------------------
class ConeLogo(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)

    def paintEvent(self, _):
        p = QPainter(self)
        icons.paint_cone(p, QRectF(6, 5, 16, 17))


class TitleBar(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.setFixedHeight(34)
        self.setAutoFillBackground(False)
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 0, 4, 0)
        h.setSpacing(2)
        h.addWidget(ConeLogo())
        self.b_more = IconButton("more", 16, tip="Menu")
        self.b_side = IconButton("sidebar", 16, tip="Library (Ctrl+L)", checkable=True)
        h.addWidget(self.b_more)
        h.addWidget(self.b_side)
        sep = QFrame()
        sep.setFixedSize(1, 16)
        sep.setStyleSheet("background:#333;")
        h.addSpacing(6)
        h.addWidget(sep)
        h.addSpacing(6)
        self.crumb = QPushButton("  Videos")
        self.crumb.setIcon(icons.icon("folder", 16, "#a8a8a8"))
        self.crumb.setCursor(Qt.PointingHandCursor)
        self.crumb.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:{theme.TEXT_DIM};padding:4px 6px;font-size:12.5px;}}"
            f"QPushButton:hover{{color:{theme.TEXT};background:rgba(255,255,255,14);border-radius:5px;}}")
        self.crumb.setFocusPolicy(Qt.NoFocus)
        h.addWidget(self.crumb)
        h.addStretch(1)
        self.b_min = IconButton("minimize", 16, 34, "Minimize")
        self.b_max = IconButton("maximize", 14, 34, "Maximize")
        self.b_full = IconButton("fullscreen", 15, 34, "Fullscreen (F)")
        self.b_close = IconButton("close", 16, 34, "Close")
        for b in (self.b_min, self.b_max, self.b_full, self.b_close):
            h.addWidget(b)
        self.title = QLabel(APP_TITLE, self)
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet(f"color:{theme.TEXT_DIM}; font-size:12.5px;")
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_title(self, text: str) -> None:
        self.title.setText(text)
        self._place_title()

    def _place_title(self) -> None:
        w = min(self.width() // 2, self.title.fontMetrics().horizontalAdvance(self.title.text()) + 20)
        self.title.setGeometry((self.width() - w) // 2, 0, w, self.height())
        self.title.setText(self.title.fontMetrics().elidedText(self.title.text(), Qt.ElideMiddle, w))

    def resizeEvent(self, e):
        self._place_title()

    def paintEvent(self, _):
        QPainter(self).fillRect(self.rect(), QColor(theme.WINDOW))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self.win.toggle_maximized()


class VideoSurface(QWidget):
    """Native window that libVLC renders into. Paints the idle / audio-only state itself."""

    def __init__(self, win: "MainWindow", parent):
        super().__init__(parent)
        self.win = win
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.mode = "idle"
        self.caption = ""
        self.radius = 8

    def set_mode(self, mode: str, caption: str = "") -> None:
        self.mode, self.caption = mode, caption
        self.update()

    def resizeEvent(self, e):
        if self.radius:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self.radius, self.radius)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        else:
            self.clearMask()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        r = self.rect()
        p.fillRect(r, QColor(theme.STAGE if self.mode != "video" else "#000000"))
        if self.mode == "video":
            return
        # floor band like the design's stage
        floor = int(r.height() * 0.62)
        p.fillRect(QRect(0, floor, r.width(), r.height() - floor), QColor("#272625"))
        cell = max(4, min(10, r.height() // 45))
        icons.paint_pixel_cone(p, r.width() / 2, floor, cell)
        f = QFont(self.font())
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT_DIM))
        if self.mode == "audio":
            f.setPixelSize(15)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRect(0, floor + 24, r.width(), 24), Qt.AlignCenter, self.caption)
        else:
            p.drawText(QRect(0, floor + 24, r.width(), 22), Qt.AlignCenter,
                       "Drop media here, or press Ctrl+O to open a file")
            p.setPen(QColor(theme.TEXT_FAINT))
            f.setPixelSize(11.5)
            p.setFont(f)
            p.drawText(QRect(0, floor + 48, r.width(), 20), Qt.AlignCenter,
                       "Ctrl+L library  ·  Ctrl+N network stream  ·  F fullscreen")

    def nativeEvent(self, event_type, message):
        res = winframe.handle_child_edge(self, message)
        return res if res is not None else super().nativeEvent(event_type, message)

    def mouseDoubleClickEvent(self, e):
        self.win.toggle_fullscreen()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.win.close_overlays()
        elif e.button() == Qt.RightButton:
            self.win.show_main_menu(e.globalPosition().toPoint())

    def wheelEvent(self, e):
        self.win.change_volume(5 if e.angleDelta().y() > 0 else -5)


class ControlBar(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.setFixedHeight(46)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 0, 10, 2)
        h.setSpacing(4)
        self.b_prev = IconButton("prev", 13, 30, "Previous (P)")
        self.b_play = PlayButton()
        self.b_next = IconButton("next", 13, 30, "Next (N)")
        h.addWidget(self.b_prev)
        h.addWidget(self.b_play)
        h.addWidget(self.b_next)
        h.addSpacing(10)
        self.t_cur = QLabel("00:00:00")
        self.t_len = QLabel("00:00:00")
        for lab in (self.t_cur, self.t_len):
            lab.setStyleSheet(f"color:{theme.TEXT_DIM}; font-size:12px;")
            lab.setFixedWidth(62)
            lab.setAlignment(Qt.AlignCenter)
        self.seek = SeekBar()
        h.addWidget(self.t_cur)
        h.addWidget(self.seek, 1)
        h.addWidget(self.t_len)
        h.addSpacing(12)
        self.b_mute = IconButton("volume", 16, 28, "Mute (M)")
        self.vol = VolumeWedge()
        h.addWidget(self.b_mute)
        h.addWidget(self.vol)
        h.addSpacing(14)
        self.b_tracks = IconButton("waveform", 16, 30, "Audio tracks & devices")
        self.b_subs = IconButton("subtitles", 17, 30, "Subtitles")
        self.b_settings = IconButton("settings", 16, 30, "Settings")
        h.addWidget(self.b_tracks)
        h.addWidget(self.b_subs)
        h.addWidget(self.b_settings)
        h.addSpacing(10)
        self.b_queue = IconButton("list", 17, 30, "Queue, bookmarks & chapters (Q)")
        h.addWidget(self.b_queue)

    def paintEvent(self, _):
        QPainter(self).fillRect(self.rect(), QColor(theme.WINDOW))


class Stage(QWidget):
    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win

    def resizeEvent(self, e):
        self.win.layout_stage()

    def paintEvent(self, _):
        QPainter(self).fillRect(self.rect(), QColor(theme.WINDOW))


class InfoPanel(Panel):
    """Small native overlay used for the OSD and the statistics readout."""

    def __init__(self, parent, mono: bool = False):
        super().__init__(parent, radius=6, color="#141414")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        self.label = QLabel()
        css = f"color:{theme.TEXT}; font-size:12px;"
        if mono:
            css += "font-family: Consolas, 'Cascadia Mono', monospace; font-size:11px;"
        self.label.setStyleSheet(css)
        lay.addWidget(self.label)

    def set_text(self, text: str) -> None:
        self.label.setText(text)
        self.adjustSize()


# ---------------------------------------------------------------------------
class MainWindow(QWidget):
    def __init__(self, files: list[str] | None = None):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(760, 440)
        self.setAcceptDrops(True)

        self.store = Store()
        self.engine = Engine(subtitle_args_from_store(self.store))
        self.queue = PlayQueue()
        self.queue.repeat = self.store.get("repeat", "off")
        self.queue.shuffle = self.store.get("shuffle", False)
        self._parsing: dict[int, object] = {}
        self._was_maximized = False
        self._stop_after_current = False
        self._edge_cursor = False
        self._last_chapter = -2
        self.right_panel: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.titlebar = TitleBar(self)
        self.stage = Stage(self)
        self.controls = ControlBar(self)
        root.addWidget(self.titlebar)
        root.addWidget(self.stage, 1)
        root.addWidget(self.controls)

        self.video = VideoSurface(self, self.stage)
        self.library = Library(self)
        self.queue_panel = QueuePanel(self)
        self.settings = SettingsPanel(self)
        self.tracks = TracksPopup(self)
        self.stats_panel = InfoPanel(self.stage, mono=True)
        self.osd_panel = InfoPanel(self.stage)
        for w in (self.library, self.queue_panel, self.settings, self.tracks, self.stats_panel, self.osd_panel):
            w.hide()

        self._osd_timer = QTimer(self, singleShot=True, interval=1400, timeout=self.osd_panel.hide)
        self._stats_timer = QTimer(self, interval=1000, timeout=self._update_stats)
        self._parse_timer = QTimer(self, interval=500, timeout=self._poll_parsing)
        self._sleep_timer = QTimer(self, singleShot=True, timeout=self._sleep_fired)
        self._autohide = QTimer(self, interval=250, timeout=self._fullscreen_autohide)
        self._history_timer = QTimer(self, interval=15000, timeout=self._record_current)
        self._history_timer.start()
        self._last_mouse = QPoint()
        self._idle_ms = 0

        self._wire()
        self._shortcuts()
        self._restore()
        if not winframe.IS_WIN:
            QApplication.instance().installEventFilter(self)  # fallback edge-resize

        if files:
            QTimer.singleShot(0, lambda: self.open_paths(files))

    # -- wiring ------------------------------------------------------------------
    def _wire(self) -> None:
        tb, cb, e = self.titlebar, self.controls, self.engine
        tb.b_more.clicked.connect(lambda: self.show_main_menu(tb.b_more.mapToGlobal(tb.b_more.rect().bottomLeft())))
        tb.b_side.clicked.connect(self.toggle_library)
        tb.crumb.clicked.connect(self._crumb_clicked)
        tb.b_min.clicked.connect(self.showMinimized)
        tb.b_max.clicked.connect(self.toggle_maximized)
        tb.b_full.clicked.connect(self.toggle_fullscreen)
        tb.b_close.clicked.connect(self.close)

        cb.b_play.clicked.connect(self.toggle_play)
        cb.b_prev.clicked.connect(self.prev)
        cb.b_next.clicked.connect(self.next)
        cb.seek.seekRequested.connect(e.seek)
        cb.seek.scrubbing.connect(lambda ms: cb.t_cur.setText(fmt_time(ms)))
        cb.vol.volumeChanged.connect(e.set_volume)
        cb.b_mute.clicked.connect(lambda: e.set_muted(not e.muted()))
        cb.b_tracks.clicked.connect(lambda: self.toggle_right("tracks", 1))
        cb.b_subs.clicked.connect(lambda: self.toggle_right("tracks", 2))
        cb.b_settings.clicked.connect(lambda: self.toggle_right("settings"))
        cb.b_queue.clicked.connect(lambda: self.toggle_right("queue"))

        e.stateChanged.connect(self._state_changed)
        e.timeChanged.connect(self._time_changed)
        e.lengthChanged.connect(self._length_changed)
        e.endReached.connect(self._end_reached)
        e.volumeChanged.connect(self._volume_changed)
        e.voutChanged.connect(self._vout_changed)
        e.tracksChanged.connect(self._refresh_chapters)
        e.rateChanged.connect(lambda r: self.osd(f"Speed {r:g}x"))

    def _shortcuts(self) -> None:
        def sc(keys, fn):
            for k in keys if isinstance(keys, (list, tuple)) else [keys]:
                QShortcut(QKeySequence(k), self, activated=fn)

        sc("Space", self.toggle_play)
        sc(["F", "F11"], self.toggle_fullscreen)
        sc("Escape", self._escape)
        sc("Right", lambda: self.jump(10_000))
        sc("Left", lambda: self.jump(-10_000))
        sc("Shift+Right", lambda: self.jump(3_000))
        sc("Shift+Left", lambda: self.jump(-3_000))
        sc("Ctrl+Right", lambda: self.jump(60_000))
        sc("Ctrl+Left", lambda: self.jump(-60_000))
        sc("Up", lambda: self.change_volume(5))
        sc("Down", lambda: self.change_volume(-5))
        sc("M", lambda: self.engine.set_muted(not self.engine.muted()))
        sc("N", self.next)
        sc("P", self.prev)
        sc("S", self.stop)
        sc("E", self.engine.next_frame)
        sc("]", lambda: self.engine.set_rate(round(self.engine.rate() + 0.1, 2)))
        sc("[", lambda: self.engine.set_rate(round(self.engine.rate() - 0.1, 2)))
        sc("=", lambda: self.engine.set_rate(1.0))
        sc("Ctrl+O", self.open_files)
        sc("Ctrl+F", self.open_folder)
        sc("Ctrl+N", self.open_network)
        sc("Ctrl+L", self.toggle_library)
        sc("Q", lambda: self.toggle_right("queue"))
        sc("Ctrl+P", lambda: self.toggle_right("settings"))
        sc("Ctrl+B", self.add_bookmark)
        sc("Shift+S", self.snapshot)
        sc("V", self._cycle_subtitle)
        sc("B", self._cycle_audio)
        sc("H", lambda: self.settings.sp_sdelay.setValue(self.settings.sp_sdelay.value() - 0.05))
        sc("J", lambda: self.settings.sp_sdelay.setValue(self.settings.sp_sdelay.value() + 0.05))
        sc("Ctrl+Q", self.close)

    # -- layout --------------------------------------------------------------------
    def layout_stage(self) -> None:
        r = self.stage.rect()
        fs = self.isFullScreen()
        vr = r if fs else r.adjusted(8, 0, -8, -2)
        self.video.radius = 0 if fs else 8
        self.video.setGeometry(vr)
        self.video.resizeEvent(None)
        lib_w = RAIL_W + PANEL_W
        self.library.setGeometry(0, 0, lib_w, r.height())
        pw = min(340, max(280, vr.width() // 3))
        side = QRect(vr.right() - pw - 8, vr.top() + 10, pw, max(120, vr.height() - 20))
        self.queue_panel.setGeometry(side)
        self.settings.setGeometry(side)
        th = min(430, side.height())
        self.tracks.setGeometry(QRect(side.left(), side.bottom() - th + 1, pw, th))
        left = (lib_w if self.library.isVisible() else vr.left()) + 12
        self.stats_panel.move(left, vr.top() + 12)
        self.osd_panel.move(left, vr.top() + 12 + (self.stats_panel.height() + 8 if self.stats_panel.isVisible() else 0))

    def _show_overlay(self, w: QWidget) -> None:
        w.show()
        w.raise_()

    # -- panels ----------------------------------------------------------------------
    def toggle_library(self) -> None:
        if self.library.isVisible():
            self.library.hide()
        else:
            self.library.render()
            self._show_overlay(self.library)
        self.titlebar.b_side.setChecked(self.library.isVisible())
        self.layout_stage()

    def toggle_right(self, which: str, tab: int | None = None) -> None:
        panels = {"queue": self.queue_panel, "settings": self.settings, "tracks": self.tracks}
        if self.right_panel == which and (tab is None or which != "tracks" or self.tracks.tabs.current() == tab):
            self.close_right()
            return
        for k, w in panels.items():
            if k != which:
                w.hide()
        self.right_panel = which
        w = panels[which]
        if which == "tracks":
            self.tracks.tabs.set_current(tab if tab is not None else 1, emit=False)
            self.tracks.refresh()
        elif which == "queue":
            self.queue_panel.refresh_queue()
            self._refresh_bookmarks()
            self._refresh_chapters()
        elif which == "settings":
            self.settings.refresh_tracks()
        self._show_overlay(w)
        self._sync_buttons()

    def open_settings_tab(self, i: int) -> None:
        if self.right_panel != "settings":
            self.toggle_right("settings")
        self.settings.tabs.set_current(i)

    def close_right(self) -> None:
        for w in (self.queue_panel, self.settings, self.tracks):
            w.hide()
        self.right_panel = None
        self._sync_buttons()

    def close_overlays(self) -> None:
        self.close_right()
        if self.library.isVisible():
            self.toggle_library()

    def _sync_buttons(self) -> None:
        cb = self.controls
        rp = self.right_panel
        cb.b_queue.set_active(rp == "queue")
        cb.b_settings.set_active(rp == "settings")
        cb.b_tracks.set_active(rp == "tracks" and self.tracks.tabs.current() in (0, 1))
        cb.b_subs.set_active(rp == "tracks" and self.tracks.tabs.current() == 2)

    def _escape(self) -> None:
        if self.isFullScreen():
            self.toggle_fullscreen()
        else:
            self.close_overlays()

    # -- window state ----------------------------------------------------------------
    def toggle_maximized(self) -> None:
        if self.isFullScreen():
            return
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.titlebar.show()
            self.controls.show()
            self._autohide.stop()
            self.showMaximized() if self._was_maximized else self.showNormal()
            self._reapply_native_styles()
        else:
            self._was_maximized = self.isMaximized()
            self.titlebar.hide()
            self.showFullScreen()
            self._idle_ms = 0
            self._autohide.start()
        self.titlebar.b_full.set_icon("unfullscreen" if self.isFullScreen() else "fullscreen")
        QTimer.singleShot(50, self.layout_stage)

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange:
            self.titlebar.b_max.set_icon("restore" if self.isMaximized() else "maximize")
        super().changeEvent(e)

    def _fullscreen_autohide(self) -> None:
        pos = QCursor.pos()
        if pos != self._last_mouse:
            self._last_mouse = pos
            self._idle_ms = 0
            if not self.controls.isVisible():
                self.controls.show()
        else:
            self._idle_ms += 250
        over_controls = self.controls.isVisible() and self.controls.geometry().contains(self.mapFromGlobal(pos))
        if (self._idle_ms > 2500 and self.controls.isVisible() and not over_controls
                and self.right_panel is None and not self.library.isVisible() and self.engine.is_playing()):
            self.controls.hide()

    # frameless-window edge resizing
    def _edges(self, p: QPoint):
        m = 6
        e = Qt.Edges()
        if p.x() <= m:
            e |= Qt.LeftEdge
        if p.x() >= self.width() - m:
            e |= Qt.RightEdge
        if p.y() <= m:
            e |= Qt.TopEdge
        if p.y() >= self.height() - m:
            e |= Qt.BottomEdge
        return e

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.MouseMove, QEvent.MouseButtonPress) and isinstance(obj, QWidget) and obj.window() is self:
            if self.isMaximized() or self.isFullScreen():
                self._clear_edge_cursor()
                return False
            edges = self._edges(self.mapFromGlobal(QCursor.pos()))
            if t == QEvent.MouseButtonPress and edges and ev.button() == Qt.LeftButton:
                self._clear_edge_cursor()
                self.windowHandle().startSystemResize(edges)
                return True
            if edges:
                horiz = bool(edges & (Qt.LeftEdge | Qt.RightEdge))
                vert = bool(edges & (Qt.TopEdge | Qt.BottomEdge))
                if horiz and vert:
                    tl_br = edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge)
                    shape = Qt.SizeFDiagCursor if tl_br else Qt.SizeBDiagCursor
                else:
                    shape = Qt.SizeHorCursor if horiz else Qt.SizeVerCursor
                if self._edge_cursor:
                    QApplication.changeOverrideCursor(shape)
                else:
                    QApplication.setOverrideCursor(shape)
                    self._edge_cursor = True
            else:
                self._clear_edge_cursor()
        return False

    def _clear_edge_cursor(self) -> None:
        if self._edge_cursor:
            QApplication.restoreOverrideCursor()
            self._edge_cursor = False

    # -- opening media ---------------------------------------------------------------
    def open_files(self, enqueue: bool = False) -> None:
        start = self.store.get("last_dir", QStandardPaths.writableLocation(QStandardPaths.MoviesLocation))
        exts = " ".join(f"*{x}" for x in sorted(MEDIA_EXT))
        files, _ = QFileDialog.getOpenFileNames(self, "Open media", start,
                                                f"Media files ({exts});;All files (*.*)")
        if not files:
            return
        self.store.set("last_dir", os.path.dirname(files[0]))
        mrls = [to_mrl(f) for f in files]
        self.enqueue(mrls) if enqueue else self.play_mrls(mrls)

    def open_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Open folder", self.store.get("last_dir", ""))
        if d:
            self.store.set("last_dir", d)
            self.open_paths([d])

    def open_network(self) -> None:
        url, ok = QInputDialog.getText(self, "Open network stream", "URL (http, https, rtsp, udp, …):")
        url = url.strip()
        if ok and url:
            if "://" not in url:
                url = "https://" + url
            streams = self.store.data["streams"]
            if url in streams:
                streams.remove(url)
            streams.insert(0, url)
            self.play_mrls([url])

    def open_subtitle(self) -> None:
        if not self.engine.mrl:
            self.osd("Play something first")
            return
        base = os.path.dirname(mrl_to_path(self.engine.mrl) or "") or self.store.get("last_dir", "")
        f, _ = QFileDialog.getOpenFileName(self, "Add subtitle file", base,
                                           "Subtitles (" + " ".join(f"*{x}" for x in SUB_EXT) + ")")
        if f:
            self._add_subtitle(f)

    def _add_subtitle(self, path: str) -> None:
        self.engine.add_subtitle(to_mrl(path))
        self.osd(f"Subtitle: {os.path.basename(path)}")
        self._load_cues()
        QTimer.singleShot(300, self.tracks._maybe_refresh)

    def open_paths(self, paths: list[str]) -> None:
        media, subs = [], []
        for p in paths:
            if "://" in p and not os.path.exists(p):
                media.append(p)
            elif os.path.isdir(p):
                _, files = scan_folder(p)
                media += [to_mrl(f) for f in files]
            elif os.path.splitext(p)[1].lower() in SUB_EXT:
                subs.append(p)
            elif os.path.isfile(p):
                media.append(to_mrl(p))
        if media:
            self.play_mrls(media)
        for s in subs:
            if self.engine.mrl:
                QTimer.singleShot(400 if media else 0, lambda s=s: self._add_subtitle(s))

    def play_mrls(self, mrls: list[str], start: int = 0) -> None:
        if not mrls:
            return
        self._record_current()
        self.queue.items = [self.queue.make(m) for m in mrls]
        self.queue._played.clear()
        self._parse_durations()
        self.play_index(max(0, min(start, len(mrls) - 1)))

    def enqueue(self, mrls: list[str]) -> None:
        was_empty = not self.queue.items
        self.queue.items += [self.queue.make(m) for m in mrls]
        self._parse_durations()
        self.osd(f"Added {len(mrls)} item{'s' if len(mrls) != 1 else ''} to queue")
        if was_empty:
            self.play_index(0)
        else:
            self.queue_panel.refresh_queue()

    def play_index(self, i: int, resume: bool = True) -> None:
        if not (0 <= i < len(self.queue.items)):
            return
        if self.engine.mrl and i != self.queue.index:
            self._record_current()
        self.queue.index = i
        entry = self.queue.items[i]
        mrl = entry["mrl"]
        start = self.store.resume_point(mrl) if (resume and self.store.get("resume", True)) else 0
        self.settings.reset_for_new_media()
        self.engine.load(mrl, start)
        if start:
            self.osd(f"Resumed at {fmt_short(start)}")
        self.titlebar.set_title(entry["title"])
        self.setWindowTitle(f"{entry['title']} - {APP_TITLE}")
        path = mrl_to_path(mrl)
        self.titlebar.crumb.setText("  " + (os.path.basename(os.path.dirname(path)) if path else "Network"))
        self.controls.seek.chapters = []
        self._last_chapter = -2
        self.video.set_mode("audio", entry["title"])
        self.queue_panel.refresh_queue()
        self._refresh_bookmarks()
        self._load_cues()
        self.store.record(mrl, start, entry.get("duration") or 0)

    def play_queue_id(self, qid: int) -> None:
        i = self.queue.pos_of(qid)
        if i >= 0:
            self.play_index(i)

    # -- transport -----------------------------------------------------------------
    def toggle_play(self) -> None:
        if not self.engine.mrl:
            if self.queue.items:
                self.play_index(max(0, self.queue.index))
            else:
                self.open_files()
            return
        self.engine.toggle()

    def stop(self) -> None:
        self._record_current()
        self.engine.stop()

    def next(self) -> None:
        i = self.queue.next(auto=False)
        if i is not None:
            self.play_index(i)

    def prev(self) -> None:
        if self.engine.time() > 3000:
            self.engine.seek(0)
            return
        i = self.queue.prev()
        if i is not None:
            self.play_index(i)

    def jump(self, ms: int) -> None:
        if self.engine.mrl:
            self.engine.jump(ms)
            self.osd(("+" if ms > 0 else "−") + f"{abs(ms) // 1000}s  ·  {fmt_short(self.engine.time())}")

    def change_volume(self, delta: int) -> None:
        self.engine.set_volume(self.engine.volume() + delta)
        self.osd(f"Volume {self.engine.volume()}%")

    def snapshot(self) -> None:
        if not self.engine.has_video:
            return
        d = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        if self.engine.snapshot(d):
            self.osd(f"Snapshot saved to {d}")

    def _cycle(self, tracks, cur, setter, label):
        if not tracks:
            return
        ids = [t for t, _ in tracks]
        nxt = ids[(ids.index(cur) + 1) % len(ids)] if cur in ids else ids[0]
        setter(nxt)
        self.osd(f"{label}: {dict(tracks)[nxt]}")

    def _cycle_subtitle(self) -> None:
        self._cycle(self.engine.spu_tracks(), self.engine.spu_track(), self.engine.set_spu_track, "Subtitles")

    def _cycle_audio(self) -> None:
        self._cycle(self.engine.audio_tracks(), self.engine.audio_track(), self.engine.set_audio_track, "Audio")

    # -- engine events -------------------------------------------------------------
    def _state_changed(self, state: str) -> None:
        self.controls.b_play.set_playing(state == "playing")
        if state == "error":
            entry = self.queue.current()
            self.osd(f"Couldn't play {entry['title'] if entry else 'media'}")
        if state == "stopped":
            self.video.set_mode("idle")
            self.controls.seek.set_position(0)
            self.controls.t_cur.setText(fmt_time(0))
        if state == "paused":
            self._record_current()

    def _time_changed(self, ms: int) -> None:
        cb = self.controls
        cb.seek.set_position(ms)
        if not cb.seek._drag:
            cb.t_cur.setText(fmt_time(ms))
        ch = self.engine.chapter()
        if ch != self._last_chapter and self.right_panel == "queue":
            self._refresh_chapters()

    def _length_changed(self, ms: int) -> None:
        self.controls.seek.set_length(ms)
        self.controls.t_len.setText(fmt_time(ms))
        entry = self.queue.current()
        if entry and ms > 0 and entry.get("duration", 0) <= 0:
            entry["duration"] = ms
            self.queue_panel.refresh_queue()
        self._refresh_chapters()

    def _vout_changed(self, has_video: bool) -> None:
        entry = self.queue.current()
        self.video.set_mode("video" if has_video else "audio", entry["title"] if entry else "")

    def _volume_changed(self, v: int, muted: bool) -> None:
        self.controls.vol.set_volume(v, muted)
        self.controls.b_mute.set_icon("volume-x" if muted or v == 0 else "volume")

    def _end_reached(self) -> None:
        entry = self.queue.current()
        if entry:
            length = self.engine.length() or entry.get("duration", 0)
            self.store.record(entry["mrl"], length, length)
        if self._stop_after_current:
            self._stop_after_current = False
            self.settings.c_sleep.setCurrentIndex(0)
            QTimer.singleShot(0, self.engine.stop)
            return
        nxt = self.queue.next(auto=True)
        if nxt is None:
            QTimer.singleShot(0, self.engine.stop)
        else:
            QTimer.singleShot(0, lambda: self.play_index(nxt, resume=False))

    def _record_current(self) -> None:
        if self.engine.mrl and self.engine.state in ("playing", "paused"):
            self.store.record(self.engine.mrl, self.engine.time(), self.engine.length())

    # -- queue operations ------------------------------------------------------------
    def queue_sort(self) -> None:
        cur = self.queue.current()
        self.queue.items.sort(key=lambda e: e["title"].lower())
        if cur:
            self.queue.index = self.queue.items.index(cur)
        self.queue_panel.refresh_queue()

    def queue_cycle_repeat(self) -> None:
        self.queue.repeat = {"off": "all", "all": "one", "one": "off"}[self.queue.repeat]
        self.store.set("repeat", self.queue.repeat)
        self.osd(f"Repeat {self.queue.repeat}")
        self.queue_panel.refresh_queue()

    def queue_toggle_shuffle(self) -> None:
        self.queue.shuffle = not self.queue.shuffle
        self.queue._played.clear()
        self.store.set("shuffle", self.queue.shuffle)
        self.osd("Shuffle on" if self.queue.shuffle else "Shuffle off")
        self.queue_panel.refresh_queue()

    def queue_remove(self, ids: list[int]) -> None:
        cur = self.queue.current()
        self.queue.items = [e for e in self.queue.items if e["id"] not in ids]
        if cur and cur["id"] in ids:
            self.queue.index = -1
            self.stop()
            self.engine.mrl = None
            self.titlebar.set_title(APP_TITLE)
        elif cur:
            self.queue.index = self.queue.items.index(cur)
        self.queue_panel.refresh_queue()

    def queue_reorder(self, ids: list[int]) -> None:
        cur = self.queue.current()
        by_id = {e["id"]: e for e in self.queue.items}
        self.queue.items = [by_id[i] for i in ids if i in by_id]
        if cur:
            self.queue.index = self.queue.items.index(cur)
        QTimer.singleShot(0, self.queue_panel.refresh_queue)

    def queue_clear(self) -> None:
        self.queue_remove([e["id"] for e in self.queue.items])

    def save_queue_as_playlist(self) -> None:
        if not self.queue.items:
            self.osd("The queue is empty")
            return
        self.library.create_playlist([e["mrl"] for e in self.queue.items])

    def _parse_durations(self) -> None:
        for e in self.queue.items:
            if not e.get("duration") and e["id"] not in self._parsing and mrl_to_path(e["mrl"]):
                self._parsing[e["id"]] = parse_duration_async(self.engine.instance, e["mrl"])
        if self._parsing:
            self._parse_timer.start()

    def _poll_parsing(self) -> None:
        changed = False
        for qid, media in list(self._parsing.items()):
            d = parsed_duration(media)
            if d is None:
                continue
            self._parsing.pop(qid)
            i = self.queue.pos_of(qid)
            if i >= 0 and d > 0:
                self.queue.items[i]["duration"] = d
                changed = True
            media.release()
        if changed:
            self.queue_panel.refresh_queue()
        if not self._parsing:
            self._parse_timer.stop()

    # -- bookmarks & chapters -----------------------------------------------------
    def _refresh_bookmarks(self) -> None:
        self.queue_panel.refresh_bookmarks(self.store.bookmarks(self.engine.mrl))

    def add_bookmark(self) -> None:
        if not self.engine.mrl:
            return
        marks = self.store.bookmarks(self.engine.mrl)
        t = self.engine.time()
        marks.append({"name": f"Bookmark {len(marks) + 1}", "time": t})
        marks.sort(key=lambda b: b["time"])
        self.store.save()
        self._refresh_bookmarks()
        self.osd(f"Bookmark added at {fmt_short(t)}")

    def remove_bookmark(self, bm: dict) -> None:
        marks = self.store.bookmarks(self.engine.mrl)
        if bm in marks:
            marks.remove(bm)
            self.store.save()
        self._refresh_bookmarks()

    def rename_bookmark(self, bm: dict, name: str) -> None:
        for m in self.store.bookmarks(self.engine.mrl):
            if m == bm:
                m["name"] = name
        self.store.save()
        self._refresh_bookmarks()

    def _refresh_chapters(self) -> None:
        chapters = self.engine.chapters()
        cur = self.engine.chapter()
        self._last_chapter = cur
        self.controls.seek.chapters = [t for _, _, t in chapters if t > 0]
        self.controls.seek.update()
        self.queue_panel.refresh_chapters(chapters, cur)

    # -- playback settings hooks ------------------------------------------------------
    def set_sub_timeline(self, on: bool) -> None:
        self.store.set("sub_timeline", on)
        self._load_cues()

    def _load_cues(self) -> None:
        cues: list[tuple[int, int]] = []
        if self.store.get("sub_timeline", False) and self.engine.mrl:
            cands = [mrl_to_path(u) for u in self.engine.slaves]
            path = mrl_to_path(self.engine.mrl)
            if path:
                base = os.path.splitext(path)[0]
                cands += [base + ".srt", base + ".en.srt"]
            for c in cands:
                if c and c.lower().endswith(".srt") and os.path.isfile(c):
                    cues = parse_srt(c)
                    break
        self.controls.seek.cues = cues
        self.controls.seek.update()

    def set_stats_visible(self, on: bool) -> None:
        if on:
            self._update_stats()
            self._show_overlay(self.stats_panel)
            self._stats_timer.start()
        else:
            self._stats_timer.stop()
            self.stats_panel.hide()
        self.layout_stage()

    def _update_stats(self) -> None:
        e = self.engine
        w, h = e.video_size()
        lines = [f"{'Resolution':<14}{w}x{h}" if w else f"{'Resolution':<14}—",
                 f"{'Frame rate':<14}{e.fps():.2f} fps" if e.fps() else f"{'Frame rate':<14}—"]
        for k, v in e.stats().items():
            lines.append(f"{k:<14}{v}")
        self.stats_panel.set_text("\n".join(lines))

    def set_sleep_timer(self, choice: str) -> None:
        minutes = {"15 minutes": 15, "30 minutes": 30, "45 minutes": 45, "1 hour": 60, "2 hours": 120}
        self._sleep_timer.stop()
        self._stop_after_current = choice == "End of current item"
        if choice in minutes:
            self._sleep_timer.start(minutes[choice] * 60_000)
            self.osd(f"Sleep timer: {choice}")
        elif self._stop_after_current:
            self.osd("Will stop after this item")

    def _sleep_fired(self) -> None:
        self.engine.pause()
        self.settings.c_sleep.setCurrentIndex(0)
        self.osd("Sleep timer: paused")

    # -- OSD / menus -----------------------------------------------------------------
    def osd(self, text: str) -> None:
        self.osd_panel.set_text(text)
        self.layout_stage()
        self._show_overlay(self.osd_panel)
        self._osd_timer.start()

    def show_main_menu(self, pos: QPoint) -> None:
        m = QMenu(self)
        m.addAction("Open File…\tCtrl+O", self.open_files)
        m.addAction("Open Folder…\tCtrl+F", self.open_folder)
        m.addAction("Open Network Stream…\tCtrl+N", self.open_network)
        m.addAction("Add Subtitle File…", self.open_subtitle)
        m.addSeparator()
        act = m.addAction("Stop\tS", self.stop)
        act.setEnabled(bool(self.engine.mrl))
        act = m.addAction("Take Snapshot\tShift+S", self.snapshot)
        act.setEnabled(self.engine.has_video)
        act = m.addAction("Add Bookmark\tCtrl+B", self.add_bookmark)
        act.setEnabled(bool(self.engine.mrl))
        m.addSeparator()
        top = m.addAction("Always on Top")
        top.setCheckable(True)
        top.setChecked(bool(self.windowFlags() & Qt.WindowStaysOnTopHint))
        top.toggled.connect(self._set_on_top)
        m.addAction("Keyboard Shortcuts", self._show_shortcuts)
        m.addAction("About", self._about)
        m.addSeparator()
        m.addAction("Quit\tCtrl+Q", self.close)
        m.exec(pos)

    def _set_on_top(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()
        self._reapply_native_styles()

    def _show_shortcuts(self) -> None:
        QMessageBox.information(self, "Keyboard shortcuts", (
            "Space  Play / pause\nF / F11  Fullscreen     Esc  Exit fullscreen / close panels\n"
            "← →  Seek 10 s     Shift+← →  3 s     Ctrl+← →  1 min\n↑ ↓  Volume     M  Mute\n"
            "N / P  Next / previous     S  Stop     E  Next frame\n[ ]  Slower / faster     =  Normal speed\n"
            "V  Cycle subtitles     B  Cycle audio track     H / J  Subtitle delay\n"
            "Ctrl+O  Open file     Ctrl+F  Open folder     Ctrl+N  Network stream\n"
            "Ctrl+L  Library     Q  Queue     Ctrl+P  Settings     Ctrl+B  Bookmark\nShift+S  Snapshot"))

    def _about(self) -> None:
        from .engine import vlc
        QMessageBox.about(self, "About", (
            "<b>VLC Redesign</b><br>A desktop player built on the 'VLC Redesign' Figma concept.<br><br>"
            f"Playback engine: libVLC {vlc.libvlc_get_version().decode()}<br><br>"
            "Copyright © 2026 satvik1808. Free software under the GNU GPL v3 or later; "
            "there is NO WARRANTY.<br>"
            "<a href='https://github.com/satvik1808/vlc-redesign'>github.com/satvik1808/vlc-redesign</a><br><br>"
            "Not affiliated with VideoLAN. VLC is a trademark of VideoLAN."))

    def _crumb_clicked(self) -> None:
        path = mrl_to_path(self.engine.mrl) if self.engine.mrl else None
        if not self.library.isVisible():
            self.toggle_library()
        if path:
            self.library.open_folder_page(os.path.dirname(path))
        else:
            self.library.go(("videos",))

    # -- drag & drop ---------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = []
        for u in e.mimeData().urls():
            paths.append(u.toLocalFile() if u.isLocalFile() else u.toString())
        subs = [p for p in paths if os.path.splitext(p)[1].lower() in SUB_EXT]
        if subs and len(subs) == len(paths) and self.engine.mrl:
            for s in subs:
                self._add_subtitle(s)
        else:
            self.open_paths(paths)

    # -- persistence ---------------------------------------------------------------
    def _restore(self) -> None:
        st = self.store
        geo = st.get("geometry")
        if geo:
            self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
        else:
            self.resize(1280, 760)
        self.engine.set_volume(st.get("volume", 80))
        self.engine.set_muted(False)
        self.engine.visualizer = st.get("visualizer", "Disabled")
        q = st.data.get("queue", {})
        items = q.get("items", [])
        if items:
            self.queue.items = [self.queue.make(m) for m in items]
            self.queue.index = min(q.get("index", 0), len(items) - 1)
            cur = self.queue.current()
            if cur:
                self.titlebar.set_title(cur["title"])
            self._parse_durations()
        self.queue_panel.refresh_queue()

    def closeEvent(self, e):
        self._record_current()
        st = self.store
        st.set("geometry", bytes(self.saveGeometry().toBase64()).decode())
        st.set("volume", self.engine.volume())
        st.data["queue"] = {"items": [x["mrl"] for x in self.queue.items], "index": self.queue.index}
        try:
            st.save()
        except OSError:
            pass
        self._clear_edge_cursor()
        for t in (self._stats_timer, self._parse_timer, self._history_timer, self._autohide,
                  self._sleep_timer, self._osd_timer):
            t.stop()
        self._parsing.clear()
        self.engine.release()
        super().closeEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        winframe.apply_native_styles(int(self.winId()))
        self.engine.attach(int(self.video.winId()))
        self.layout_stage()

    # -- native window integration (Windows) ------------------------------------------
    def nativeEvent(self, event_type, message):
        res = winframe.handle_top_level(self, message, self._is_caption)
        if res is not None:
            return res
        return super().nativeEvent(event_type, message)

    def _is_caption(self, x: float, y: float) -> bool:
        tb = self.titlebar
        if self.isFullScreen() or not tb.isVisible() or y >= tb.height():
            return False
        child = tb.childAt(int(x), int(y))
        return child is None or child is tb.title or isinstance(child, (ConeLogo, QFrame))

    def _reapply_native_styles(self) -> None:
        QTimer.singleShot(0, lambda: winframe.apply_native_styles(int(self.winId())))

    def paintEvent(self, _):
        QPainter(self).fillRect(self.rect(), QColor(theme.WINDOW))
