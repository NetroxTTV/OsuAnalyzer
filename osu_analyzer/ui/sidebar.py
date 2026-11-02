"""Left sidebar: app name, replay search and the replay list."""

from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QItemSelection, QItemSelectionModel, QModelIndex,
                            QPointF, QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QFontMetricsF, QLinearGradient
from PySide6.QtWidgets import (QAbstractItemView, QListView, QStyle, QStyledItemDelegate, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..core import replay_label
from . import icons
from .theme import qcolor, theme
from .widgets import Button, Chip, IconButton, SearchField, Surface, hbox, label, painter

ROW_HEIGHT = 60


class ReplayListModel(QAbstractListModel):
    """Replay paths with their display labels (title, subtitle, date)."""

    LabelRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.paths = []
        self._labels = {}

    def set_paths(self, paths):
        self.beginResetModel()
        self.paths = list(paths)
        for p in self.paths:
            if p not in self._labels:
                self._labels[p] = replay_label(p)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.paths)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self.paths[index.row()]
        if role == self.LabelRole:
            return self._labels[p]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._labels[p][0]
        if role == Qt.ItemDataRole.ToolTipRole:
            return p.name
        return None


class ReplayDelegate(QStyledItemDelegate):
    """Rounded rows: title, 'difficulty · player' and the date."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f_title = theme.semibold(10)
        self.f_sub = theme.font(9)
        self.f_date = theme.font(8.5)

    def sizeHint(self, _option, _index):
        return QSize(200, ROW_HEIGHT)

    def paint(self, p, option, index):
        title, sub, date = index.data(ReplayListModel.LabelRole)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        r = QRectF(option.rect).adjusted(6, 2, -6, -2)
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if selected:
            p.setBrush(theme.accent_soft(0.15))
            p.drawRoundedRect(r, 10, 10)
            p.setBrush(theme.accent)
            p.drawRoundedRect(QRectF(r.x() + 1, r.y() + 14, 3, r.height() - 28), 1.5, 1.5)
        elif hovered:
            p.setBrush(qcolor("#ffffff", 0.045))
            p.drawRoundedRect(r, 10, 10)

        x0, x1 = r.x() + 16, r.right() - 12
        fm_t, fm_s, fm_d = QFontMetricsF(self.f_title), QFontMetricsF(self.f_sub), QFontMetricsF(self.f_date)
        dw = fm_d.horizontalAdvance(date) + 10 if date else 0
        p.setFont(self.f_title)
        p.setPen(theme.text)
        p.drawText(QPointF(x0, r.y() + 24), fm_t.elidedText(title, Qt.TextElideMode.ElideRight, x1 - x0 - dw))
        p.setFont(self.f_sub)
        p.setPen(theme.accent if selected else theme.muted)
        p.drawText(QPointF(x0, r.y() + 43), fm_s.elidedText(sub, Qt.TextElideMode.ElideRight, x1 - x0))
        if date:
            p.setFont(self.f_date)
            p.setPen(theme.subtle if not selected else theme.muted)
            p.drawText(QRectF(x1 - dw, r.y() + 10, dw, 18),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, date)
        p.restore()


class ReplayListView(QListView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setItemDelegate(ReplayDelegate(self))


class BrandMark(QWidget):
    """App logo: a hit circle with the average-hit cross, on an accent tile."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, _e):
        p = painter(self)
        r = QRectF(self.rect())
        g = QLinearGradient(0, 0, r.width(), r.height())
        g.setColorAt(0, theme.accent_hover)
        g.setColorAt(1, theme.accent_pressed)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, 10, 10)
        c = r.center()
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = p.pen()
        pen.setColor(theme.on_accent)
        pen.setWidthF(2.2)
        pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(pen)
        p.drawEllipse(c, 10, 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.on_accent)
        p.drawEllipse(QPointF(c.x() + 3, c.y() - 2), 3, 3)


class Sidebar(Surface):
    """selectionCommitted(paths): the user settled on a selection (debounced).
    openRequested / refreshRequested / chooseFolderRequested: header and footer buttons."""

    selectionCommitted = Signal(list)
    openRequested = Signal()
    refreshRequested = Signal()
    chooseFolderRequested = Signal()

    def __init__(self, parent=None):
        super().__init__("surface", parent)
        self.setFixedWidth(340)
        self.entries, self.current = [], []
        self._syncing = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(0)

        name = QVBoxLayout()
        name.setSpacing(0)
        name.addWidget(label("Hit Analyzer", "h3"))
        name.addWidget(label(f"for osu!  ·  v{__version__}", "caption"))
        brand = hbox(BrandMark(), spacing=12, margins=(6, 0, 0, 0))
        brand.addLayout(name)
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addSpacing(22)

        self.count = Chip("0")
        refresh = IconButton(icons.REFRESH, "Rescan the replays (F5)", size=30)
        refresh.clicked.connect(self.refreshRequested)
        add = IconButton(icons.ADD, "Open replay files (Ctrl+O)", size=30)
        add.clicked.connect(self.openRequested)
        lay.addLayout(hbox(label("Replays", "h3"), self.count, None, refresh, add, spacing=6,
                           margins=(6, 0, 0, 0)))
        lay.addSpacing(10)

        self.search = SearchField("Filter by map, difficulty, player...")
        self.search.textChanged.connect(lambda _t: self._fill())
        lay.addWidget(self.search)
        lay.addSpacing(10)

        self.model = ReplayListModel(self)
        self.list = ReplayListView()
        self.list.setModel(self.model)
        self.list.selectionModel().selectionChanged.connect(self._selection_changed)
        lay.addWidget(self.list, 1)

        self.empty = label("No replays found", "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)

        lay.addSpacing(10)
        self.hint = label("Click a replay  ·  Ctrl/Shift+click to combine", "caption")
        self.hint.setContentsMargins(6, 0, 0, 0)
        lay.addWidget(self.hint)
        self.folder_btn = Button("Choose your osu! folder", icons.FOLDER, "primary")
        self.folder_btn.clicked.connect(self.chooseFolderRequested)
        lay.addSpacing(8)
        lay.addWidget(self.folder_btn)

        self._commit_timer = QTimer(self, singleShot=True, interval=250)
        self._commit_timer.timeout.connect(self._commit)

    # --------------------------------------------------------------- data --

    def set_entries(self, entries, has_folder=True):
        self.entries = list(entries)
        self.count.set_text(str(len(self.entries)))
        self.folder_btn.setVisible(not has_folder)
        self._fill()

    def set_current(self, paths):
        """Show these replays as selected (without re-triggering an analysis)."""
        self.current = [Path(p) for p in paths]
        self._select_current()

    def clear_filter(self):
        self.search.clear()

    def focus_search(self):
        self.search.focus()

    def _fill(self):
        words = self.search.text().lower().split()
        shown = [p for p in self.entries if all(w in p.name.lower() for w in words)]
        self._syncing = True
        self.model.set_paths(shown)
        self._syncing = False
        self.empty.setVisible(not shown)
        self.empty.setText("No replays found" if not words else "No replay matches the filter")
        self._select_current()

    def _select_current(self):
        rows = [i for i, p in enumerate(self.model.paths) if p in self.current]
        sel = QItemSelection()
        for r in rows:
            idx = self.model.index(r)
            sel.select(idx, idx)
        self._syncing = True
        self.list.selectionModel().select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if rows:
            self.list.selectionModel().setCurrentIndex(self.model.index(rows[0]),
                                                       QItemSelectionModel.SelectionFlag.NoUpdate)
            self.list.scrollTo(self.model.index(rows[0]))
        self._syncing = False

    # ---------------------------------------------------------- selection --

    def _selection_changed(self, *_):
        if not self._syncing:
            self._commit_timer.start()

    def _commit(self):
        rows = sorted(i.row() for i in self.list.selectionModel().selectedRows())
        paths = [self.model.paths[r] for r in rows]
        if paths and paths != self.current:
            self.current = paths
            self.selectionCommitted.emit(paths)
