"""Left library sidebar: icon rail + browsable panel (Home, Videos, Music, Network,
Playlists, History), with back/forward navigation, sort and search."""
from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QFileInfo, QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QPushButton, QVBoxLayout, QWidget,
)

from . import rows, theme
from .rows import KEY
from .store import AUDIO_EXT, MEDIA_EXT, fmt_short, kind_of, mrl_to_path, title_of, to_mrl
from .widgets import IconButton, Panel, dim_label

if TYPE_CHECKING:
    from .mainwindow import MainWindow

RAIL_W = 40
PANEL_W = 300          # default width of the browsable panel (right of the rail)
PANEL_MIN_W = 220
PANEL_MAX_W = 900
MIN_VIDEO_W = 240      # keep at least this much of the stage visible beside the library
OPACITY = 0.84         # library pane translucency over the video


class _ResizeGrip(QWidget):
    """Thin handle on the library's right edge; drag to resize, double-click to reset."""

    W = 6

    def __init__(self, lib: "Library"):
        super().__init__(lib)
        self.lib = lib
        self.setCursor(Qt.SizeHorCursor)
        self.setToolTip("Drag to resize  ·  double-click to reset")
        self._drag = False
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = True
            self.update()

    def mouseMoveEvent(self, e):
        if self._drag:
            x = self.lib.mapFromGlobal(e.globalPosition().toPoint()).x()
            self.lib.set_panel_width(x - RAIL_W)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.update()
            self.lib.store.save()

    def mouseDoubleClickEvent(self, e):
        self.lib.set_panel_width(PANEL_W)
        self.lib.store.save()

    def paintEvent(self, _):
        if self._hover or self._drag:
            p = QPainter(self)
            c = QColor(theme.ACCENT)
            c.setAlpha(255 if self._drag else 140)
            p.fillRect(self.width() - 2, 0, 2, self.height(), c)


def fmt_size(n: int) -> str:
    if n <= 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def scan_folder(path: str) -> tuple[list[str], list[str]]:
    dirs, files = [], []
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith((".", "$")):
                    continue
                try:
                    if e.is_dir():
                        dirs.append(e.path)
                    elif os.path.splitext(e.name)[1].lower() in MEDIA_EXT:
                        files.append(e.path)
                except OSError:
                    pass
    except OSError:
        pass
    key = lambda p: os.path.basename(p).lower()  # noqa: E731
    return sorted(dirs, key=key), sorted(files, key=key)


class Library(Panel):
    def __init__(self, app: "MainWindow"):
        super().__init__(app.stage, radius=0, color=theme.PANEL)
        self.app = app
        self.store = app.store
        self.page: tuple = ("home",)
        self.back_stack: list[tuple] = []
        self.fwd_stack: list[tuple] = []
        self.sort_desc = False
        self.details = True
        self.grip = _ResizeGrip(self)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # rail ---------------------------------------------------------------
        rail = QWidget()
        rail.setFixedWidth(RAIL_W)
        rail.setAutoFillBackground(True)
        rail.setStyleSheet(f"background: {theme.RAIL};")
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(2, 8, 2, 8)
        rl.setSpacing(4)
        self.rail_group = QButtonGroup(self)
        self.rail_btns = {}
        for key, ic, tip in (("home", "home", "Home"), ("videos", "videos", "Videos"), ("music", "music", "Music"),
                             ("network", "network", "Network streams"), ("playlists", "playlist", "Playlists"),
                             ("history", "history", "History")):
            b = IconButton(ic, 17, 36, tip, checkable=True)
            self.rail_group.addButton(b)
            self.rail_btns[key] = b
            b.clicked.connect(lambda _=False, k=key: self.go((k,)))
            rl.addWidget(b, 0, Qt.AlignHCenter)
        add = IconButton("plus", 17, 36, "Add a folder to the library")
        add.clicked.connect(self.add_folder)
        rl.addWidget(add, 0, Qt.AlignHCenter)
        rl.addStretch(1)
        outer.addWidget(rail)

        # content ----------------------------------------------------------
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(2)
        self.b_back = IconButton("arrow-left", 17, tip="Back")
        self.b_fwd = IconButton("arrow-right", 17, tip="Forward")
        self.title = QLabel("Home")
        self.title.setStyleSheet(f"color:{theme.TEXT}; font-size:14px; padding-left:6px;")
        self.b_more = IconButton("more", 16, tip="More")
        self.b_ext = IconButton("external", 16, tip="Show in File Explorer")
        head.addWidget(self.b_back)
        head.addWidget(self.b_fwd)
        head.addWidget(self.title, 1)
        head.addWidget(self.b_more)
        head.addWidget(self.b_ext)
        bl.addLayout(head)

        sub = QHBoxLayout()
        sub.setContentsMargins(6, 6, 0, 6)
        self.count = dim_label("", 12)
        self.b_sort = IconButton("sort", 16, tip="Sort A–Z / Z–A")
        self.b_view = IconButton("view", 16, tip="Show / hide details", checkable=True)
        self.b_view.setChecked(True)
        self.b_search = IconButton("search", 16, tip="Search (Ctrl+F in library)", checkable=True)
        sub.addWidget(self.count, 1)
        sub.addWidget(self.b_sort)
        sub.addWidget(self.b_view)
        sub.addWidget(self.b_search)
        bl.addLayout(sub)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter…")
        self.search.setClearButtonEnabled(True)
        self.search.hide()
        bl.addWidget(self.search)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{theme.DIVIDER}; margin: 4px 0;")
        bl.addWidget(line)

        # network URL entry (only on the Network page)
        self.net = QWidget()
        nl = QHBoxLayout(self.net)
        nl.setContentsMargins(0, 8, 0, 4)
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…, rtsp://…, udp://…")
        go = QPushButton("Play")
        nl.addWidget(self.url, 1)
        nl.addWidget(go)
        self.net.hide()
        bl.addWidget(self.net)
        go.clicked.connect(self._play_url)
        self.url.returnPressed.connect(self._play_url)

        self.list = rows.make_list()
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        bl.addWidget(self.list, 1)
        outer.addWidget(body, 1)

        self.b_back.clicked.connect(self.back)
        self.b_fwd.clicked.connect(self.forward)
        self.b_sort.clicked.connect(self._toggle_sort)
        self.b_view.toggled.connect(self._toggle_view)
        self.b_search.toggled.connect(self._toggle_search)
        self.search.textChanged.connect(self._filter)
        self.b_more.clicked.connect(self._more_menu)
        self.b_ext.clicked.connect(self._open_external)
        self.list.itemClicked.connect(self._activate)
        self.list.customContextMenuRequested.connect(self._context)

    # navigation ------------------------------------------------------------
    def go(self, page: tuple, push: bool = True) -> None:
        if push and page != self.page:
            self.back_stack.append(self.page)
            self.fwd_stack.clear()
        self.page = page
        self.render()

    def back(self) -> None:
        if self.back_stack:
            self.fwd_stack.append(self.page)
            self.page = self.back_stack.pop()
            self.render()

    def forward(self) -> None:
        if self.fwd_stack:
            self.back_stack.append(self.page)
            self.page = self.fwd_stack.pop()
            self.render()

    def open_folder_page(self, path: str) -> None:
        kind = "music" if self._is_music_path(path) else "videos"
        self.go(("folder", path, kind))

    def _is_music_path(self, path: str) -> bool:
        norm = os.path.normcase(os.path.abspath(path))
        return any(norm.startswith(os.path.normcase(os.path.abspath(f))) for f in self.store.data["folders"]["music"])

    # rendering ---------------------------------------------------------------
    # -- translucency -----------------------------------------------------------------
    def set_opacity(self, alpha: float) -> None:
        """Whole-pane opacity (0..1). The pane is a native child window sitting over libVLC's
        video window, so Qt's own opacity can't blend it; use a layered child window instead."""
        if sys.platform != "win32":
            return
        import ctypes
        u32 = ctypes.windll.user32
        u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        h = int(self.winId())
        ex = u32.GetWindowLongPtrW(h, -20)            # GWL_EXSTYLE
        if not ex & 0x80000:                            # WS_EX_LAYERED
            u32.SetWindowLongPtrW(h, -20, ctypes.c_ssize_t(ex | 0x80000))
        u32.SetLayeredWindowAttributes(h, 0, max(0, min(255, round(alpha * 255))), 2)  # LWA_ALPHA

    # -- width ---------------------------------------------------------------------
    def total_width(self, stage_w: int) -> int:
        """Rail + panel width to use on a stage of the given width (saved width, clamped)."""
        w = int(self.store.get("library_width", PANEL_W) or PANEL_W)
        hi = min(PANEL_MAX_W, stage_w - RAIL_W - MIN_VIDEO_W)
        return RAIL_W + max(PANEL_MIN_W, min(w, hi))

    def set_panel_width(self, w: int) -> None:
        stage_w = self.parentWidget().width()
        hi = max(PANEL_MIN_W, min(PANEL_MAX_W, stage_w - RAIL_W - MIN_VIDEO_W))
        self.store.set("library_width", max(PANEL_MIN_W, min(int(w), hi)))
        self.app.layout_stage()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.grip.setGeometry(self.width() - _ResizeGrip.W, 0, _ResizeGrip.W, self.height())
        self.grip.raise_()

    def render(self) -> None:
        kind = self.page[0]
        rail_key = {"folder": self.page[2] if len(self.page) > 2 else "videos", "playlist": "playlists"}.get(kind, kind)
        if rail_key in self.rail_btns:
            self.rail_btns[rail_key].setChecked(True)
        self.b_back.setEnabled(bool(self.back_stack))
        self.b_fwd.setEnabled(bool(self.fwd_stack))
        self.b_ext.setVisible(kind in ("folder", "videos", "music"))
        self.net.setVisible(kind == "network")
        self.list.clear()
        n = getattr(self, f"_page_{kind}")()
        self.count.setText(f"{n} item{'s' if n != 1 else ''}")
        self._filter(self.search.text())

    def _add(self, text: str, **kw) -> None:
        if not self.details:
            kw.pop("right", None)
            kw.pop("sub", None)
            kw.pop("thumb", None)
        self.list.addItem(rows.item(text, **kw))

    def _sorted(self, seq, key):
        return sorted(seq, key=key, reverse=self.sort_desc)

    def _page_home(self) -> int:
        self.title.setText("Home")
        st = self.store
        n = 0
        cw = st.continue_watching()[:3]
        self._add("Continue Watching", header=True, key=("history",))
        for h in cw:
            self._add(h["title"], icon="film", right=f"{fmt_short(h['position'])} / {fmt_short(h['length'])}",
                      key=("media", h["mrl"]), thumb=mrl_to_path(h["mrl"]))
        if not cw:
            self._add("Nothing in progress", faint=True)
        n += len(cw)
        audio = [h for h in st.data["history"] if h["kind"] == "audio"][:3]
        self._add("Listen Again", header=True, key=("music",))
        for h in audio:
            self._add(h["title"], icon="note", key=("media", h["mrl"]), thumb=mrl_to_path(h["mrl"]))
        if not audio:
            self._add("No recent music", faint=True)
        n += len(audio)
        visits = sorted(st.data["folder_visits"].items(), key=lambda kv: -kv[1])
        folders = [p for p, _ in visits if os.path.isdir(p)][:3] or (st.data["folders"]["video"] + st.data["folders"]["music"])[:3]
        self._add("Frequently Visited Folders", header=True, key=("videos",))
        for p in folders:
            self._add(os.path.basename(p) or p, icon="folder", key=("folder", p))
        n += len(folders)
        pls = sorted(st.data["playlists"], key=lambda name: -st.data["playlist_visits"].get(name, 0))[:3]
        self._add("Frequently Visited Playlists", header=True, key=("playlists",))
        for name in pls:
            self._add(name, icon="playlist", key=("playlist", name))
        if not pls:
            self._add("No playlists yet", faint=True)
        n += len(pls)
        return n

    def _roots(self, kind: str) -> int:
        st = self.store
        key = "video" if kind == "videos" else "music"
        self.title.setText("Videos" if kind == "videos" else "Music")
        self._add("Add", icon="plus", faint=True, key=("add-folder", key))
        roots = st.data["folders"][key]
        for p in self._sorted(roots, key=lambda p: os.path.basename(p).lower()):
            self._add(os.path.basename(p) or p, icon="folder", key=("folder", p), sub=p if self.details else None)
        return len(roots)

    def _page_videos(self) -> int:
        return self._roots("videos")

    def _page_music(self) -> int:
        return self._roots("music")

    def _page_folder(self) -> int:
        path = self.page[1]
        self.title.setText(os.path.basename(path) or path)
        self.store.visit_folder(path)
        dirs, files = scan_folder(path)
        key = lambda p: os.path.basename(p).lower()  # noqa: E731
        for d in self._sorted(dirs, key):
            self._add(os.path.basename(d), icon="folder", key=("folder", d))
        if files:
            self._add("Play all", icon="playback", faint=True, key=("play-all", path))
        for f in self._sorted(files, key):
            ext = os.path.splitext(f)[1].lower()
            self._add(os.path.basename(f), icon="note" if ext in AUDIO_EXT else "film",
                      right=fmt_size(QFileInfo(f).size()), key=("file", f), thumb=f)
        return len(dirs) + len(files)

    def _page_network(self) -> int:
        self.title.setText("Network")
        streams = self.store.data["streams"]
        self._add("Recent Streams", header=True)
        for u in streams:
            self._add(u, icon="link", key=("media", u))
        if not streams:
            self._add("Enter a URL above to play a stream", faint=True)
        return len(streams)

    def _page_playlists(self) -> int:
        self.title.setText("Playlists")
        self._add("Create playlist", icon="plus", faint=True, key=("new-playlist",))
        names = self._sorted(self.store.data["playlists"], key=str.lower)
        for name in names:
            cnt = len(self.store.data["playlists"][name])
            self._add(name, icon="playlist", right=f"{cnt} item{'s' if cnt != 1 else ''}", key=("playlist", name))
        return len(names)

    def _page_playlist(self) -> int:
        name = self.page[1]
        self.title.setText(name)
        self.store.visit_playlist(name)
        items = self.store.data["playlists"].get(name, [])
        if items:
            self._add("Play all", icon="playback", faint=True, key=("play-playlist", name))
        for i, mrl in enumerate(items):
            self._add(title_of(mrl), icon="note" if kind_of(mrl) == "audio" else "film", key=("pl-item", name, i),
                      thumb=mrl_to_path(mrl))
        return len(items)

    def _page_history(self) -> int:
        self.title.setText("History")
        hist = self.store.data["history"]
        if hist:
            self._add("Clear history", icon="trash", faint=True, key=("clear-history",))
        for h in hist:
            right = f"{fmt_short(h['position'])} / {fmt_short(h['length'])}" if h.get("length") else ""
            self._add(h["title"], icon={"audio": "note", "video": "film"}.get(h["kind"], "link"),
                      right=right, key=("media", h["mrl"]), thumb=mrl_to_path(h["mrl"]))
        return len(hist)

    # actions -----------------------------------------------------------------
    def _activate(self, it) -> None:
        key = it.data(KEY)
        if not key:
            return
        kind = key[0]
        app = self.app
        if kind in ("history", "music", "videos", "playlists"):
            self.go((kind,))
        elif kind == "folder":
            self.open_folder_page(key[1])
        elif kind == "add-folder":
            self.add_folder(key[1])
        elif kind == "file":
            _, files = scan_folder(os.path.dirname(key[1]))
            files = self._sorted(files, key=lambda p: os.path.basename(p).lower())
            app.play_mrls([to_mrl(f) for f in files], files.index(key[1]) if key[1] in files else 0)
        elif kind == "play-all":
            _, files = scan_folder(key[1])
            app.play_mrls([to_mrl(f) for f in self._sorted(files, key=lambda p: os.path.basename(p).lower())])
        elif kind == "media":
            app.play_mrls([key[1]])
        elif kind == "new-playlist":
            self.create_playlist()
        elif kind == "playlist":
            self.go(("playlist", key[1]))
        elif kind == "play-playlist":
            app.play_mrls(list(self.store.data["playlists"].get(key[1], [])))
        elif kind == "pl-item":
            items = self.store.data["playlists"].get(key[1], [])
            app.play_mrls(list(items), key[2])
        elif kind == "clear-history":
            self.store.data["history"].clear()
            self.store.save()
            self.render()

    def _media_of(self, key) -> list[str]:
        if not key:
            return []
        if key[0] == "file":
            return [to_mrl(key[1])]
        if key[0] == "media":
            return [key[1]]
        if key[0] == "pl-item":
            return [self.store.data["playlists"][key[1]][key[2]]]
        if key[0] in ("folder", "play-all"):
            _, files = scan_folder(key[1])
            return [to_mrl(f) for f in files]
        if key[0] in ("playlist", "play-playlist"):
            return list(self.store.data["playlists"].get(key[1], []))
        return []

    def _context(self, pos) -> None:
        it = self.list.itemAt(pos)
        key = it.data(KEY) if it else None
        mrls = self._media_of(key)
        m = QMenu(self)
        if mrls:
            m.addAction("Play", lambda: self.app.play_mrls(mrls))
            m.addAction("Add to queue", lambda: self.app.enqueue(mrls))
            sub = m.addMenu("Add to playlist")
            for name in sorted(self.store.data["playlists"], key=str.lower):
                sub.addAction(name, lambda n=name: self._add_to_playlist(n, mrls))
            sub.addSeparator()
            sub.addAction("New playlist…", lambda: self.create_playlist(mrls))
        if key and key[0] in ("file", "folder"):
            m.addAction("Show in File Explorer", lambda: self._reveal(key[1]))
        if key and key[0] == "folder" and self.page[0] in ("videos", "music"):
            m.addSeparator()
            m.addAction("Remove from library", lambda: self._remove_root(key[1]))
        if key and key[0] == "pl-item":
            m.addSeparator()
            m.addAction("Remove from playlist", lambda: self._remove_pl_item(key[1], key[2]))
        if key and key[0] == "playlist":
            m.addSeparator()
            m.addAction("Rename…", lambda: self._rename_playlist(key[1]))
            m.addAction("Delete playlist", lambda: self._delete_playlist(key[1]))
        if key and key[0] == "media" and self.page[0] == "history":
            m.addAction("Remove from history", lambda: self._remove_history(key[1]))
        if not m.isEmpty():
            m.exec(self.list.mapToGlobal(pos))

    def _more_menu(self) -> None:
        m = QMenu(self)
        m.addAction("Open file…", self.app.open_files)
        m.addAction("Open folder…", self.app.open_folder)
        m.addAction("Add folder to library…", self.add_folder)
        m.addAction("Create playlist from queue…", self.app.save_queue_as_playlist)
        m.exec(self.b_more.mapToGlobal(self.b_more.rect().bottomLeft()))

    def _open_external(self) -> None:
        if self.page[0] == "folder":
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.page[1]))
        else:
            key = "video" if self.page[0] == "videos" else "music"
            for p in self.store.data["folders"][key][:1]:
                QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def _reveal(self, path: str) -> None:
        import subprocess
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def add_folder(self, kind: str | None = None) -> None:
        path = QFileDialog.getExistingDirectory(self.app, "Add a folder to the library")
        if not path:
            return
        if kind not in ("video", "music"):
            _, files = scan_folder(path)
            audio = sum(os.path.splitext(f)[1].lower() in AUDIO_EXT for f in files)
            kind = "music" if files and audio > len(files) / 2 else "video"
        roots = self.store.data["folders"][kind]
        if path not in roots:
            roots.append(path)
            self.store.save()
        self.go(("videos" if kind == "video" else "music",))

    def _remove_root(self, path: str) -> None:
        for k in ("video", "music"):
            if path in self.store.data["folders"][k]:
                self.store.data["folders"][k].remove(path)
        self.store.save()
        self.render()

    def create_playlist(self, mrls: list[str] | None = None) -> None:
        name, ok = QInputDialog.getText(self.app, "Create playlist", "Playlist name:")
        name = name.strip()
        if not ok or not name:
            return
        if mrls is None:
            mrls = [e["mrl"] for e in self.app.queue.items]
        self.store.data["playlists"][name] = list(mrls)
        self.store.save()
        self.go(("playlist", name))

    def _add_to_playlist(self, name: str, mrls: list[str]) -> None:
        self.store.data["playlists"].setdefault(name, []).extend(mrls)
        self.store.save()
        self.app.osd(f"Added to {name}")

    def _remove_pl_item(self, name: str, i: int) -> None:
        items = self.store.data["playlists"].get(name, [])
        if 0 <= i < len(items):
            items.pop(i)
            self.store.save()
            self.render()

    def _rename_playlist(self, name: str) -> None:
        new, ok = QInputDialog.getText(self.app, "Rename playlist", "Name:", text=name)
        new = new.strip()
        if ok and new and new != name:
            pls = self.store.data["playlists"]
            pls[new] = pls.pop(name)
            self.store.save()
            self.render()

    def _delete_playlist(self, name: str) -> None:
        self.store.data["playlists"].pop(name, None)
        self.store.save()
        if self.page == ("playlist", name):
            self.go(("playlists",))
        else:
            self.render()

    def _remove_history(self, mrl: str) -> None:
        self.store.data["history"] = [h for h in self.store.data["history"] if h["mrl"] != mrl]
        self.store.save()
        self.render()

    def _play_url(self) -> None:
        url = self.url.text().strip()
        if not url:
            return
        if "://" not in url:
            url = "https://" + url
        streams = self.store.data["streams"]
        if url in streams:
            streams.remove(url)
        streams.insert(0, url)
        del streams[20:]
        self.store.save()
        self.url.clear()
        self.app.play_mrls([url])
        self.render()

    def _toggle_sort(self) -> None:
        self.sort_desc = not self.sort_desc
        self.b_sort.set_active(self.sort_desc)
        self.render()

    def _toggle_view(self, on: bool) -> None:
        self.details = on
        self.render()

    def _toggle_search(self, on: bool) -> None:
        self.search.setVisible(on)
        if on:
            self.search.setFocus()
        else:
            self.search.clear()

    def _filter(self, text: str) -> None:
        t = text.lower().strip()
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(rows.HEADER):
                it.setHidden(False)
                continue
            it.setHidden(bool(t) and t not in (it.text() or "").lower())
