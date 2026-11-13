"""Thin Qt wrapper around libVLC (python-vlc). All playback goes through VLC's engine."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QObject, QTimer, Signal


def _prepare_libvlc_path() -> None:
    """Help python-vlc find libvlc.dll (VLC install dir, or VLC_PATH env var)."""
    if sys.platform != "win32" or os.environ.get("PYTHON_VLC_LIB_PATH"):
        return
    candidates = []
    if getattr(sys, "frozen", False):
        # packaged build: libVLC + plugins ship in a "vlc" folder next to the app
        candidates.append(os.path.join(os.path.dirname(sys.executable), "vlc"))
        candidates.append(os.path.join(getattr(sys, "_MEIPASS", ""), "vlc"))
    candidates.append(os.environ.get("VLC_PATH", ""))
    for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        if base:
            candidates.append(os.path.join(base, "VideoLAN", "VLC"))
    for d in candidates:
        if d and os.path.isfile(os.path.join(d, "libvlc.dll")):
            os.environ["PYTHON_VLC_LIB_PATH"] = os.path.join(d, "libvlc.dll")
            os.environ.setdefault("PYTHON_VLC_MODULE_PATH", os.path.join(d, "plugins"))
            os.add_dll_directory(d)
            return


_prepare_libvlc_path()
import vlc  # noqa: E402

VISUALIZERS = {
    "Disabled": None,
    "Spectrum": ("visual", "spectrum"),
    "Spectrometer": ("visual", "spectrometer"),
    "Scope": ("visual", "scope"),
    "VU meter": ("visual", "vuMeter"),
    "Goom": ("goom", None),
}

STEREO_MODES = {"Stereo": 1, "Reverse stereo": 2, "Left": 3, "Right": 4, "Dolby Surround": 5}


def _s(v) -> str:
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return "" if v is None else str(v)


class Engine(QObject):
    stateChanged = Signal(str)      # opening | playing | paused | stopped | ended | error
    timeChanged = Signal(int)
    lengthChanged = Signal(int)
    endReached = Signal()
    tracksChanged = Signal()
    voutChanged = Signal(bool)
    volumeChanged = Signal(int, bool)
    rateChanged = Signal(float)
    _vlc_event = Signal(str)

    def __init__(self, extra_args: list[str] | None = None) -> None:
        super().__init__()
        self._base_args = ["--quiet", "--no-video-title-show", "--no-snapshot-preview", *(extra_args or [])]
        self.instance = None
        self.player = None
        self._win_id: int | None = None
        # player-level settings, re-applied whenever the player is rebuilt
        self._vstate: dict = {}

        self.mrl: str | None = None
        self.media = None
        self.state = "stopped"
        self.has_video = False
        self._volume = 80
        self._muted = False
        self._rate = 1.0
        self.slaves: list[str] = []
        # options that need the media to be re-opened when changed
        self.flip = "none"          # none | h | v
        self.rotate = 0
        self.visualizer = "Disabled"
        self._eq = None

        E = vlc.EventType
        self._events = [
            (E.MediaPlayerOpening, "opening"), (E.MediaPlayerPlaying, "playing"),
            (E.MediaPlayerPaused, "paused"), (E.MediaPlayerStopped, "stopped"),
            (E.MediaPlayerEndReached, "ended"), (E.MediaPlayerEncounteredError, "error"),
            (E.MediaPlayerLengthChanged, "length"), (E.MediaPlayerESAdded, "es"),
            (E.MediaPlayerESDeleted, "es"), (E.MediaPlayerESSelected, "es"),
            (E.MediaPlayerVout, "vout"),
        ]
        self._generation = 0
        self._filter_args: list[str] = []
        self._vlc_event.connect(self._handle_event)
        self._poll = QTimer(self, interval=200, timeout=self._tick)
        self._create_player([])

    def _create_player(self, filter_args: list[str]) -> None:
        """(Re)create the libVLC instance + player. libVLC 3 only applies video filters
        (flip/rotate) and visualisations given at instance level, so changing them needs
        a fresh instance; all other settings are carried over."""
        if self.player is not None:
            self._poll.stop()
            em = self.player.event_manager()
            for et, _ in self._events:
                em.event_detach(et)
            self.player.stop()
            self.player.release()
            self.player = None
        if self.instance is None or filter_args != self._filter_args:
            if self.instance is not None:
                self.instance.release()
            self.instance = vlc.Instance(self._base_args + filter_args)
            if self.instance is None:
                raise RuntimeError("libVLC could not be initialised. Is VLC 3 (64-bit) installed?")
            self._filter_args = list(filter_args)
        self._generation += 1
        self.player = self.instance.media_player_new()
        self.player.video_set_mouse_input(False)
        self.player.video_set_key_input(False)
        em = self.player.event_manager()
        for et, name in self._events:
            em.event_attach(et, self._on_vlc_event, (self._generation, name))
        if self._win_id is not None:
            self.attach(self._win_id)
        if self._eq is not None:
            self.player.set_equalizer(self._eq)
        self._apply_vstate()

    def _apply_vstate(self) -> None:
        p, s = self.player, self._vstate
        if "scale" in s:
            p.video_set_scale(s["scale"])
        if "aspect" in s:
            p.video_set_aspect_ratio(s["aspect"])
        if "crop" in s:
            p.video_set_crop_geometry(s["crop"])
        if "deint" in s:
            p.video_set_deinterlace(s["deint"])
        if "adjust" in s:
            self.set_adjust(*s["adjust"])

    def _apply_media_state(self) -> None:
        """Settings libVLC resets per media (applied once playback has started)."""
        s = self._vstate
        if "adelay" in s:
            self.player.audio_set_delay(int(s["adelay"] * 1_000_000))
        if "sdelay" in s:
            self.player.video_set_spu_delay(int(s["sdelay"] * 1_000_000))
        if s.get("stereo", 1) != 1:
            self.player.audio_set_channel(s["stereo"])

    # -- libVLC callbacks (VLC thread) -> Qt main thread ----------------------
    def _on_vlc_event(self, _event, tag):
        gen, name = tag
        if gen == self._generation:
            self._vlc_event.emit(name)

    def _handle_event(self, name: str) -> None:
        if name in ("opening", "playing", "paused", "stopped", "ended", "error"):
            self.state = name
            if name == "playing":
                self._poll.start()
                self.player.audio_set_volume(self._volume)
                self.player.audio_set_mute(self._muted)
                if abs(self.player.get_rate() - self._rate) > 1e-3:
                    self.player.set_rate(self._rate)
                self._apply_media_state()
            elif name in ("stopped", "ended", "error"):
                self._poll.stop()
            self.stateChanged.emit(name)
            if name == "ended":
                self.endReached.emit()
        elif name == "length":
            self.lengthChanged.emit(self.length())
        elif name == "es":
            self.tracksChanged.emit()
        elif name == "vout":
            self.has_video = self.player.has_vout() > 0
            if self.has_video and "adjust" in self._vstate:
                self.set_adjust(*self._vstate["adjust"])   # needs a live video output
            self.voutChanged.emit(self.has_video)
            self.tracksChanged.emit()

    def _tick(self) -> None:
        self.timeChanged.emit(max(0, self.player.get_time()))

    # -- output ---------------------------------------------------------------
    def attach(self, win_id: int) -> None:
        self._win_id = win_id
        if sys.platform == "win32":
            self.player.set_hwnd(win_id)
        elif sys.platform == "darwin":
            self.player.set_nsobject(win_id)
        else:
            self.player.set_xwindow(win_id)

    # -- loading --------------------------------------------------------------
    def _wanted_filter_args(self) -> list[str]:
        """Instance arguments for flip / rotate / audio visualisation."""
        args, filters = [], []
        rot = self.rotate % 360
        # flip + quarter turns map exactly onto the fast 'transform' filter
        combo = {("h", 90): "antitranspose", ("h", 180): "vflip", ("h", 270): "transpose",
                 ("v", 90): "transpose", ("v", 180): "hflip", ("v", 270): "antitranspose"}
        if (self.flip, rot) in combo:
            filters.append("transform")
            args.append(f"--transform-type={combo[(self.flip, rot)]}")
        elif self.flip != "none":
            filters.append("transform")
            args.append("--transform-type=" + ("hflip" if self.flip == "h" else "vflip"))
            if rot:
                filters.append("rotate")
                args.append(f"--rotate-angle={-rot}")
        elif rot in (90, 180, 270):
            filters.append("transform")
            args.append(f"--transform-type={rot}")
        elif rot:
            filters.append("rotate")
            args.append(f"--rotate-angle={-rot}")
        if filters:
            args.append("--video-filter=" + ":".join(filters))
        vis = VISUALIZERS.get(self.visualizer)
        if vis:
            args.append(f"--audio-visual={vis[0]}")
            if vis[1]:
                args.append(f"--effect-list={vis[1]}")
        return args

    def load(self, mrl: str, start_ms: int = 0, paused: bool = False, keep_slaves: bool = False) -> None:
        if not keep_slaves:
            # a different media: per-media sync settings start fresh
            self.slaves = []
            for k in ("adelay", "sdelay", "stereo"):
                self._vstate.pop(k, None)
        wanted = self._wanted_filter_args()
        if wanted != self._filter_args:
            self._create_player(wanted)
        self.mrl = mrl
        media = self.instance.media_new(mrl)
        if start_ms > 0:
            media.add_option(f":start-time={start_ms / 1000:.3f}")
        if paused:
            media.add_option(":start-paused")
        self.media = media
        self.has_video = False
        self.player.set_media(media)
        self.player.play()
        for uri in self.slaves:
            self.player.add_slave(vlc.MediaSlaveType.subtitle, uri, True)

    def reopen(self) -> None:
        """Re-open the current media at the same position (needed for filter changes)."""
        if not self.mrl:
            return
        t = self.player.get_time()
        paused = self.state == "paused"
        self.load(self.mrl, max(0, t), paused, keep_slaves=True)

    # -- transport ------------------------------------------------------------
    def toggle(self) -> None:
        if self.state in ("stopped", "ended", "error") and self.mrl:
            self.load(self.mrl, keep_slaves=True)
        else:
            self.player.pause()

    def play(self) -> None:
        self.player.set_pause(0)

    def pause(self) -> None:
        self.player.set_pause(1)

    def stop(self) -> None:
        self.player.stop()

    def is_playing(self) -> bool:
        return self.state == "playing"

    def time(self) -> int:
        return max(0, self.player.get_time())

    def length(self) -> int:
        return max(0, self.player.get_length())

    def seek(self, ms: int) -> None:
        if self.player.is_seekable():
            self.player.set_time(int(max(0, ms)))
            self.timeChanged.emit(int(ms))

    def jump(self, delta_ms: int) -> None:
        self.seek(self.time() + delta_ms)

    def next_frame(self) -> None:
        self.player.next_frame()

    # -- audio ----------------------------------------------------------------
    def volume(self) -> int:
        return self._volume

    def muted(self) -> bool:
        return self._muted

    def set_volume(self, v: int) -> None:
        self._volume = int(max(0, min(125, v)))
        self.player.audio_set_volume(self._volume)
        if self._muted and v > 0:
            self.set_muted(False)
        self.volumeChanged.emit(self._volume, self._muted)

    def set_muted(self, m: bool) -> None:
        self._muted = bool(m)
        self.player.audio_set_mute(self._muted)
        self.volumeChanged.emit(self._volume, self._muted)

    def set_rate(self, r: float) -> None:
        self._rate = float(max(0.25, min(4.0, r)))
        self.player.set_rate(self._rate)
        self.rateChanged.emit(self._rate)

    def rate(self) -> float:
        return self._rate

    def audio_tracks(self) -> list[tuple[int, str]]:
        return [(i, _s(n)) for i, n in (self.player.audio_get_track_description() or [])]

    def audio_track(self) -> int:
        return self.player.audio_get_track()

    def set_audio_track(self, i: int) -> None:
        self.player.audio_set_track(i)
        self.tracksChanged.emit()

    def set_audio_delay(self, seconds: float) -> None:
        self._vstate["adelay"] = seconds
        self.player.audio_set_delay(int(seconds * 1_000_000))

    def audio_delay(self) -> float:
        return self.player.audio_get_delay() / 1_000_000

    def set_stereo_mode(self, name: str) -> None:
        self._vstate["stereo"] = STEREO_MODES.get(name, 1)
        self.player.audio_set_channel(self._vstate["stereo"])

    def output_devices(self) -> list[tuple[str, str]]:
        out = []
        head = self.player.audio_output_device_enum()
        node = head
        while node:
            d = node.contents
            out.append((_s(d.device), _s(d.description)))
            node = d.next
        if head:
            vlc.libvlc_audio_output_device_list_release(head)
        return out

    def output_device(self) -> str:
        try:
            return _s(self.player.audio_output_device_get())
        except Exception:
            return ""

    def set_output_device(self, device_id: str) -> None:
        self.player.audio_output_device_set(None, device_id)

    # equaliser
    @staticmethod
    def eq_presets() -> list[str]:
        n = vlc.libvlc_audio_equalizer_get_preset_count()
        return [_s(vlc.libvlc_audio_equalizer_get_preset_name(i)) for i in range(n)]

    @staticmethod
    def eq_bands() -> list[float]:
        n = vlc.libvlc_audio_equalizer_get_band_count()
        return [vlc.libvlc_audio_equalizer_get_band_frequency(i) for i in range(n)]

    def set_eq_preset(self, index: int | None) -> tuple[float, list[float]]:
        """index None = disable. Returns (preamp, band amps) of the chosen preset."""
        if index is None:
            self._eq = None
            self.player.set_equalizer(None)
            return 0.0, [0.0] * len(self.eq_bands())
        self._eq = vlc.libvlc_audio_equalizer_new_from_preset(index)
        self.player.set_equalizer(self._eq)
        bands = [self._eq.get_amp_at_index(i) for i in range(len(self.eq_bands()))]
        return self._eq.get_preamp(), bands

    def set_eq_values(self, preamp: float, bands: list[float]) -> None:
        if self._eq is None:
            self._eq = vlc.AudioEqualizer()
        self._eq.set_preamp(preamp)
        for i, v in enumerate(bands):
            self._eq.set_amp_at_index(v, i)
        self.player.set_equalizer(self._eq)

    # -- video ----------------------------------------------------------------
    def video_tracks(self) -> list[tuple[int, str]]:
        return [(i, _s(n)) for i, n in (self.player.video_get_track_description() or [])]

    def video_track(self) -> int:
        return self.player.video_get_track()

    def set_video_track(self, i: int) -> None:
        self.player.video_set_track(i)
        self.tracksChanged.emit()

    def set_scale(self, s: float) -> None:
        self._vstate["scale"] = s
        self.player.video_set_scale(s)

    def set_aspect(self, a: str | None) -> None:
        self._vstate["aspect"] = a
        self.player.video_set_aspect_ratio(a)

    def set_crop(self, c: str | None) -> None:
        self._vstate["crop"] = c
        self.player.video_set_crop_geometry(c)

    def set_deinterlace(self, mode: str | None) -> None:
        self._vstate["deint"] = mode
        self.player.video_set_deinterlace(mode)

    def set_adjust(self, brightness: float, contrast: float, saturation: float, hue: float, gamma: float) -> None:
        self._vstate["adjust"] = (brightness, contrast, saturation, hue, gamma)
        A = vlc.VideoAdjustOption
        on = not (brightness == 1 and contrast == 1 and saturation == 1 and hue == 0 and gamma == 1)
        self.player.video_set_adjust_int(A.Enable, 1 if on else 0)
        if on:
            self.player.video_set_adjust_float(A.Brightness, brightness)
            self.player.video_set_adjust_float(A.Contrast, contrast)
            self.player.video_set_adjust_float(A.Saturation, saturation)
            self.player.video_set_adjust_float(A.Hue, hue)
            self.player.video_set_adjust_float(A.Gamma, gamma)

    def snapshot(self, path: str) -> bool:
        return self.player.video_take_snapshot(0, path, 0, 0) == 0

    # -- subtitles ------------------------------------------------------------
    def spu_tracks(self) -> list[tuple[int, str]]:
        return [(i, _s(n)) for i, n in (self.player.video_get_spu_description() or [])]

    def spu_track(self) -> int:
        return self.player.video_get_spu()

    def set_spu_track(self, i: int) -> None:
        self.player.video_set_spu(i)
        self.tracksChanged.emit()

    def add_subtitle(self, uri: str) -> None:
        if uri not in self.slaves:
            self.slaves.append(uri)
        self.player.add_slave(vlc.MediaSlaveType.subtitle, uri, True)
        self.tracksChanged.emit()

    def set_spu_delay(self, seconds: float) -> None:
        self._vstate["sdelay"] = seconds
        self.player.video_set_spu_delay(int(seconds * 1_000_000))

    def spu_delay(self) -> float:
        return self.player.video_get_spu_delay() / 1_000_000

    # -- chapters -------------------------------------------------------------
    def chapters(self) -> list[tuple[int, str, int]]:
        out = []
        try:
            descs = self.player.get_full_chapter_descriptions(-1) or []
            for i, d in enumerate(descs):
                out.append((i, _s(d.name) or f"Chapter {i + 1}", int(d.time_offset)))
        except Exception:
            pass
        return out

    def chapter(self) -> int:
        return self.player.get_chapter()

    def set_chapter(self, i: int) -> None:
        self.player.set_chapter(i)

    # -- misc -----------------------------------------------------------------
    def stats(self) -> dict:
        if not self.media:
            return {}
        st = vlc.MediaStats()
        try:
            ok = self.media.get_stats(st)
        except Exception:
            ok = False
        if not ok:
            return {}
        return {
            "Input bitrate": f"{st.input_bitrate * 8000:.0f} kb/s",
            "Demux bitrate": f"{st.demux_bitrate * 8000:.0f} kb/s",
            "Decoded video": st.decoded_video,
            "Displayed": st.displayed_pictures,
            "Lost frames": st.lost_pictures,
            "Decoded audio": st.decoded_audio,
            "Lost audio": st.lost_abuffers,
        }

    def video_size(self) -> tuple[int, int]:
        try:
            w, h = self.player.video_get_size(0)
            return int(w), int(h)
        except Exception:
            return 0, 0

    def fps(self) -> float:
        return float(self.player.get_fps() or 0)

    def release(self) -> None:
        self._poll.stop()
        try:
            em = self.player.event_manager()
            for et, _ in self._events:
                em.event_detach(et)
        except Exception:
            pass
        self.player.stop()
        self.player.release()
        self.instance.release()


def parse_duration_async(instance, mrl: str):
    """Kick off async parsing of a media's duration. Returns the Media object to poll."""
    m = instance.media_new(mrl)
    # python-vlc enum members can't be OR-ed; 'local' is enough to read the duration.
    m.parse_with_options(vlc.MediaParseFlag.local, 4000)
    return m


def parsed_duration(media) -> int | None:
    """Duration in ms once parsed, -1 if parsing failed, None if still pending."""
    try:
        st = media.get_parsed_status()
    except Exception:
        return -1
    if st == vlc.MediaParsedStatus.done:
        return max(0, media.get_duration())
    if st in (vlc.MediaParsedStatus.failed, vlc.MediaParsedStatus.timeout, vlc.MediaParsedStatus.skipped):
        return -1
    return None
