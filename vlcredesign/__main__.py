import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox


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
