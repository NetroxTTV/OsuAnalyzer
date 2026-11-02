"""History page: how your unstable rate, accuracy and aim evolve over time."""

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QListView, QMessageBox, QStackedLayout, QStyle,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

from ...palette import BAD, GOOD, GRADE_COLORS
from .. import icons
from ..theme import qcolor, theme
from ..widgets import Button, Card, EmptyState, ProgressBar, SegmentedControl, hbox, label, painter
from .chart import METRIC_BY_KEY, METRICS, HistoryChart, Metric
from .importer import HistoryImporter

RANGES = [(7, "7 days"), (30, "30 days"), (90, "90 days"), (0, "All")]
IMPORT_COUNT = 50
COMPARE = 10            # tiles compare the last 10 replays with the 10 before


class StatTile(Card):
    """Label, value, and the change between the last replays and the ones before."""

    def __init__(self, name, parent=None):
        super().__init__(parent, padding=(18, 14, 18, 14), spacing=2)
        self.body.addWidget(label(name, "caption"))
        self.value = label("-", "metric-sm")
        self.delta = label("", "caption")
        self.body.addWidget(self.value)
        self.body.addWidget(self.delta)

    def set(self, value, delta="", good=None):
        self.value.setText(value)
        self.delta.setText(delta)
        colour = theme.muted.name() if good is None else (GOOD if good else BAD)
        self.delta.setStyleSheet(f"color: {colour};")


def compare(entries, metric: Metric):
    """(average, delta text, improved?) over the entries; the delta compares the last
    COMPARE replays with the COMPARE before them."""
    values = [metric.value(e) for e in entries]
    if not values:
        return "-", "", None
    avg = metric.text(sum(values) / len(values))
    k = min(COMPARE, len(values) // 2)
    if k < 3:
        return avg, "Not enough replays to compare yet", None
    new = sum(values[-k:]) / k
    old = sum(values[-2 * k:-k]) / k
    gain = metric.improvement(old, new)
    arrow = "▲" if new > old else "▼" if new < old else "="
    diff = metric.fmt.format(abs(new - old)).lstrip("+")
    word = "better" if gain > 0 else "worse" if gain < 0 else "same"
    return avg, f"{arrow} {diff} {word}, last {k} vs the {k} before", (gain > 0) if gain else None


# ------------------------------------------------------------------ table --

COLUMNS = [("Mods", 70), ("Accuracy", 78), ("UR", 64), ("Aim offset", 84), ("Misses", 60)]
DATE_W, BADGE_W = 104, 40


def column_rects(rect):
    """{name: QRectF} for a row (or the header) of the given rect."""
    out = {"Date": QRectF(rect.x() + 14, rect.y(), DATE_W, rect.height())}
    out["Grade"] = QRectF(out["Date"].right(), rect.y(), BADGE_W, rect.height())
    x = rect.right() - 14
    for name, w in reversed(COLUMNS):
        out[name] = QRectF(x - w, rect.y(), w, rect.height())
        x -= w
    out["Map"] = QRectF(out["Grade"].right() + 8, rect.y(), x - out["Grade"].right() - 16, rect.height())
    return out


def cell_texts(e):
    return {"Date": e.date.astimezone().strftime("%b %d  %H:%M"), "Map": e.map_name,
            "Mods": "" if e.mods == "NM" else f"+{e.mods}", "Accuracy": f"{e.accuracy * 100:.2f}%",
            "UR": f"{e.ur:.1f}", "Aim offset": f"{e.offset * 100:.1f}%", "Misses": str(e.misses)}


class HistoryModel(QAbstractListModel):
    EntryRole = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []

    def set_entries(self, entries):
        self.beginResetModel()
        self.entries = list(entries)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        if role == self.EntryRole:
            return e
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{e.map_name}\n{e.player}  ·  {e.max_combo}x combo\nClick to open this replay"
        return None


class HistoryDelegate(QStyledItemDelegate):
    ROW = 40

    def sizeHint(self, _option, _index):
        return QSize(400, self.ROW)

    def paint(self, p, option, index):
        e = index.data(HistoryModel.EntryRole)
        r = QRectF(option.rect).adjusted(4, 1, -4, -1)
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        if option.state & QStyle.StateFlag.State_MouseOver:
            p.setBrush(qcolor("#ffffff", 0.045))
            p.drawRoundedRect(r, 8, 8)
        cols, texts = column_rects(r), cell_texts(e)
        badge = QRectF(0, 0, 28, 24)
        badge.moveCenter(cols["Grade"].center())
        colour = qcolor(GRADE_COLORS.get(e.grade, theme.muted.name()))
        p.setBrush(qcolor(colour, 0.15))
        p.drawRoundedRect(badge, 7, 7)
        p.setFont(theme.bold(8.5))
        p.setPen(colour)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, e.grade.replace("H", ""))
        for name, text in texts.items():
            rect = cols[name]
            p.setFont(theme.semibold(9.5) if name == "Map" else theme.font(9))
            p.setPen(theme.text if name in ("Map", "Accuracy", "UR") else theme.muted)
            align = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if name in ("Date", "Map")
                                                     else Qt.AlignmentFlag.AlignRight)
            p.drawText(rect, align, p.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width())))
        p.restore()


class TableHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)

    def paintEvent(self, _e):
        p = painter(self)
        p.setFont(theme.bold(8))
        p.setPen(theme.muted)
        for name, rect in column_rects(QRectF(self.rect()).adjusted(4, 0, -4, 0)).items():
            if name == "Grade":
                continue
            align = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if name in ("Date", "Map")
                                                     else Qt.AlignmentFlag.AlignRight)
            p.drawText(rect, align, name.upper())


# ------------------------------------------------------------------- page --

class HistoryPage(QWidget):
    """openRequested(path): open a replay from the history."""

    openRequested = Signal(str)
    message = Signal(str)

    def __init__(self, history, library, parent=None):
        super().__init__(parent)
        self.history, self.library = history, library
        self.shown_metric = METRICS[0]
        self.days = 0
        self.slider_heads = True
        self._importer = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(14)

        self.metric_opt = SegmentedControl([(m.key, m.name) for m in METRICS], self.shown_metric.key)
        self.metric_opt.changed.connect(self._set_metric)
        self.range_opt = SegmentedControl(RANGES, self.days)
        self.range_opt.changed.connect(self._set_range)
        self.import_btn = Button("Add recent replays", icons.ADD, "secondary")
        self.import_btn.setToolTip(f"Analyse your {IMPORT_COUNT} newest replays that aren't in the history yet")
        self.import_btn.clicked.connect(self.start_import)
        self.clear_btn = Button("Clear", icons.DELETE, "ghost")
        self.clear_btn.setToolTip("Delete the whole history")
        self.clear_btn.clicked.connect(self._clear)
        self.import_status = label("", "caption")
        self.import_bar = ProgressBar()
        self.import_bar.setFixedWidth(160)
        self.import_bar.hide()
        outer.addLayout(hbox(self.metric_opt, 18, self.range_opt, None, self.import_status, self.import_bar,
                             12, self.import_btn, self.clear_btn, spacing=8))

        self.stack = QStackedLayout()
        outer.addLayout(self.stack, 1)
        self.empty = EmptyState(icons.HISTORY, "History",
                                "Every replay you analyse is saved here so you can follow your progress.\n"
                                f"Click \"Add recent replays\" to fill it with your {IMPORT_COUNT} latest plays.")
        self.stack.addWidget(self.empty)
        content = QWidget()
        self.stack.addWidget(content)
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(14)

        self.tiles = {"count": StatTile("Replays"), "ur": StatTile("Average unstable rate"),
                      "accuracy": StatTile("Average accuracy"), "offset": StatTile("Average aim offset")}
        row = hbox(spacing=14)
        for t in self.tiles.values():
            row.addWidget(t, 1)
        col.addLayout(row)

        chart_card = Card(padding=(20, 16, 20, 12), spacing=4)
        self.chart_title = label("", "h3")
        self.chart_note = label("Dots = each replay  ·  line = average of the last 5", "caption")
        chart_card.body.addLayout(hbox(self.chart_title, None, self.chart_note))
        self.chart = HistoryChart()
        self.chart.openRequested.connect(lambda e: self.openRequested.emit(e.replay_path))
        chart_card.body.addWidget(self.chart, 1)
        col.addWidget(chart_card, 3)

        table = Card(padding=(12, 12, 12, 8), spacing=2)
        table.body.addWidget(TableHeader())
        self.model = HistoryModel(self)
        self.list = QListView()
        self.list.setModel(self.model)
        self.list.setItemDelegate(HistoryDelegate(self.list))
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.list.clicked.connect(lambda i: self.openRequested.emit(i.data(HistoryModel.EntryRole).replay_path))
        table.body.addWidget(self.list, 1)
        col.addWidget(table, 2)

        theme.changed.connect(self.refresh)
        self.refresh()

    # ---------------------------------------------------------- page API --

    def set_analyses(self, _analyses):
        self.refresh()

    def refresh(self):
        entries = self.history.entries
        self.import_btn.setEnabled(self._importer is None and self.library.has_folder)
        self.clear_btn.setVisible(bool(entries))
        if not entries:
            self.stack.setCurrentWidget(self.empty)
            return
        self.stack.setCurrentIndex(1)
        if self.days:
            since = datetime.now(timezone.utc) - timedelta(days=self.days)
            entries = [e for e in entries if e.date >= since]

        self.tiles["count"].set(f"{len(entries):,}", "in this period" if self.days else "in total")
        for key in ("ur", "accuracy", "offset"):
            self.tiles[key].set(*compare(entries, METRIC_BY_KEY[key]))
        self.chart_title.setText(self.shown_metric.name + (f"  ({self.shown_metric.unit})" if self.shown_metric.unit else ""))
        self.chart.set_data(entries, self.shown_metric)
        self.model.set_entries(list(reversed(entries)))

    # ------------------------------------------------------------ actions --

    def _set_metric(self, key):
        self.shown_metric = METRIC_BY_KEY[key]
        self.refresh()

    def _set_range(self, days):
        self.days = days
        self.refresh()

    def start_import(self):
        if self._importer or not self.library.has_folder:
            return
        self._importer = HistoryImporter(self.history, self.library.install, self.library.entries,
                                         IMPORT_COUNT, self.slider_heads)
        self._importer.progress.connect(self._import_progress)
        self._importer.done.connect(self._import_done)
        self.import_btn.setEnabled(False)
        self.import_status.setText("Looking for new replays...")
        self.import_bar.set_indeterminate()
        self.import_bar.start()
        self.import_bar.show()
        self._importer.start()

    def _import_progress(self, done, total, text):
        if total:
            self.import_bar.set_range(done, total)
            self.import_status.setText(f"Analysing {min(done + 1, total)} / {total}")
        self.import_status.setToolTip(text)

    def _import_done(self, added, skipped):
        self._importer.wait()
        self._importer = None
        self.import_bar.stop()
        self.import_bar.hide()
        self.import_status.setText("")
        if added or skipped:
            text = f"Added {added} replay{'s' if added != 1 else ''} to the history"
            if skipped:
                text += f" ({skipped} skipped: beatmap not found or unreadable)"
        else:
            text = "Your history already has all your recent replays"
        self.message.emit(text)
        self.refresh()

    def _clear(self):
        answer = QMessageBox.question(self, "Clear history",
                                      f"Delete all {len(self.history)} replays from the history?\n"
                                      "Your replay files are not touched.")
        if answer == QMessageBox.StandardButton.Yes:
            self.history.clear()
            self.refresh()

    def shutdown(self):
        if self._importer:
            self._importer.stop()
            self._importer.wait(3000)
