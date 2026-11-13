"""Small animation helpers shared by the widgets.

`Tween` animates one float and calls back on each step (by default it repaints the
owning widget), so custom-painted controls can ease between states with one line.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QObject, QVariantAnimation
from PySide6.QtWidgets import QWidget

FAST = 120
NORMAL = 200
SLOW = 260


class Tween(QObject):
    def __init__(self, owner: QWidget, value: float = 0.0, duration: int = NORMAL,
                 easing: QEasingCurve.Type = QEasingCurve.OutCubic,
                 on_step: Callable[[float], None] | None = None):
        super().__init__(owner)
        self._value = float(value)
        self._target = float(value)
        self.duration = duration
        self.easing = easing
        self._on_step = on_step or (lambda _v: owner.update())
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._step)

    @property
    def value(self) -> float:
        return self._value

    @property
    def target(self) -> float:
        return self._target

    def running(self) -> bool:
        return self._anim.state() == QVariantAnimation.Running

    def to(self, target: float, duration: int | None = None,
           easing: QEasingCurve.Type | None = None) -> None:
        target = float(target)
        if target == self._target and (self.running() or self._value == target):
            return
        self._target = target
        self._anim.stop()
        if self._value == target:
            return
        self._anim.setDuration(max(1, self.duration if duration is None else duration))
        self._anim.setEasingCurve(easing if easing is not None else self.easing)
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(target)
        self._anim.start()

    def snap(self, value: float) -> None:
        self._anim.stop()
        self._value = self._target = float(value)
        self._on_step(self._value)

    def _step(self, v) -> None:
        self._value = float(v)
        self._on_step(self._value)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix(c1, c2, t: float):
    """Blend two QColors."""
    from PySide6.QtGui import QColor
    a, b = QColor(c1), QColor(c2)
    return QColor(round(lerp(a.red(), b.red(), t)), round(lerp(a.green(), b.green(), t)),
                  round(lerp(a.blue(), b.blue(), t)), round(lerp(a.alpha(), b.alpha(), t)))
