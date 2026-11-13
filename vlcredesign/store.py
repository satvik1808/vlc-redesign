"""Small JSON-backed store: history/resume points, playlists, bookmarks, library folders, settings."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl

VIDEO_EXT = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg", ".flv", ".ts",
    ".m2ts", ".mts", ".3gp", ".ogv", ".vob", ".divx", ".rm", ".rmvb", ".asf", ".f4v",
}
AUDIO_EXT = {
    ".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".alac", ".aiff", ".aif",
    ".ape", ".mka", ".mid", ".midi", ".ac3", ".dts",
}
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".smi"}
PLAYLIST_EXT = {".m3u", ".m3u8", ".pls", ".xspf"}
MEDIA_EXT = VIDEO_EXT | AUDIO_EXT | PLAYLIST_EXT


def to_mrl(path_or_url: str) -> str:
    if "://" in path_or_url:
        return path_or_url
    return QUrl.fromLocalFile(os.path.abspath(path_or_url)).toString(QUrl.FullyEncoded)


def mrl_to_path(mrl: str) -> str | None:
    url = QUrl(mrl)
    return url.toLocalFile() if url.isLocalFile() else None


def title_of(mrl: str) -> str:
    path = mrl_to_path(mrl)
    if path:
        return os.path.basename(path)
    url = QUrl(mrl)
    name = os.path.basename(url.path().rstrip("/"))
    return name or url.host() or mrl


def kind_of(mrl: str) -> str:
    ext = os.path.splitext(mrl_to_path(mrl) or QUrl(mrl).path())[1].lower()
    if ext in AUDIO_EXT:
        return "audio"
    if ext in VIDEO_EXT:
        return "video"
    return "stream"


def fmt_time(ms: int | float, force_hours: bool = True) -> str:
    s = max(0, int(ms or 0) // 1000)
    h, m, s = s // 3600, (s // 60) % 60, s % 60
    if h or force_hours:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_short(ms: int | float) -> str:
    s = max(0, int(ms or 0) // 1000)
    h, m, s = s // 3600, (s // 60) % 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_ms(ms: int) -> str:
    ms = max(0, int(ms))
    return f"{fmt_time(ms)}:{ms % 1000:03d}"


def fmt_total(ms: int) -> str:
    m = int(ms // 60000)
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def default_folders(kind: str) -> list[str]:
    loc = QStandardPaths.MoviesLocation if kind == "video" else QStandardPaths.MusicLocation
    return [p for p in QStandardPaths.standardLocations(loc) if os.path.isdir(p)][:1]


class Store:
    def __init__(self) -> None:
        base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        self.dir = Path(base)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "library.json"
        self.data: dict = {}
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("history", [])          # [{mrl,title,kind,position,length,last}]
        self.data.setdefault("playlists", {})        # name -> [mrl]
        self.data.setdefault("bookmarks", {})        # mrl -> [{name,time}]
        self.data.setdefault("folders", {"video": default_folders("video"), "music": default_folders("music")})
        self.data.setdefault("folder_visits", {})    # path -> count
        self.data.setdefault("playlist_visits", {})  # name -> count
        self.data.setdefault("streams", [])          # recent URLs
        self.data.setdefault("settings", {})
        self.data.setdefault("queue", {"items": [], "index": -1})

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # settings -------------------------------------------------------------
    def get(self, key: str, default=None):
        return self.data["settings"].get(key, default)

    def set(self, key: str, value) -> None:
        self.data["settings"][key] = value

    # history --------------------------------------------------------------
    def record(self, mrl: str, position: int, length: int) -> None:
        hist = [h for h in self.data["history"] if h["mrl"] != mrl]
        hist.insert(0, {
            "mrl": mrl, "title": title_of(mrl), "kind": kind_of(mrl),
            "position": int(position), "length": int(length), "last": time.time(),
        })
        self.data["history"] = hist[:200]

    def resume_point(self, mrl: str) -> int:
        for h in self.data["history"]:
            if h["mrl"] == mrl:
                pos, length = h.get("position", 0), h.get("length", 0)
                if length > 120_000 and 10_000 < pos < length * 0.95:
                    return pos
                return 0
        return 0

    def continue_watching(self) -> list[dict]:
        out = []
        for h in self.data["history"]:
            if h["kind"] == "video" and h["length"] and 10_000 < h["position"] < h["length"] * 0.95:
                out.append(h)
        return out

    def visit_folder(self, path: str) -> None:
        v = self.data["folder_visits"]
        v[path] = v.get(path, 0) + 1

    def visit_playlist(self, name: str) -> None:
        v = self.data["playlist_visits"]
        v[name] = v.get(name, 0) + 1

    # bookmarks -------------------------------------------------------------
    def bookmarks(self, mrl: str) -> list[dict]:
        return self.data["bookmarks"].setdefault(mrl, []) if mrl else []
