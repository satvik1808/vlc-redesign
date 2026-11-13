"""A single list-row delegate used by every list in the app (queue, bookmarks, chapters,
tracks, library), so they all share the design's row styling."""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from . import icons, theme

ICON = Qt.UserRole + 1      # icon name
RIGHT = Qt.UserRole + 2     # right-aligned text
CURRENT = Qt.UserRole + 3   # highlight as "now playing" / selected track
NUM = Qt.UserRole + 4       # orange number prefix (chapters)
KEY = Qt.UserRole + 5       # payload
HEADER = Qt.UserRole + 6    # section header row
FAINT = Qt.UserRole + 7     # dim "action" row (Add, Create playlist, ...)
CHECK = Qt.UserRole + 8     # show check-mark column (tracks popup)
SUB = Qt.UserRole + 9       # small secondary text below title


class RowDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index: QModelIndex) -> QSize:
        if index.data(HEADER):
            return QSize(100, 42)
        if index.data(SUB):
            return QSize(100, 44)
        return QSize(100, 34)

    def paint(self, p: QPainter, option, index: QModelIndex) -> None:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(option.rect)
        text = index.data(Qt.DisplayRole) or ""
        if index.data(HEADER):
            f = QFont(option.font)
            f.setPixelSize(13)
            f.setWeight(QFont.DemiBold)
            p.setFont(f)
            hover = bool(option.state & QStyle.State_MouseOver)
            p.setPen(QColor(theme.TEXT))
            p.drawText(r.adjusted(10, 6, -36, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
            if index.data(KEY) is not None:
                p.drawPixmap(QPointF(r.right() - 26, r.center().y() - 4),
                             icons.pixmap("chevron-right", 14, theme.TEXT if hover else theme.TEXT_DIM))
            p.restore()
            return

        sel = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        if sel or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT_BG if sel else theme.HOVER))
            p.drawRoundedRect(r.adjusted(4, 1, -4, -1), 4, 4)

        current = bool(index.data(CURRENT))
        faint = bool(index.data(FAINT))
        x = r.left() + 14
        if index.data(CHECK):
            if current:
                p.drawPixmap(QPointF(x, r.center().y() - 7), icons.pixmap("check", 14, theme.ACCENT))
            x += 26
        num = index.data(NUM)
        if num:
            p.setPen(QColor(theme.ACCENT))
            p.drawText(QRectF(x, r.top(), 24, r.height()), Qt.AlignVCenter | Qt.AlignLeft, str(num))
            x += 30
        ic = index.data(ICON)
        if ic:
            col = theme.ACCENT if current else ("#7a7a7a" if not faint else theme.TEXT_FAINT)
            p.drawPixmap(QPointF(x, r.center().y() - 8), icons.pixmap(ic, 16, col))
            x += 30

        right = index.data(RIGHT) or ""
        rw = p.fontMetrics().horizontalAdvance(right) + 16 if right else 0
        if right:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(QRectF(r.right() - rw - 6, r.top(), rw, r.height()), Qt.AlignVCenter | Qt.AlignRight, right)

        col = theme.ACCENT if current and not index.data(CHECK) else (theme.TEXT_DIM if faint else theme.TEXT)
        p.setPen(QColor(col))
        tr = QRectF(x, r.top(), r.right() - x - rw - 12, r.height())
        sub = index.data(SUB)
        if sub:
            p.drawText(tr.adjusted(0, 5, 0, -r.height() / 2 + 3), Qt.AlignBottom | Qt.AlignLeft,
                       p.fontMetrics().elidedText(text, Qt.ElideRight, int(tr.width())))
            f = QFont(option.font)
            f.setPixelSize(11)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT_FAINT))
            p.drawText(tr.adjusted(0, r.height() / 2 + 1, 0, 0), Qt.AlignTop | Qt.AlignLeft,
                       p.fontMetrics().elidedText(sub, Qt.ElideRight, int(tr.width())))
        else:
            p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft,
                       p.fontMetrics().elidedText(text, Qt.ElideRight, int(tr.width())))
        p.restore()


def make_list(parent=None, draggable: bool = False) -> QListWidget:
    lw = QListWidget(parent)
    lw.setItemDelegate(RowDelegate(lw))
    lw.setMouseTracking(True)
    lw.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    lw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    lw.setSelectionMode(QAbstractItemView.ExtendedSelection if draggable else QAbstractItemView.SingleSelection)
    lw.setUniformItemSizes(False)
    if draggable:
        lw.setDragDropMode(QAbstractItemView.InternalMove)
        lw.setDefaultDropAction(Qt.MoveAction)
    return lw


def item(text: str, **roles) -> QListWidgetItem:
    it = QListWidgetItem(text)
    mapping = {"icon": ICON, "right": RIGHT, "current": CURRENT, "num": NUM, "key": KEY,
               "header": HEADER, "faint": FAINT, "check": CHECK, "sub": SUB}
    for k, v in roles.items():
        it.setData(mapping[k], v)
    if roles.get("header"):
        it.setFlags(Qt.ItemIsEnabled)
    return it
