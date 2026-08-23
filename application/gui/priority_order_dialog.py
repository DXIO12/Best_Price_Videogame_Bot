"""Hand-order the merged list before an import is written.

Reached from the import dialog's "sort by hand" placement. It runs *before*
anything reaches the database, so the imported rows have no id yet — each row is
an opaque token from ``product_io.merge_order_tokens``, and only
``product_io.apply_merge`` turns the returned order into real priority values.
Cancelling here cancels the whole import.
"""

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from application.gui.priority_table import PriorityTableWidget
from application.language_selector import tr

# Matches the main window's table, so the two read as the same list.
ROW_HEIGHT = 36


class PriorityOrderDialog(QDialog):
    """Drag-and-drop ordering over ``merge_order_tokens`` rows.

    ``rows`` is [(token, product_name, platform_label, is_new)]; after exec()
    returns Accepted, :meth:`ordered_tokens` gives that list's tokens in the
    order the user left them."""

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("order_priority.window_title"))
        self.resize(560, 560)
        self._rows = list(rows)
        self._setup_ui()
        self._reload()

    # -- construction -------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout()

        heading = QLabel(tr("order_priority.heading"))
        layout.addWidget(heading)

        new_count = sum(1 for row in self._rows if row[3])
        subtitle = QLabel(tr(
            "order_priority.subtitle",
            current=len(self._rows) - new_count,
            new=new_count,
        ))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("QLabel { color: #9e9e9e; }")
        layout.addWidget(subtitle)

        self.table = PriorityTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            tr("order_priority.header_priority"),
            tr("order_priority.header_product"),
            tr("order_priority.header_platform"),
            tr("order_priority.header_origin"),
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )

        # Same interaction contract as the main window's table: whole-row
        # selection, single selection, internal move, nothing editable in place.
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.table.setDragDropOverwriteMode(False)
        self.table.setDragEnabled(True)
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(
            "QTableWidget::item:selected { background-color: #47474e; color: white; }"
        )
        self.table.rowDropped.connect(self._on_row_dropped)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        buttons.addStretch()
        accept_button = QPushButton(tr("common.accept"))
        accept_button.setDefault(True)
        accept_button.clicked.connect(self.accept)
        cancel_button = QPushButton(tr("common.cancel"))
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(accept_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        self.setLayout(layout)

    # -- rendering ----------------------------------------------------------

    def _reload(self, select: int | None = None):
        """Rebuild every row from ``self._rows`` — the list is the model.

        Full rebuild rather than in-place edits for the same reason the main
        window does it: the rank column is a cell *widget*, and Qt's own move
        machinery does not carry those with the row."""
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._rows))

        last = len(self._rows) - 1
        for index, (_token, name, platform, is_new) in enumerate(self._rows):
            self.table.setItem(index, 1, QTableWidgetItem(name))
            self.table.setItem(index, 2, QTableWidgetItem(platform))

            origin = QTableWidgetItem(
                tr("order_priority.origin_new") if is_new
                else tr("order_priority.origin_current")
            )
            if is_new:
                # Blue is the app's "informational" accent (the ℹ buttons in
                # Settings); nothing here is destructive, so no red.
                origin.setForeground(Qt.GlobalColor.cyan)
            self.table.setItem(index, 3, origin)

            self._set_rank_cell_widget(index, is_first=(index == 0), is_last=(index == last))
            self.table.setRowHeight(index, ROW_HEIGHT)

        if select is not None and 0 <= select < len(self._rows):
            self.table.selectRow(select)

    def _set_rank_cell_widget(self, row: int, is_first: bool, is_last: bool):
        """Rank number plus ▲▼ nudges — the same widget the main window builds,
        for the same reason: moving a row exactly one place by dragging is
        fiddly."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 2, 0)
        layout.setSpacing(2)
        layout.addWidget(QLabel(str(row + 1)))

        up_button = QToolButton()
        up_button.setText("▲")
        up_button.setAutoRaise(True)
        up_button.setFixedSize(16, 16)
        up_button.setEnabled(not is_first)
        up_button.clicked.connect(lambda _checked, index=row: self._move(index, -1))

        down_button = QToolButton()
        down_button.setText("▼")
        down_button.setAutoRaise(True)
        down_button.setFixedSize(16, 16)
        down_button.setEnabled(not is_last)
        down_button.clicked.connect(lambda _checked, index=row: self._move(index, 1))

        layout.addWidget(up_button)
        layout.addWidget(down_button)
        self.table.setCellWidget(row, 0, container)

    # -- reordering ---------------------------------------------------------

    def _move(self, index: int, direction: int):
        target = index + direction
        if not (0 <= index < len(self._rows)) or not (0 <= target < len(self._rows)):
            return
        self._rows[index], self._rows[target] = self._rows[target], self._rows[index]
        self._reload(select=target)

    def _on_row_dropped(self, source_row: int, target_row: int):
        """``target_row`` is an insert position in the pre-removal indexing, so
        it shifts by one once the dragged row is taken out from above it —
        the same correction the main window applies."""
        if not 0 <= source_row < len(self._rows):
            return
        moving = self._rows.pop(source_row)
        insert_at = target_row - 1 if target_row > source_row else target_row
        insert_at = max(0, min(insert_at, len(self._rows)))
        self._rows.insert(insert_at, moving)
        self._reload(select=insert_at)

    # -- result -------------------------------------------------------------

    def ordered_tokens(self) -> list[tuple]:
        return [row[0] for row in self._rows]
