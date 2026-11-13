"""Right-hand overlay panels: Queue/Bookmarks/Chapters, Settings (Playback/Video/Audio/Subtitles)
and the Tracks popup (Video/Audio/Subtitles), as laid out in the design."""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFontComboBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu,
    QPushButton, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from . import rows, theme
from .anim import Tween
from .engine import STEREO_MODES, VISUALIZERS, Engine
from .rows import KEY
from .store import fmt_ms, fmt_short, fmt_total, title_of
from .widgets import GoldSlider, IconButton, Panel, Segmented, TabBar, Toggle, dim_label, heading

if TYPE_CHECKING:
    from .mainwindow import MainWindow

FIELD_W = 170


def _divider() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {theme.DIVIDER};")
    return f


def _row(label: str, widget: QWidget, tip: str = "") -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    lab = dim_label(label, 12.5)
    if tip:
        lab.setToolTip(tip)
        widget.setToolTip(tip)
    h.addWidget(lab)
    h.addStretch(1)
    h.addWidget(widget)
    return w


def _combo(items: list[str], current: str | None = None, width: int = FIELD_W) -> QComboBox:
    c = QComboBox()
    c.addItems(items)
    c.setFixedWidth(width)
    c.setCursor(Qt.PointingHandCursor)
    if current and current in items:
        c.setCurrentText(current)
    return c


def _delay_spin() -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setRange(-10.0, 10.0)
    s.setDecimals(3)
    s.setSingleStep(0.05)
    s.setSuffix(" s")
    s.setFixedWidth(FIELD_W)
    s.setAlignment(Qt.AlignLeft)
    return s


def _scroll_page() -> tuple[QScrollArea, QVBoxLayout]:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(18, 14, 18, 18)
    lay.setSpacing(12)
    area.setWidget(inner)
    return area, lay


def _toolbar(label: QLabel, *buttons: QWidget) -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(18, 12, 12, 6)
    h.setSpacing(4)
    h.addWidget(label)
    h.addStretch(1)
    for b in buttons:
        h.addWidget(b)
    return w


# ---------------------------------------------------------------------------
class QueuePanel(Panel):
    """Queue / Bookmarks / Chapters."""

    def __init__(self, app: "MainWindow"):
        super().__init__(app.stage)
        self.app = app
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.setSpacing(0)
        self.tabs = TabBar([("queue", "Queue"), ("bookmark", "Bookmarks"), ("chapters", "Chapters")])
        lay.addWidget(self.tabs)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)

        # Queue ----------------------------------------------------------
        q = QWidget()
        ql = QVBoxLayout(q)
        ql.setContentsMargins(0, 0, 0, 0)
        ql.setSpacing(0)
        self.q_info = dim_label("0 items", 12.5)
        self.b_sort = IconButton("sort", 16, tip="Sort by name")
        self.b_repeat = IconButton("repeat", 16, tip="Repeat: off")
        self.b_shuffle = IconButton("shuffle", 16, tip="Shuffle", checkable=True)
        self.b_qremove = IconButton("minus", 16, tip="Remove selected (Del)")
        self.b_qadd = IconButton("plus", 16, tip="Add files to queue")
        ql.addWidget(_toolbar(self.q_info, self.b_sort, self.b_repeat, self.b_shuffle, self.b_qremove, self.b_qadd))
        self.q_list = rows.make_list(draggable=True)
        self.q_list.setContextMenuPolicy(Qt.CustomContextMenu)
        ql.addWidget(self.q_list, 1)
        self.stack.addWidget(q)

        self.b_sort.clicked.connect(app.queue_sort)
        self.b_repeat.clicked.connect(app.queue_cycle_repeat)
        self.b_shuffle.clicked.connect(app.queue_toggle_shuffle)
        self.b_qremove.clicked.connect(self._remove_selected)
        self.b_qadd.clicked.connect(lambda: app.open_files(enqueue=True))
        self.q_list.itemDoubleClicked.connect(lambda it: app.play_queue_id(it.data(KEY)))
        self.q_list.model().rowsMoved.connect(self._reordered)
        self.q_list.customContextMenuRequested.connect(self._queue_menu)

        # Bookmarks ------------------------------------------------------
        b = QWidget()
        bl = QVBoxLayout(b)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        self.b_info = dim_label("0 Bookmarks", 12.5)
        self.b_bremove = IconButton("minus", 16, tip="Remove selected bookmark")
        self.b_badd = IconButton("plus", 16, tip="Add bookmark at current time (Ctrl+B)")
        bl.addWidget(_toolbar(self.b_info, self.b_bremove, self.b_badd))
        self.b_list = rows.make_list()
        self.b_list.setContextMenuPolicy(Qt.CustomContextMenu)
        bl.addWidget(self.b_list, 1)
        self.b_empty = dim_label("No media playing", 12)
        self.stack.addWidget(b)
        self.b_badd.clicked.connect(app.add_bookmark)
        self.b_bremove.clicked.connect(self._remove_bookmark)
        self.b_list.itemClicked.connect(lambda it: app.engine.seek(it.data(KEY)["time"]))
        self.b_list.itemDoubleClicked.connect(self._rename_bookmark)
        self.b_list.customContextMenuRequested.connect(self._bookmark_menu)

        # Chapters -------------------------------------------------------
        c = QWidget()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(0, 8, 0, 0)
        self.c_list = rows.make_list()
        cl.addWidget(self.c_list, 1)
        self.stack.addWidget(c)
        self.c_list.itemClicked.connect(lambda it: app.engine.set_chapter(it.data(KEY)))

    # queue
    def refresh_queue(self) -> None:
        qq = self.app.queue
        self.q_list.blockSignals(True)
        sel = {it.data(KEY) for it in self.q_list.selectedItems()}
        self.q_list.clear()
        total = 0
        for i, entry in enumerate(qq.items):
            d = entry.get("duration") or 0
            total += max(0, d)
            it = rows.item(entry["title"], icon="grip", right=fmt_short(d) if d > 0 else "",
                           current=(i == qq.index), key=entry["id"])
            self.q_list.addItem(it)
            if entry["id"] in sel:
                it.setSelected(True)
        self.q_list.blockSignals(False)
        n = len(qq.items)
        self.q_info.setText(f"{n} item{'s' if n != 1 else ''}" + (f" - {fmt_total(total)}" if total else ""))
        self.b_repeat.set_icon("repeat-one" if qq.repeat == "one" else "repeat")
        self.b_repeat.set_active(qq.repeat != "off")
        self.b_repeat.setToolTip(f"Repeat: {qq.repeat}")
        self.b_shuffle.setChecked(qq.shuffle)

    def _reordered(self, *_):
        ids = [self.q_list.item(i).data(KEY) for i in range(self.q_list.count())]
        self.app.queue_reorder(ids)

    def _remove_selected(self) -> None:
        ids = [it.data(KEY) for it in self.q_list.selectedItems()]
        if ids:
            self.app.queue_remove(ids)

    def _queue_menu(self, pos) -> None:
        it = self.q_list.itemAt(pos)
        m = QMenu(self)
        if it:
            m.addAction("Play", lambda: self.app.play_queue_id(it.data(KEY)))
            m.addAction("Remove", self._remove_selected)
            m.addSeparator()
        m.addAction("Add files…", lambda: self.app.open_files(enqueue=True))
        m.addAction("Save queue as playlist…", self.app.save_queue_as_playlist)
        m.addAction("Clear queue", self.app.queue_clear)
        m.exec(self.q_list.mapToGlobal(pos))

    # bookmarks
    def refresh_bookmarks(self, marks: list[dict]) -> None:
        self.b_list.clear()
        for bm in marks:
            self.b_list.addItem(rows.item(bm["name"], right=fmt_ms(bm["time"]), key=bm))
        n = len(marks)
        self.b_info.setText(f"{n} Bookmark{'s' if n != 1 else ''}")

    def _remove_bookmark(self) -> None:
        it = self.b_list.currentItem()
        if it:
            self.app.remove_bookmark(it.data(KEY))

    def _rename_bookmark(self, it) -> None:
        bm = it.data(KEY)
        name, ok = QInputDialog.getText(self, "Rename bookmark", "Name:", text=bm["name"])
        if ok and name.strip():
            self.app.rename_bookmark(bm, name.strip())

    def _bookmark_menu(self, pos) -> None:
        it = self.b_list.itemAt(pos)
        if not it:
            return
        m = QMenu(self)
        m.addAction("Go to", lambda: self.app.engine.seek(it.data(KEY)["time"]))
        m.addAction("Rename…", lambda: self._rename_bookmark(it))
        m.addAction("Delete", lambda: self.app.remove_bookmark(it.data(KEY)))
        m.exec(self.b_list.mapToGlobal(pos))

    # chapters
    def refresh_chapters(self, chapters: list[tuple[int, str, int]], current: int) -> None:
        self.c_list.clear()
        if not chapters:
            it = rows.item("This media has no chapters", faint=True)
            it.setFlags(Qt.NoItemFlags)
            self.c_list.addItem(it)
            return
        for i, name, t in chapters:
            self.c_list.addItem(rows.item(name, num=str(i + 1), right=fmt_short(t), current=(i == current), key=i))


# ---------------------------------------------------------------------------
class SettingsPanel(Panel):
    """Playback / Video / Audio / Subtitles preferences."""

    def __init__(self, app: "MainWindow"):
        super().__init__(app.stage)
        self.app = app
        self.engine: Engine = app.engine
        st = app.store
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 6)
        lay.setSpacing(0)
        self.tabs = TabBar([("playback", "Playback"), ("video-tab", "Video"), ("waveform", "Audio"), ("subtitles", "Subtitles")])
        lay.addWidget(self.tabs)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)
        self._reopen_timer = QTimer(self, singleShot=True, interval=350, timeout=self.engine.reopen)

        # Playback ---------------------------------------------------------
        page, v = _scroll_page()
        self.t_cues = Toggle(st.get("sub_timeline", False))
        self.t_stats = Toggle(False)
        self.t_reverse = Toggle(False)
        self.t_reverse.setEnabled(False)
        self.t_resume = Toggle(st.get("resume", True))
        v.addWidget(_row("Show Subtitle Timeline on Seekbar", self.t_cues,
                         "Marks subtitle cues from external .srt files on the seek bar"))
        v.addWidget(_row("Show Statistics", self.t_stats))
        v.addWidget(_row("Reverse", self.t_reverse, "Reverse playback is not supported by libVLC 3"))
        v.addWidget(_row("Resume Where I Left Off", self.t_resume))
        self.c_sleep = _combo(["Off", "15 minutes", "30 minutes", "45 minutes", "1 hour", "2 hours", "End of current item"])
        v.addWidget(_row("Sleep Timer", self.c_sleep))
        self.c_vis = _combo(list(VISUALIZERS), st.get("visualizer", "Disabled"))
        v.addWidget(_row("Audio Visualizer", self.c_vis, "Shown while playing audio-only media"))
        self.speed_lab = QLabel("1x")
        self.speed_lab.setFixedWidth(110)
        self.speed_lab.setStyleSheet(f"background:{theme.FIELD}; border-radius:4px; padding:6px 10px;")
        v.addWidget(_row("Speed", self.speed_lab))
        stops = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2]
        self.s_speed = GoldSlider(0.25, 2.0, 1.0, ticks=stops, labels=[(s, f"{s:g}") for s in stops], step=0.05)
        v.addWidget(self.s_speed)
        v.addStretch(1)
        self.stack.addWidget(page)

        self.t_cues.toggled.connect(app.set_sub_timeline)
        self.t_stats.toggled.connect(app.set_stats_visible)
        self.t_resume.toggled.connect(lambda on: st.set("resume", on))
        self.c_sleep.currentTextChanged.connect(app.set_sleep_timer)
        self.c_vis.currentTextChanged.connect(self._set_visualizer)
        self.s_speed.valueChanged.connect(self.engine.set_rate)
        self.engine.rateChanged.connect(self._rate_changed)

        # Video ------------------------------------------------------------
        page, v = _scroll_page()
        v.addWidget(heading("Defaults"))
        v.addWidget(dim_label("Flip", 12.5))
        self.seg_flip = Segmented(["None", "Horizontal", "Vertical"])
        v.addWidget(self.seg_flip)
        self.sp_rot = QSpinBox()
        self.sp_rot.setRange(0, 359)
        self.sp_rot.setSingleStep(90)
        self.sp_rot.setWrapping(True)
        self.sp_rot.setSuffix(" deg")
        self.sp_rot.setFixedWidth(FIELD_W)
        v.addWidget(_row("Rotate", self.sp_rot, "Steps of 90° use the fast transform filter"))
        self.zooms = {"Fit to Window": 0.0, "1:4 Quarter": 0.25, "1:2 Half": 0.5, "1:1 Original": 1.0, "2:1 Double": 2.0}
        self.c_zoom = _combo(list(self.zooms))
        v.addWidget(_row("Zoom", self.c_zoom))
        aspects = ["Default", "16:9", "4:3", "1:1", "16:10", "2.21:1", "2.35:1", "2.39:1", "5:4"]
        self.c_aspect = _combo(aspects)
        v.addWidget(_row("Aspect Ratio", self.c_aspect))
        crops = ["Default", "16:10", "16:9", "4:3", "1.85:1", "2.21:1", "2.35:1", "2.39:1", "5:3", "5:4", "1:1"]
        self.c_crop = _combo(crops)
        v.addWidget(_row("Crop", self.c_crop))
        self.deint = {"Off": None, "Blend": "blend", "Bob": "bob", "Linear": "linear", "X": "x",
                      "Yadif": "yadif", "Yadif (2x)": "yadif2x", "Phosphor": "phosphor"}
        self.c_deint = _combo(list(self.deint))
        v.addWidget(_row("Deinterlace", self.c_deint))
        v.addWidget(_divider())
        v.addWidget(heading("Image Adjustments"))
        self.adj = {}
        for name, lo, hi, origin in (("Brightness", 0, 2, 1), ("Contrast", 0, 2, 1), ("Saturation", 0, 3, 1),
                                     ("Hue", -180, 180, 0), ("Gamma", 0.1, 3, 1)):
            v.addWidget(dim_label(name, 12.5))
            s = GoldSlider(lo, hi, origin, origin=origin)
            s.setToolTip("Double-click to reset")
            s.valueChanged.connect(self._apply_adjust)
            self.adj[name] = s
            v.addWidget(s)
        reset = QPushButton("Reset adjustments")
        reset.clicked.connect(self._reset_adjust)
        v.addWidget(reset)
        v.addStretch(1)
        self.stack.addWidget(page)

        self.seg_flip.changed.connect(self._set_flip)
        self.sp_rot.valueChanged.connect(self._set_rotate)
        self.c_zoom.currentTextChanged.connect(lambda t: self.engine.set_scale(self.zooms[t]))
        self.c_aspect.currentTextChanged.connect(lambda t: self.engine.set_aspect(None if t == "Default" else t))
        self.c_crop.currentTextChanged.connect(lambda t: self.engine.set_crop(None if t == "Default" else t))
        self.c_deint.currentTextChanged.connect(lambda t: self.engine.set_deinterlace(self.deint[t]))

        # Audio ------------------------------------------------------------
        page, v = _scroll_page()
        v.addWidget(heading("Defaults"))
        self.c_atrack = _combo([])
        v.addWidget(_row("Audio Track", self.c_atrack))
        self.c_stereo = _combo(list(STEREO_MODES))
        v.addWidget(_row("Stereo Mode", self.c_stereo))
        v.addWidget(_divider())
        v.addWidget(heading("Synchronization"))
        self.sp_adelay = _delay_spin()
        v.addWidget(_row("Audio Track Delay", self.sp_adelay))
        self.s_adelay = GoldSlider(-10, 10, 0, origin=0, labels=[(-10, "-10 s"), (0, "0 s"), (10, "+10 s")], step=0.05)
        v.addWidget(self.s_adelay)
        v.addWidget(_divider())
        v.addWidget(heading("Filters"))
        v.addWidget(dim_label("Equalizer", 12.5))
        self.c_eq = QComboBox()
        self.c_eq.addItems(["None", *Engine.eq_presets()])
        v.addWidget(self.c_eq)
        self.b_expand = QPushButton("Expand Settings  ›")
        self.b_expand.setCheckable(True)
        self.b_expand.setStyleSheet("text-align:left; padding:8px 10px;")
        v.addWidget(self.b_expand)
        self.eq_box = QWidget()
        eqv = QVBoxLayout(self.eq_box)
        eqv.setContentsMargins(0, 0, 0, 0)
        eqv.setSpacing(2)
        self.eq_sliders: list[GoldSlider] = []
        labels = ["Preamp"] + [(f"{f / 1000:g} kHz" if f >= 1000 else f"{f:g} Hz") for f in Engine.eq_bands()]
        for lab in labels:
            row = QWidget()
            rh = QHBoxLayout(row)
            rh.setContentsMargins(0, 0, 0, 0)
            l = dim_label(lab, 11.5)
            l.setFixedWidth(64)
            s = GoldSlider(-20, 20, 0, origin=0, step=0.5)
            s.setToolTip("dB, double-click to reset")
            s.valueChanged.connect(self._eq_custom)
            rh.addWidget(l)
            rh.addWidget(s, 1)
            eqv.addWidget(row)
            self.eq_sliders.append(s)
        self.eq_box.setVisible(False)
        v.addWidget(self.eq_box)
        v.addStretch(1)
        self.stack.addWidget(page)

        self.c_atrack.activated.connect(lambda i: self.engine.set_audio_track(self.c_atrack.itemData(i)))
        self.c_stereo.currentTextChanged.connect(self.engine.set_stereo_mode)
        self.sp_adelay.valueChanged.connect(self._set_adelay)
        self.s_adelay.valueChanged.connect(lambda v_: self.sp_adelay.setValue(v_))
        self.c_eq.currentIndexChanged.connect(self._set_eq_preset)
        self.b_expand.toggled.connect(self._toggle_eq)

        # Subtitles --------------------------------------------------------
        page, v = _scroll_page()
        v.addWidget(heading("Defaults"))
        self.c_strack = _combo([])
        v.addWidget(_row("Subtitle Track", self.c_strack))
        add_sub = QPushButton("Add subtitle file…")
        add_sub.clicked.connect(app.open_subtitle)
        v.addWidget(add_sub)
        v.addWidget(_divider())
        v.addWidget(heading("Synchronization"))
        self.sp_sdelay = _delay_spin()
        v.addWidget(_row("Subtitle Track Delay", self.sp_sdelay))
        self.s_sdelay = GoldSlider(-10, 10, 0, origin=0, labels=[(-10, "-10 s"), (0, "0 s"), (10, "+10 s")], step=0.05)
        v.addWidget(self.s_sdelay)
        v.addWidget(_divider())
        v.addWidget(heading("Appearance"))
        v.addWidget(dim_label("Applied the next time the player starts.", 11, theme.TEXT_FAINT))
        self.c_font = QFontComboBox()
        self.c_font.setFixedWidth(FIELD_W)
        self.c_font.setCurrentFont(QFont(st.get("sub_font", "Inter")))
        v.addWidget(_row("Subtitle Font", self.c_font))
        self.sizes = {"Smaller": 20, "Small": 18, "Normal": 16, "Large": 12, "Larger": 6}
        self.c_size = _combo(list(self.sizes), st.get("sub_size", "Normal"))
        v.addWidget(_row("Subtitle Size", self.c_size))
        self.colors = {"White": 0xFFFFFF, "Yellow": 0xFFFF00, "Light grey": 0xC0C0C0, "Cyan": 0x00FFFF, "Orange": 0xE8891F}
        self.c_color = _combo(list(self.colors), st.get("sub_color", "White"))
        v.addWidget(_row("Text Color", self.c_color))
        self.t_outline = Toggle(st.get("sub_bg", False))
        v.addWidget(_row("Background Box", self.t_outline))
        v.addStretch(1)
        self.stack.addWidget(page)

        self.c_strack.activated.connect(lambda i: self.engine.set_spu_track(self.c_strack.itemData(i)))
        self.sp_sdelay.valueChanged.connect(self._set_sdelay)
        self.s_sdelay.valueChanged.connect(lambda v_: self.sp_sdelay.setValue(v_))
        self.c_font.currentFontChanged.connect(lambda f: st.set("sub_font", f.family()))
        self.c_size.currentTextChanged.connect(lambda t: st.set("sub_size", t))
        self.c_color.currentTextChanged.connect(lambda t: st.set("sub_color", t))
        self.t_outline.toggled.connect(lambda on: st.set("sub_bg", on))

        self.engine.tracksChanged.connect(self.refresh_tracks)

    # playback
    def _rate_changed(self, r: float) -> None:
        self.speed_lab.setText(f"{r:g}x")
        if abs(self.s_speed.value() - r) > 1e-3:
            self.s_speed.set_value(r)

    def _set_visualizer(self, name: str) -> None:
        self.engine.visualizer = name
        self.app.store.set("visualizer", name)
        if self.engine.mrl and not self.engine.has_video:
            self._reopen_timer.start()

    # video
    def _set_flip(self, i: int) -> None:
        self.engine.flip = ["none", "h", "v"][i]
        self._reopen_timer.start()

    def _set_rotate(self, deg: int) -> None:
        self.engine.rotate = deg
        self._reopen_timer.start()

    def _apply_adjust(self, *_):
        a = self.adj
        self.engine.set_adjust(a["Brightness"].value(), a["Contrast"].value(), a["Saturation"].value(),
                               a["Hue"].value(), a["Gamma"].value())

    def _reset_adjust(self) -> None:
        for s in self.adj.values():
            s.set_value(s.origin)
        self._apply_adjust()

    # audio
    def _set_adelay(self, v: float) -> None:
        self.engine.set_audio_delay(v)
        if abs(self.s_adelay.value() - v) > 1e-3:
            self.s_adelay.set_value(v)

    def _set_eq_preset(self, i: int) -> None:
        pre, bands = self.engine.set_eq_preset(None if i == 0 else i - 1)
        for s, val in zip(self.eq_sliders, [pre, *bands]):
            s.set_value(val)

    def _eq_custom(self, *_):
        vals = [s.value() for s in self.eq_sliders]
        self.engine.set_eq_values(vals[0], vals[1:])

    def _toggle_eq(self, on: bool) -> None:
        self.b_expand.setText("Collapse Settings  ⌄" if on else "Expand Settings  ›")
        box = self.eq_box
        if not hasattr(self, "_eq_t"):
            self._eq_t = Tween(box, 0.0, 240, on_step=self._eq_step)
        if not self.isVisible():
            box.setVisible(on)
            box.setMaximumHeight(16777215)
            self._eq_t.snap(1.0 if on else 0.0)
            return
        if on and not box.isVisible():
            box.setMaximumHeight(0)
            box.setVisible(True)
        self._eq_full = max(1, box.sizeHint().height())
        self._eq_t.to(1.0 if on else 0.0)

    def _eq_step(self, t: float) -> None:
        box = self.eq_box
        if t >= 1.0:
            box.setMaximumHeight(16777215)          # done expanding: let it size naturally
        elif t <= 0.0:
            box.setVisible(False)
            box.setMaximumHeight(16777215)
        else:
            box.setMaximumHeight(round(getattr(self, "_eq_full", box.sizeHint().height()) * t))

    # subtitles
    def _set_sdelay(self, v: float) -> None:
        self.engine.set_spu_delay(v)
        if abs(self.s_sdelay.value() - v) > 1e-3:
            self.s_sdelay.set_value(v)

    def reset_for_new_media(self) -> None:
        for sp in (self.sp_adelay, self.sp_sdelay):
            sp.blockSignals(True)
            sp.setValue(0)
            sp.blockSignals(False)
        self.s_adelay.set_value(0)
        self.s_sdelay.set_value(0)
        self.c_stereo.setCurrentIndex(0)

    def refresh_tracks(self) -> None:
        for combo, tracks, cur in (
            (self.c_atrack, self.engine.audio_tracks(), self.engine.audio_track()),
            (self.c_strack, self.engine.spu_tracks(), self.engine.spu_track()),
        ):
            combo.blockSignals(True)
            combo.clear()
            for tid, name in tracks:
                combo.addItem(name, tid)
                if tid == cur:
                    combo.setCurrentIndex(combo.count() - 1)
            if not tracks:
                combo.addItem("None", -1)
            combo.blockSignals(False)


def subtitle_args_from_store(store) -> list[str]:
    sizes = {"Smaller": 20, "Small": 18, "Normal": 16, "Large": 12, "Larger": 6}
    colors = {"White": 0xFFFFFF, "Yellow": 0xFFFF00, "Light grey": 0xC0C0C0, "Cyan": 0x00FFFF, "Orange": 0xE8891F}
    args = [f"--freetype-rel-fontsize={sizes.get(store.get('sub_size', 'Normal'), 16)}",
            f"--freetype-color={colors.get(store.get('sub_color', 'White'), 0xFFFFFF)}"]
    if store.get("sub_font"):
        args.append(f"--freetype-font={store.get('sub_font')}")
    if store.get("sub_bg", False):
        args.append("--freetype-background-opacity=160")
    return args


# ---------------------------------------------------------------------------
class TracksPopup(Panel):
    """Quick track picker opened from the waveform / subtitles buttons."""
    closed = Signal()

    def __init__(self, app: "MainWindow"):
        super().__init__(app.stage)
        self.app = app
        self.engine: Engine = app.engine
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 8)
        lay.setSpacing(0)
        self.tabs = TabBar([("video-tab", "Video"), ("waveform", "Audio"), ("subtitles", "Subtitles")])
        lay.addWidget(self.tabs)
        self.list = rows.make_list()
        lay.addWidget(self.list, 1)
        self.pref = QPushButton("Show Preferences")
        self.pref.setStyleSheet(f"background:{theme.WINDOW}; border:none; color:{theme.TEXT_DIM}; padding:9px;")
        self.pref.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.pref)
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        self.list.itemClicked.connect(self._clicked)
        self.pref.clicked.connect(lambda: app.open_settings_tab([1, 2, 3][self.tabs.current()]))
        self.engine.tracksChanged.connect(self._maybe_refresh)

    def _maybe_refresh(self) -> None:
        if self.isVisible():
            self.refresh()

    def _section(self, text: str, actions: list[tuple[str, str]] | None = None) -> None:
        it = rows.item(text, header=True)
        self.list.addItem(it)
        if actions:
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 6, 8, 0)
            h.addStretch(1)
            for ic, act in actions:
                b = IconButton(ic, 15, tip={"add": "Add subtitle file", "edit": "Subtitle preferences",
                                             "refresh": "Refresh devices"}[act])
                b.clicked.connect(lambda _=False, a=act: self._action(a))
                h.addWidget(b)
            self.list.setItemWidget(it, w)

    def _action(self, act: str) -> None:
        if act == "add":
            self.app.open_subtitle()
        elif act == "edit":
            self.app.open_settings_tab(3)
        elif act == "refresh":
            self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        tab = self.tabs.current()
        e = self.engine
        if tab == 0:
            self._section("Embedded Tracks")
            tracks, cur = e.video_tracks(), e.video_track()
            for tid, name in tracks or [(-1, "None")]:
                self.list.addItem(rows.item(name, check=True, current=(tid == cur), key=("v", tid)))
        elif tab == 1:
            self._section("Embedded Tracks")
            tracks, cur = e.audio_tracks(), e.audio_track()
            for tid, name in tracks or [(-1, "None")]:
                self.list.addItem(rows.item(name, check=True, current=(tid == cur), key=("a", tid)))
            self._section("Output Device", [("refresh", "refresh")])
            cur_dev = e.output_device()
            for dev, desc in e.output_devices():
                self.list.addItem(rows.item(desc, check=True, current=(dev == cur_dev), key=("d", dev)))
        else:
            self._section("Embedded Tracks")
            tracks, cur = e.spu_tracks(), e.spu_track()
            for tid, name in tracks or [(-1, "None")]:
                self.list.addItem(rows.item(name, check=True, current=(tid == cur), key=("s", tid)))
            self._section("External Tracks", [("pencil", "edit"), ("plus", "add")])
            for uri in e.slaves:
                self.list.addItem(rows.item(title_of(uri), check=True, key=None))
            if not e.slaves:
                self.list.addItem(rows.item("Drop a subtitle file on the player or press +", faint=True))

    def _clicked(self, it) -> None:
        key = it.data(KEY)
        if not key:
            return
        kind, val = key
        if kind == "v":
            self.engine.set_video_track(val)
        elif kind == "a":
            self.engine.set_audio_track(val)
        elif kind == "s":
            self.engine.set_spu_track(val)
        elif kind == "d":
            self.engine.set_output_device(val)
        QTimer.singleShot(120, self.refresh)
