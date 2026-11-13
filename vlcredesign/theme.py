"""Colour tokens and the global Qt stylesheet, taken from the Figma 'VLC Redesign' file."""
from __future__ import annotations

import os
import tempfile

from PySide6.QtGui import QFont, QFontDatabase

# ---- colour tokens -------------------------------------------------------
WINDOW = "#1b1b1b"        # title bar, control bar, window frame
STAGE = "#2b2a29"         # idle video area
PANEL = "#141414"         # overlay panels (queue / settings / library)
RAIL = "#1b1b1b"          # library icon rail
INPUT = "#1c1c1c"         # dropdowns
FIELD = "#0f0f0f"         # number fields / tracks
BORDER = "#2a2a2a"
DIVIDER = "#222222"
HOVER = "#232323"
TEXT = "#d6d6d6"
TEXT_DIM = "#8c8c8c"
TEXT_FAINT = "#5e5e5e"
ACCENT = "#e8891f"        # VLC orange
ACCENT_DARK = "#4a2a0c"   # seek-bar fill
ACCENT_BG = "#2a1b0d"     # selected row / segmented control
TRACK = "#0d0d0d"         # slider tracks
VOLUME = "#8fb21c"        # volume wedge (lime)


def pick_font_family() -> str:
    families = set(QFontDatabase.families())
    for fam in ("Inter", "Inter Variable", "Segoe UI Variable Text", "Segoe UI"):
        if fam in families:
            return fam
    return QFont().defaultFamily()


def _asset_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "vlcredesign-assets")
    os.makedirs(d, exist_ok=True)
    return d


def _write_svg(name: str, body: str, color: str) -> str:
    path = os.path.join(_asset_dir(), f"{name}.svg")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{body}</svg>'
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return path.replace("\\", "/")


def stylesheet(family: str) -> str:
    chevron = _write_svg("chevron-down", '<path d="M6 9l6 6 6-6"/>', TEXT_DIM)
    return f"""
* {{ font-family: "{family}"; font-size: 12px; }}
QWidget {{ color: {TEXT}; }}
QToolTip {{ background: {INPUT}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}

QComboBox {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 4px;
    padding: 6px 10px; min-height: 18px;
}}
QComboBox:hover {{ border-color: #3a3a3a; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({chevron}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{
    background: {INPUT}; border: 1px solid {BORDER}; outline: 0; padding: 4px;
    selection-background-color: {ACCENT_BG}; selection-color: {ACCENT};
}}

QLineEdit, QAbstractSpinBox {{
    background: {FIELD}; border: 1px solid #1e1e1e; border-radius: 4px;
    padding: 5px 8px; selection-background-color: {ACCENT_DARK};
}}
QLineEdit:focus, QAbstractSpinBox:focus {{ border-color: #3a2a18; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2e2e2e; border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #3a3a3a; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QScrollBar:horizontal {{ height: 0; }}

QListWidget {{ background: transparent; border: none; outline: 0; }}
QListWidget::item {{ padding: 0px; border-radius: 4px; }}
QListWidget::item:hover {{ background: {HOVER}; }}
QListWidget::item:selected {{ background: {ACCENT_BG}; }}

QMenu {{ background: {INPUT}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_BG}; color: {ACCENT}; }}
QMenu::item:disabled {{ color: {TEXT_FAINT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}

QPushButton {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 4px; padding: 6px 12px;
}}
QPushButton:hover {{ background: {HOVER}; }}
QPushButton:pressed {{ background: {ACCENT_BG}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; }}

QDialog, QInputDialog, QMessageBox {{ background: {WINDOW}; }}
QLabel {{ background: transparent; }}
"""
