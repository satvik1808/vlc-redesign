"""Seek-bar hover previews.

A second, silent libVLC player opens the same media off-screen and renders into a small
memory buffer (video callbacks). Hovering the seek bar asks it to seek; the frame it
decodes is shown in a little popup above the bar, like the scrub previews on video sites.
Requests are coalesced, so only the latest hovered time is decoded.
"""
from __future__ import annotations

import ctypes
import threading

import vlc
from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

from . import theme
from .anim import Tween
from .store import fmt_time

PREVIEW_W = 192


class FramePreviewer(QObject):
    """Decodes frames at requested times, off-screen. Emits frameReady(ms, image)."""

    frameReady = Signal(int, QImage)
    _gotFrame = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inst: vlc.Instance | None = None
        self._player = None
        self._mrl: str | None = None
        self._w = PREVIEW_W
        self._h = 108
        self._buf = None
        self._lock = threading.Lock()
        self._frames = 0
        self._ready = False           # first frame decoded and player paused
        self._fresh = False
        self._inflight: int | None = None
        self._wanted: int | None = None
        self._watchdog = QTimer(self, singleShot=True, interval=450, timeout=self._give_up)
        # if the first frame never arrives (rare libVLC start hiccup), reopen once
        self._start_watch = QTimer(self, singleShot=True, interval=2500, timeout=self._start_stalled)
        self._aspect = 16 / 9
        self._retried = False
        self._gotFrame.connect(self._on_frame)
        # keep the ctypes callbacks alive for as long as the player exists
        self._cb_lock = vlc.CallbackDecorators.VideoLockCb(self._vlc_lock)
        self._cb_unlock = vlc.CallbackDecorators.VideoUnlockCb(self._vlc_unlock)
        self._cb_display = vlc.CallbackDecorators.VideoDisplayCb(self._vlc_display)

    # -- libVLC callbacks (decoder thread) ----------------------------------------------
    def _vlc_lock(self, _opaque, planes):
        self._lock.acquire()
        planes[0] = ctypes.cast(self._buf, ctypes.c_void_p).value
        self._fresh = True           # a newly decoded picture is being written
        return None

    def _vlc_unlock(self, _opaque, _picture, _planes):
        self._lock.release()

    def _vlc_display(self, _opaque, _picture):
        # a paused vout re-displays the same picture periodically; only report new ones
        if self._fresh:
            self._fresh = False
            self._frames += 1
            self._gotFrame.emit()

    # -- control (main thread) ------------------------------------------------------------
    def open(self, mrl: str, aspect: float) -> None:
        if mrl == self._mrl and self._player is not None:
            return
        if mrl != self._mrl:
            self._retried = False
        self.close()
        if not mrl:
            return
        if self._inst is None:
            self._inst = vlc.Instance([
                "--quiet", "--no-audio", "--no-osd", "--no-video-title-show", "--no-spu",
                "--no-sub-autodetect-file", "--avcodec-hw=none", "--avcodec-threads=2",
                "--no-stats", "--no-snapshot-preview",
            ])
        aspect = aspect if aspect and aspect > 0.2 else 16 / 9
        self._aspect = aspect
        self._w = PREVIEW_W
        self._h = max(16, int(round(PREVIEW_W / aspect / 2)) * 2)
        self._buf = ctypes.create_string_buffer(self._w * self._h * 4)
        self._mrl = mrl
        self._ready = False
        self._frames = 0
        self._inflight = None
        player = self._inst.media_player_new()
        media = self._inst.media_new(mrl)
        for opt in (":no-audio", ":input-fast-seek", ":no-spu"):
            media.add_option(opt)
        player.set_media(media)
        player.video_set_callbacks(self._cb_lock, self._cb_unlock, self._cb_display, None)
        player.video_set_format("RV32", self._w, self._h, self._w * 4)
        self._player = player
        player.play()
        self._start_watch.start()

    def _start_stalled(self) -> None:
        if self._player is None or self._ready or self._retried:
            return
        mrl, aspect = self._mrl, self._aspect
        wanted = self._wanted
        self.close()
        self.open(mrl, aspect)
        self._retried = True          # (open() resets it for a new file)
        self._wanted = wanted

    def close(self) -> None:
        self._watchdog.stop()
        self._start_watch.stop()
        p, self._player = self._player, None
        self._mrl = None
        self._ready = False
        self._inflight = self._wanted = None
        if p is not None:
            try:
                p.stop()
                p.release()
            except Exception:
                pass

    def release(self) -> None:
        self.close()
        if self._inst is not None:
            try:
                self._inst.release()
            except Exception:
                pass
            self._inst = None

    def request(self, ms: int) -> None:
        """Ask for the frame at `ms`. Only the most recent request is honoured."""
        if self._player is None:
            return
        self._wanted = ms
        if self._ready and self._inflight is None:
            self._issue()

    def _issue(self) -> None:
        if self._player is None or self._wanted is None:
            return
        ms, self._wanted = self._wanted, None
        self._inflight = ms
        self._player.set_time(max(0, int(ms)))
        self._watchdog.start()

    def _snapshot(self) -> tuple[bytes, QImage]:
        with self._lock:
            raw = self._buf.raw
        return raw, QImage(raw, self._w, self._h, self._w * 4, QImage.Format_RGB32).copy()

    def _on_frame(self) -> None:
        if self._player is None:
            return
        if not self._ready:
            self._ready = True
            self._player.set_pause(1)
            self._last_hash = hash(self._snapshot()[0])
            if self._wanted is not None:
                self._issue()
            return
        if self._inflight is None:
            return                     # periodic re-display while paused
        raw, img = self._snapshot()
        h = hash(raw)
        if h == self._last_hash:
            return                     # still the previous picture; the seek hasn't landed yet
        self._deliver(raw, img)

    def _deliver(self, raw: bytes, img: QImage) -> None:
        self._last_hash = hash(raw)
        ms, self._inflight = self._inflight, None
        self._watchdog.stop()
        self.frameReady.emit(ms, img)
        if self._wanted is not None:
            self._issue()

    def _give_up(self) -> None:
        # nothing new arrived: the frame really is unchanged (static scene), or the seek failed
        if self._inflight is None or self._player is None:
            return
        raw, img = self._snapshot()
        self._deliver(raw, img)


class PreviewPopup(QWidget):
    """Floating card above the seek bar: the frame (when available) and the time."""

    PAD = 4
    TEXT_H = 22

    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._pm: QPixmap | None = None
        self._frame_ms = -1
        self._text = ""
        self._sub = ""
        self._img_size = (PREVIEW_W, 108)
        self._fade = Tween(self, 0.0, 120, on_step=self._faded)

    def _faded(self, t: float) -> None:
        self.setWindowOpacity(t)
        if t <= 0.0:
            self.hide()

    def set_frame_size(self, w: int, h: int) -> None:
        self._img_size = (w, h)
        self._pm = None

    def set_frame(self, img: QImage) -> None:
        self._pm = QPixmap.fromImage(img)
        self.update()

    def clear_frame(self) -> None:
        self._pm = None
        self.update()

    def show_at(self, anchor: QPoint, text: str, sub: str, bounds) -> None:
        """Centre the card horizontally on anchor.x(), with its bottom edge at anchor.y()."""
        self._text, self._sub = text, sub
        w = self._img_size[0] + 2 * self.PAD
        h = self._img_size[1] + 2 * self.PAD + self.TEXT_H + (14 if sub else 0)
        x = anchor.x() - w // 2
        x = max(bounds.left() + 4, min(bounds.right() - w - 4, x))
        self.setGeometry(x, anchor.y() - h, w, h)
        if not self.isVisible() or self._fade.target < 1.0:
            if not self.isVisible():
                self.setWindowOpacity(0.0)
                self.show()
            self._fade.to(1.0)
        self.update()

    def fade_out(self) -> None:
        if self.isVisible():
            self._fade.to(0.0)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QColor(255, 255, 255, 30))
        p.setBrush(QColor(theme.PANEL))
        p.drawRoundedRect(r, 7, 7)
        iw, ih = self._img_size
        img_r = QRectF(self.PAD, self.PAD, iw, ih)
        clip = QPainterPath()
        clip.addRoundedRect(img_r, 5, 5)
        p.save()
        p.setClipPath(clip)
        p.fillRect(img_r, QColor("#000000"))
        if self._pm is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawPixmap(img_r, self._pm, QRectF(self._pm.rect()))
        p.restore()
        f = QFont(self.font())
        f.setPixelSize(12)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT))
        ty = self.PAD + ih
        p.drawText(QRectF(0, ty, self.width(), self.TEXT_H), Qt.AlignCenter, self._text)
        if self._sub:
            f.setPixelSize(11)
            f.setWeight(QFont.Normal)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT_DIM))
            sub = p.fontMetrics().elidedText(self._sub, Qt.ElideRight, self.width() - 12)
            p.drawText(QRectF(0, ty + self.TEXT_H - 6, self.width(), 16), Qt.AlignCenter, sub)


def fmt_preview_time(ms: int, length: int) -> str:
    return fmt_time(ms, force_hours=length >= 3_600_000)
