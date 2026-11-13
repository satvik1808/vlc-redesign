import sys

from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QComboBox, QMenu, QMessageBox

MENU_OPACITY = 0.95


class _TranslucentPopups(QObject):
    """Makes every menu and drop-down list slightly see-through as it opens."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Show and isinstance(obj, QMenu):
            obj.setWindowOpacity(MENU_OPACITY)
        elif ev.type() == QEvent.Show and obj.isWidgetType() and obj.isWindow()                 and isinstance(obj.parent(), QComboBox):
            obj.setWindowOpacity(MENU_OPACITY)         # the combo box's pop-up list
        return False


def _app_icon() -> QIcon:
    from .icons import paint_cone
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        paint_cone(p, QRectF(size * 0.06, size * 0.04, size * 0.88, size * 0.92))
        p.end()
        ic.addPixmap(pm)
    return ic


def main() -> int:
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("VLCRedesign")
    app.setOrganizationName("VLCRedesign")
    app.setApplicationDisplayName("VLC Media Player")
    app.setWindowIcon(_app_icon())

    from . import theme
    family = theme.pick_font_family()
    f = QFont(family)
    f.setPixelSize(12)
    app.setFont(f)
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet(family))
    # (menu *fade* would animate opacity back to 100%, so menus use the roll-out effect instead)
    for effect in (Qt.UI_AnimateMenu, Qt.UI_AnimateCombo, Qt.UI_AnimateTooltip, Qt.UI_FadeTooltip):
        app.setEffectEnabled(effect, True)
    app.setEffectEnabled(Qt.UI_FadeMenu, False)
    popups = _TranslucentPopups(app)
    app.installEventFilter(popups)

    try:
        from .mainwindow import MainWindow
        win = MainWindow(sys.argv[1:])
    except Exception as exc:  # most likely libVLC missing
        QMessageBox.critical(None, "VLC Redesign", f"Could not start the player:\n\n{exc}\n\n"
                             "Install VLC 3 (64-bit) from videolan.org, or set VLC_PATH to its folder.")
        return 1
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
