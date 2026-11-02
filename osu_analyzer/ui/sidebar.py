"""Left sidebar: app name, replay search and the replay list."""

from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QItemSelection, QItemSelectionModel, QModelIndex,
                            QPointF, QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import (QAbstractItemView, QListView, QStyle, QStyledItemDelegate, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..core import MODE_NAMES, read_replay_header, replay_label
from ..palette import GRADE_COLORS
from . import icons
from .theme import qcolor, theme
from .widgets import BrandMark, Button, Chip, IconButton, SearchField, Surface, hbox, label

ROW_HEIGHT = 62


class ReplayListModel(QAbstractListModel):
    """Replay paths with their display labels (title, subtitle, date) and, read on demand
    for the rows on screen, their header (accuracy, grade, mods, combo)."""

    LabelRole = Qt.ItemDataRole.UserRole + 1
    HeaderRole = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.paths = []
        self._labels = {}
        self._headers = {}     # path -> Replay header, or None when unreadable

    def set_paths(self, paths):
        self.beginResetModel()
        self.paths = list(paths)
        for p in self.paths:
            if p not in self._labels:
                self._labels[p] = replay_label(p)
        self.endResetModel()

    def header(self, p):
        if p not in self._headers:
            try:
                self._headers[p] = read_replay_header(p)
            except (OSError, ValueError, EOFError):
                self._headers[p] = None
        return self._headers[p]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.paths)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self.paths[index.row()]
        if role == self.LabelRole:
            return self._labels[p]
        if role == self.HeaderRole:
            return self.header(p)
        if role == Qt.ItemDataRole.DisplayRole:
            return self._labels[p][0]
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(p)
        return None

    def _tooltip(self, p):
        h = self.header(p)
        if h is None:
            return p.name
        if h.mode != 0:
            return f"{p.name}\n{MODE_NAMES.get(h.mode, 'other mode')} replay (only osu!standard is analysed)"
        return (f"{p.name}\n{h.accuracy * 100:.2f}%  ·  {h.grade}  ·  {h.max_combo}x combo  ·  +{h.mod_string}\n"
                f"300: {h.n300}   100: {h.n100}   50: {h.n50}   miss: {h.nmiss}")


class ReplayDelegate(QStyledItemDelegate):
    """Rounded rows: grade badge, title + accuracy, 'difficulty · player' + mods, misses and date."""

    BADGE = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self.f_title = theme.semibold(10)
        self.f_sub = theme.font(9)
        self.f_grade = theme.bold(10)
        self.f_acc = theme.semibold(9.5)

    def sizeHint(self, _option, _index):
        return QSize(200, ROW_HEIGHT)

    def paint(self, p, option, index):
        title, sub, date = index.data(ReplayListModel.LabelRole)
        h = index.data(ReplayListModel.HeaderRole)
        standard = h is not None and h.mode == 0
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

        # Grade badge
        badge = QRectF(r.x() + 12, r.center().y() - self.BADGE / 2, self.BADGE, self.BADGE)
        grade = h.grade if standard else ("–" if h is not None else "?")
        colour = qcolor(GRADE_COLORS.get(grade, theme.muted.name()))
        p.setBrush(qcolor(colour, 0.15) if standard else qcolor("#ffffff", 0.05))
        p.drawRoundedRect(badge, 9, 9)
        p.setFont(self.f_grade)
        p.setPen(colour if standard else theme.subtle)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, grade.replace("H", ""))

        x0, x1 = badge.right() + 12, r.right() - 12
        fm_t, fm_s, fm_a = QFontMetricsF(self.f_title), QFontMetricsF(self.f_sub), QFontMetricsF(self.f_acc)
        y1, y2 = r.y() + 25, r.y() + 44

        # Line 1: title ............ accuracy
        acc = f"{h.accuracy * 100:.2f}%" if standard else (MODE_NAMES.get(h.mode, "") if h else "")
        aw = fm_a.horizontalAdvance(acc) + 10 if acc else 0
        p.setFont(self.f_acc)
        p.setPen(theme.text if standard else theme.subtle)
        p.drawText(QRectF(x1 - aw, y1 - 14, aw, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   acc)
        p.setFont(self.f_title)
        p.setPen(theme.text)
        p.drawText(QPointF(x0, y1), fm_t.elidedText(title, Qt.TextElideMode.ElideRight, x1 - x0 - aw))

        # Line 2: difficulty · player ............ +mods · misses · date
        right = []
        if standard and h.mod_string != "NM":
            right.append(f"+{h.mod_string}")
        if standard and h.nmiss:
            right.append(f"{h.nmiss}✕")
        if date:
            right.append(date)
        right = "  ·  ".join(right)
        rw = fm_s.horizontalAdvance(right) + 10 if right else 0
        p.setFont(self.f_sub)
        p.setPen(theme.muted)
        p.drawText(QRectF(x1 - rw, y2 - 13, rw, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   right)
        p.setPen(theme.accent if selected else theme.muted)
        p.drawText(QPointF(x0, y2), fm_s.elidedText(sub, Qt.TextElideMode.ElideRight, x1 - x0 - rw))
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
