import sys
import threading
from config.runtime_config import init_runtime_mode
from bot.bot import load_settings
from gui.add_product_dialog import AddProductDialog, get_available_shops
from gui.delete_product_dialog import DeleteProductDialog
from gui.modify_product_dialog import ModifyProductDialog
from gui.settings_bot import SettingsBotDialog
from services.product_service import (
    get_products_with_shops,
    to_gui_names,
    get_platform_priorities,
    reorder_platform_priorities,
    delete_product_platforms,
    delete_products,
)
from PyQt6 import sip
from PyQt6.QtCore import QThreadPool, Qt, QTimer, pyqtSignal, QByteArray, QSize
from PyQt6.QtGui import QCursor, QIcon, QPixmap, QPainter
from PyQt6.QtSvg import QSvgRenderer
from database.db import SessionLocal
from database.models import ProductShop, Setting
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QAbstractItemView,
    QToolButton,
    QToolTip
)

from gui.bot_worker import BotWorker
from services.resolver_worker import ResolverWorker, RetryWorker
from services.resolve_urls_service import MAX_RETRIES


# Grey pencil "edit" icon (Material "edit" glyph path), kept inline so no image
# asset file or PyInstaller --add-data entry is needed. Rendered to a QIcon at
# runtime — clearer than a text pencil glyph, which read ambiguously. Grey (not
# red) so it doesn't read as a destructive action like the red delete icon.
_EDIT_ICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path fill="#9e9e9e" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25z'
    b'M20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0'
    b'l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>'
)


def _render_svg_icon(svg_bytes: bytes, size: int = 64) -> QIcon:
    """Render an inline SVG to a QIcon. A QApplication must already exist."""
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class PriorityTableWidget(QTableWidget):
    """QTableWidget whose drop handling is fully overridden.

    Qt's built-in InternalMove drag-and-drop only relocates the
    QTableWidgetItems, not cell widgets (we use a QLabel for the Shops
    column), which desyncs rows after a drag. Instead we just figure out
    source/target row and let the owner rebuild the whole table from the
    database, which keeps items and cell widgets consistent.
    """

    rowDropped = pyqtSignal(int, int)  # source_row, target_row

    def dropEvent(self, event):
        source_row = self.currentRow()
        pos = event.position().toPoint()
        index = self.indexAt(pos)

        # Threshold is 15% of the row's height into the hovered row.
        # Dragging downward: crossing just the top 15% of a lower row is
        # enough to register "insert below it". Dragging upward: crossing
        # just the bottom 15% of a higher row is enough for "insert above
        # it". This needs noticeably less mouse travel than a full half-row
        # crossing, so a one-row move triggers sooner and feels snappier.
        if index.isValid():
            row_rect = self.visualRect(index)
            hovered_row = index.row()
            if hovered_row > source_row:
                threshold_y = row_rect.top() + row_rect.height() * 0.15
            elif hovered_row < source_row:
                threshold_y = row_rect.top() + row_rect.height() * 0.85
            else:
                threshold_y = row_rect.center().y()
            target_row = hovered_row if pos.y() < threshold_y else hovered_row + 1
        else:
            target_row = self.rowCount()

        # Tell Qt the drop was a no-op (IgnoreAction) rather than a Move.
        # If we let it resolve as a Move, QAbstractItemView's own internals
        # delete the dragged row *after* this method returns — on top of
        # whatever we already did — which silently drops a row from the
        # table. We handle the reorder entirely ourselves, so Qt must not
        # touch the model at all.
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()

        if source_row != -1 and target_row != source_row and target_row != source_row + 1:
            self.rowDropped.emit(source_row, target_row)


class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Price Bot")

        self.resize(1200, 700)
        self._center_on_screen()

        self.thread_pool = QThreadPool()

        # Recurring bot state
        self.bot_running = False
        self.bot_worker_active = False
        self.bot_stop_event = threading.Event()
        self.bot_schedule_timer = QTimer()
        self.bot_schedule_timer.setSingleShot(True)
        # PreciseTimer so remainingTime() reflects the real interval — the
        # default CoarseTimer rounds by up to 5%, which would inflate the
        # countdown reading (and slightly skew the schedule itself).
        self.bot_schedule_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.bot_schedule_timer.timeout.connect(self._launch_bot_worker)
        # Ticks once a minute while the bot waits between passes, to refresh the
        # "next automatic check in N min" countdown shown in the status label.
        self.countdown_timer = QTimer()
        self.countdown_timer.setInterval(60_000)
        self.countdown_timer.timeout.connect(self._update_countdown)

        # Pre-rendered red pencil icon for the per-row quick-edit button.
        self._edit_icon = _render_svg_icon(_EDIT_ICON_SVG)

        # Re-issues the unavailable-store tooltip on an interval so it stays
        # visible for as long as the cursor rests on the ⚠ marker, instead of
        # vanishing after QToolTip's own short default display duration.
        # Set up before setup_ui/load_products, which already clear it.
        self._shop_tooltip_target = None
        self._shop_tooltip_timer = QTimer(self)
        self._shop_tooltip_timer.timeout.connect(self._refresh_shop_tooltip)

        self.setup_ui()

        self.load_products()

        # Check for pending URL retries every 5 minutes
        self.retry_timer = QTimer()
        self.retry_timer.timeout.connect(self.check_retry_queue)
        self.retry_timer.start(5 * 60 * 1000)

    def _center_on_screen(self):
        """Centre the window on the largest connected screen — Qt otherwise
        places new top-level windows at (0, 0) on the primary screen, which
        may not be the biggest one in a multi-monitor setup."""
        screens = QApplication.screens()
        largest_screen = max(
            screens,
            key=lambda screen: screen.geometry().width() * screen.geometry().height()
        )
        screen_geometry = largest_screen.availableGeometry()
        frame_geometry = self.frameGeometry()
        frame_geometry.moveCenter(screen_geometry.center())
        self.move(frame_geometry.topLeft())

    def setup_ui(self):

        # MAIN LAYOUT
        main_layout = QVBoxLayout()

        # TITLE
        title = QLabel("Game Price Tracker")

        main_layout.addWidget(title)

        # BUTTON LAYOUT
        button_layout = QHBoxLayout()

        self.add_product_button = QPushButton(
            "Add Product"
        )

        self.delete_product_button = QPushButton(
            "Delete Product"
        )

        self.modify_product_button = QPushButton(
            "Modify Product"
        )

        self.update_urls_button = QPushButton(
            "Update URLs"
        )
        self.update_urls_button.setMinimumWidth(180)

        self.settings_bot_button = QPushButton(
            "Settings Bot"
        )
        self.settings_bot_button.setMinimumWidth(180)

        self.start_bot_button = QPushButton(
            "Start Bot"
        )
        self.start_bot_button.setMinimumWidth(180)

        self.stop_bot_button = QPushButton(
            "Stop Bot"
        )
        self.stop_bot_button.setMinimumWidth(180)
        self.stop_bot_button.setEnabled(False)

        # CONNECT BUTTONS
        self.add_product_button.clicked.connect(
            self.open_add_product_dialog
        )
        self.delete_product_button.clicked.connect(
            self.open_delete_product_dialog
        )
        self.modify_product_button.clicked.connect(
            lambda: self.open_modify_product_dialog()
        )
        self.update_urls_button.clicked.connect(self.on_update_urls_clicked)
        self.settings_bot_button.clicked.connect(self.open_settings_bot_dialog)
        self.start_bot_button.clicked.connect(self.start_bot_worker)
        self.stop_bot_button.clicked.connect(self.stop_bot_worker)

        # Order: Add · Modify · Delete — "Delete" sits at the far right, away
        # from the others, to reduce the chance of an accidental deletion.
        button_layout.addWidget(
            self.add_product_button
        )

        button_layout.addWidget(
            self.modify_product_button
        )

        button_layout.addWidget(
            self.delete_product_button
        )

        main_layout.addLayout(button_layout)

        # PRODUCT TABLE
        self.product_table = PriorityTableWidget()

        self.product_table.setWordWrap(True)
        self.product_table.setColumnCount(8)
        # We render our own "#" priority column — Qt's default row-number
        # header would otherwise show a second, redundant number.
        self.product_table.verticalHeader().setVisible(False)

        self.product_table.setHorizontalHeaderLabels([
            "Priority",
            "Product",
            "Platform",
            "Target Price",
            "Shops",
            "Best Price",
            "",
            ""
        ])

        self.product_table.horizontalHeaderItem(4).setToolTip(
            "Shop status icons (hover one for details):\n"
            "✖  no URL yet\n"
            "⏳  URL failed — retry scheduled\n"
            "⚠ (red)  URL failed — retries exhausted\n"
            "❗ (yellow)  no price found (product unavailable)"
        )
        self.product_table.horizontalHeaderItem(0).setToolTip(
            "Search priority. Drag rows to reorder — the bot searches\n"
            "lower-numbered rows first."
        )

        self.product_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.product_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeaderItem(6).setToolTip("Edit this product")
        self.product_table.horizontalHeaderItem(7).setToolTip("Delete this product")

        # Drag-and-drop row reordering (Amazon-list style) — each row is one
        # product+platform combination with its own independent priority.
        self.product_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.product_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.product_table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.product_table.setDragDropOverwriteMode(False)
        self.product_table.setDragEnabled(True)
        self.product_table.setSortingEnabled(False)
        # Product cells are read-only: edits happen only through the Modify
        # Product dialog (button or double-click), never inline. This does not
        # affect row selection or InternalMove drag-and-drop.
        self.product_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.product_table.rowDropped.connect(self.on_row_dropped)
        # Double-click a row to modify that product.
        self.product_table.cellDoubleClicked.connect(self.on_row_double_clicked)
        # Grey instead of the default blue for the row being dragged/selected.
        self.product_table.setStyleSheet(
            "QTableWidget::item:selected { background-color: #47474e; color: white; }"
        )


        main_layout.addWidget(self.product_table)

        # UPDATE URLs + SETTINGS BOT (row 1)
        control_button_layout = QHBoxLayout()
        control_button_layout.addStretch()
        control_button_layout.addWidget(self.update_urls_button)
        control_button_layout.addWidget(self.settings_bot_button)
        control_button_layout.addStretch()
        main_layout.addLayout(control_button_layout)

        # START BOT (row 2, centered)
        start_button_layout = QHBoxLayout()
        start_button_layout.addStretch()
        start_button_layout.addWidget(self.start_bot_button)
        start_button_layout.addWidget(self.stop_bot_button)
        start_button_layout.addStretch()
        main_layout.addLayout(start_button_layout)

        self.status_label = QLabel("Ready")
        main_layout.addWidget(self.status_label)

        self.setLayout(main_layout)

    # =========================================
    # OPEN ADD PRODUCT DIALOG
    # =========================================

    def open_add_product_dialog(self):

        dialog = AddProductDialog()
        
        # Refresh table when product is added
        dialog.product_added.connect(self.on_product_added)
        dialog.exec()

    # =========================================
    # OPEN DELETE PRODUCT DIALOG
    # =========================================

    def open_delete_product_dialog(self):

        dialog = DeleteProductDialog()
        
        # Refresh table when product is deleted
        dialog.product_deleted.connect(self.load_products)
        dialog.exec()

    # =========================================
    # OPEN MODIFY PRODUCT DIALOG
    # =========================================

    def open_modify_product_dialog(self, preselect_product_id=None):

        dialog = ModifyProductDialog(preselect_product_id=preselect_product_id)

        # Refresh table when product is modified
        dialog.product_modified.connect(self.load_products)
        dialog.exec()

    # =========================================
    # DOUBLE-CLICK A ROW -> MODIFY THAT PRODUCT
    # =========================================

    def on_row_double_clicked(self, row, column):
        # The product id is stored on the name cell (column 1) in load_products.
        name_item = self.product_table.item(row, 1)
        if name_item is None:
            return
        product_id = name_item.data(Qt.ItemDataRole.UserRole)
        if product_id is None:
            # The pinned "+" row (row 0) has no product behind it.
            return
        self.open_modify_product_dialog(preselect_product_id=product_id)

    # =========================================
    # LOAD PRODUCTS IN THE TABLE
    # =========================================

    # Per-shop status markers, rendered as links (not <span title="">) because
    # QLabel's rich text engine does not turn the HTML "title" attribute into
    # a hover tooltip — only anchors emit linkHovered, which
    # _on_shop_link_hovered listens to in order to show the right text below.
    SHOP_MARKER_TOOLTIPS = {
        "no_url": "No URL assigned yet — waiting for the first search attempt",
        "retry_scheduled": "URL lookup failed — a retry is scheduled",
        "retry_exhausted": "URL lookup failed after all retries — set the URL manually",
        "unavailable": "The store does not have the selected product available",
    }
    NO_URL_MARKER = ' <a href="no_url" style="text-decoration:none;">✖</a>'
    RETRY_SCHEDULED_MARKER = ' <a href="retry_scheduled" style="text-decoration:none;">⏳</a>'
    RETRY_EXHAUSTED_MARKER = (
        ' <a href="retry_exhausted" style="color:#cc3333; text-decoration:none;">⚠</a>'
    )
    # Plain "!" rather than the ❗ emoji codepoint: that symbol defaults to
    # colour-emoji presentation on this system's font, which ignores the
    # CSS `color` below and always renders red/orange regardless of style.
    UNAVAILABLE_MARKER = (
        ' <a href="unavailable" style="color:#e6b800; text-decoration:none;">!</a>'
    )

    @staticmethod
    def _build_shops_html(shop_records, all_shops) -> str:
        """Build the Shops column as rich text (HTML) for one product row.

        Per-shop markers:
          ✖  no URL yet (first attempt not done)
          ⏳  URL failed, retry scheduled
          ⚠ (red)  URL failed, all retries exhausted
          ❗ (yellow)  URL resolved but the last check found no price (unavailable)
        Collapses to "ALL" only when every shop has a URL and none are unavailable.
        """
        from html import escape

        norm_all = {s.strip().lower() for s in all_shops}
        norm_records = {r.shop.strip().lower() for r in shop_records}

        all_have_url = norm_records == norm_all and all(r.url for r in shop_records)
        none_unavailable = all(r.available is not False for r in shop_records)
        if all_have_url and none_unavailable:
            return "ALL"

        seen: set[str] = set()
        parts: list[str] = []
        for record in shop_records:
            key = record.shop.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            label = escape(record.shop.strip())
            if not record.url:
                retry = record.retry_count or 0
                if retry > MAX_RETRIES:
                    label += MainWindow.RETRY_EXHAUSTED_MARKER   # red ⚠
                elif retry > 0:
                    label += MainWindow.RETRY_SCHEDULED_MARKER   # ⏳
                else:
                    label += MainWindow.NO_URL_MARKER            # ✖
            elif record.available is False:
                # Prepended (not appended like the other markers) so the
                # unavailable warning catches the eye before the shop name.
                label = f"{MainWindow.UNAVAILABLE_MARKER.strip()} {label}"
            parts.append(label)
        return ", ".join(parts) if parts else "None"

    def _set_rank_cell_widget(self, row: int, rank: int, key: tuple, is_first: bool, is_last: bool):
        """Rank number plus small ▲▼ nudge buttons — moving a row by exactly
        one position via drag-and-drop is fiddly, so this gives a precise
        one-step alternative. The rank QTableWidgetItem underneath still
        holds the (product_id, platform_id) key used by drag reordering.

        `row` is the table row (offset by the pinned "+" row), while `rank` is
        the 1-based priority number actually shown to the user."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 2, 0)
        layout.setSpacing(2)

        rank_label = QLabel(str(rank))
        layout.addWidget(rank_label)

        up_button = QToolButton()
        up_button.setText("▲")
        up_button.setAutoRaise(True)
        up_button.setFixedSize(16, 16)
        up_button.setEnabled(not is_first and key[1] is not None)
        up_button.clicked.connect(lambda _checked, k=key: self.move_priority(k, -1))

        down_button = QToolButton()
        down_button.setText("▼")
        down_button.setAutoRaise(True)
        down_button.setFixedSize(16, 16)
        down_button.setEnabled(not is_last and key[1] is not None)
        down_button.clicked.connect(lambda _checked, k=key: self.move_priority(k, 1))

        layout.addWidget(up_button)
        layout.addWidget(down_button)
        self.product_table.setCellWidget(row, 0, container)

    def move_priority(self, key: tuple, direction: int):
        """Move a single (product_id, platform_id) row's priority up (-1) or
        down (+1) by exactly one position."""
        priorities = get_platform_priorities()
        ordered_keys = sorted(priorities, key=lambda k: priorities[k])
        if key not in ordered_keys:
            return

        index = ordered_keys.index(key)
        new_index = index + direction
        if new_index < 0 or new_index >= len(ordered_keys):
            return

        ordered_keys[index], ordered_keys[new_index] = ordered_keys[new_index], ordered_keys[index]
        reorder_platform_priorities(ordered_keys)
        self.load_products()

    def _set_add_row(self, row: int):
        """Pinned, non-editable first row whose only interactive element is a
        single '+' button spanning the edit + delete columns — a shortcut that
        opens the Add Product dialog. Kept as a real table row (not a bar above
        the table) so it lines up with the action columns."""
        # Blank, non-interactive cells for the data columns (0-5): enabled but
        # not selectable/editable/draggable, so this row can't be picked up by
        # the drag-and-drop reorder and never opens the modify dialog.
        for col in range(6):
            blank = QTableWidgetItem("")
            blank.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.product_table.setItem(row, col, blank)

        # A single '+' button spanning the edit (6) and delete (7) columns.
        self.product_table.setSpan(row, 6, 1, 2)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        add_button = QToolButton()
        add_button.setText("＋")
        add_button.setAutoRaise(True)
        add_button.setToolTip("Add a new product")
        add_button.setStyleSheet("QToolButton { font-size: 16px; font-weight: bold; }")
        add_button.clicked.connect(self.open_add_product_dialog)
        layout.addWidget(add_button)
        self.product_table.setCellWidget(row, 6, container)

    def _set_edit_cell_widget(self, row: int, product_id: int):
        """Small pencil-icon button for quick, per-row editing — opens the
        "Modify Product" dialog with this row's product preselected, mirroring
        the double-click gesture. Sits just left of the quick-delete icon."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.addStretch()

        edit_button = QToolButton()
        # Grey pencil icon (inline SVG → QIcon) — clearer than a text glyph.
        edit_button.setIcon(self._edit_icon)
        edit_button.setIconSize(QSize(16, 16))
        edit_button.setAutoRaise(True)
        edit_button.setToolTip("Edit this product")
        edit_button.clicked.connect(
            lambda _checked, pid=product_id:
                self.open_modify_product_dialog(preselect_product_id=pid)
        )

        layout.addWidget(edit_button)
        layout.addStretch()
        self.product_table.setCellWidget(row, 6, container)

    def _set_delete_cell_widget(self, row: int, product_id: int, product_name: str, platform_name):
        """Small red trash-icon button for quick, per-row deletion — an
        alternative to the "Delete Product" dialog for the common case of
        removing a single product/platform."""
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.addStretch()

        delete_button = QToolButton()
        delete_button.setText("🗑")
        delete_button.setAutoRaise(True)
        delete_button.setToolTip("Delete this product")
        delete_button.setStyleSheet("QToolButton { color: #cc3333; font-size: 14px; }")
        delete_button.clicked.connect(
            lambda _checked, pid=product_id, name=product_name, plat=platform_name:
                self.delete_row_clicked(pid, name, plat)
        )

        layout.addWidget(delete_button)
        layout.addStretch()
        self.product_table.setCellWidget(row, 7, container)

    def delete_row_clicked(self, product_id: int, product_name: str, platform_name):
        """Handler for the per-row quick-delete button: confirm, then remove
        just this product/platform (or the whole product if it has none)."""
        label = f"{product_name} ({platform_name})" if platform_name else product_name

        confirm = QMessageBox.question(
            self,
            "Confirm Delete",
            f'Are you sure you want to delete "{label}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        if platform_name:
            delete_product_platforms(product_id, [platform_name])
        else:
            delete_products([product_id])

        print(f"===================================")
        print(f"[Delete] '{label}' removed via quick delete.")

        self.load_products()

    def _set_shops_cell(self, row: int, shop_records, all_shops):
        """Render the Shops cell as a rich-text QLabel so the yellow ⚠ marker
        can be coloured independently of the rest of the cell text."""
        html = self._build_shops_html(shop_records, all_shops)
        widget = self.product_table.cellWidget(row, 4)
        if isinstance(widget, QLabel):
            widget.setText(html)
            return
        label = QLabel(html)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setContentsMargins(4, 0, 4, 0)
        label.setOpenExternalLinks(False)
        label.linkHovered.connect(self._on_shop_link_hovered)
        self.product_table.setCellWidget(row, 4, label)

    def _on_shop_link_hovered(self, url: str):
        """Keep a shop status marker's tooltip visible while hovering it."""
        text = self.SHOP_MARKER_TOOLTIPS.get(url)
        if text:
            label = self.sender()
            rect = label.rect()
            rect.moveTopLeft(label.mapToGlobal(rect.topLeft()))
            self._shop_tooltip_target = (label, rect, text)
            # Start before the first refresh: a refresh that decides to stop
            # (cursor already gone, label deleted) must not be re-armed here.
            self._shop_tooltip_timer.start(400)
            self._refresh_shop_tooltip()
        else:
            self._clear_shop_tooltip()

    def _clear_shop_tooltip(self):
        """Stop re-issuing the shop tooltip and drop the reference to its label.

        Must be called before any table rebuild: load_products() destroys every
        cell widget, and a timer still pointing at a destroyed QLabel takes the
        whole process down (see _refresh_shop_tooltip)."""
        self._shop_tooltip_timer.stop()
        self._shop_tooltip_target = None
        QToolTip.hideText()

    def _refresh_shop_tooltip(self):
        if self._shop_tooltip_target is None:
            self._shop_tooltip_timer.stop()
            return
        label, rect, text = self._shop_tooltip_target
        # The label's C++ object may already be gone (a table rebuild deletes
        # the cell widgets) while the Python wrapper survives here. Passing a
        # deleted wrapper to showText raises RuntimeError inside a slot, which
        # PyQt turns into qFatal — an instant "Aborted (core dumped)", not a
        # catchable error. Also stop once the cursor leaves the label: QLabel
        # only emits linkHovered("") if it still gets mouse events, so a label
        # the cursor left "sideways" (e.g. a dialog opening over it) would
        # otherwise keep this timer alive indefinitely.
        if sip.isdeleted(label) or not rect.contains(QCursor.pos()):
            self._clear_shop_tooltip()
            return
        QToolTip.showText(QCursor.pos(), text, label, rect)

    def load_products(self):

        # Every cell widget below is about to be destroyed, including the Shops
        # QLabel the tooltip timer may still be pointing at.
        self._clear_shop_tooltip()

        products_with_shops = get_products_with_shops()
        all_shops = get_available_shops()
        priorities = get_platform_priorities()

        # Build display rows — one per product+platform combination, each
        # carrying its own (product_id, platform_id) priority key so rows
        # for the same product can be reordered independently of each other.
        display_rows = []
        for product, shop_records in products_with_shops:
            if product.platforms:
                plats = to_gui_names([p.name for p in product.platforms])
                for platform, plat_display in zip(product.platforms, plats):
                    key = (product.id, platform.id)
                    priority = priorities.get(key, 0)
                    display_rows.append((priority, key, product, plat_display, shop_records, platform.name))
            else:
                # No platform assigned: nothing to key priority against in
                # product_platforms, so this row can't be drag-reordered.
                key = (product.id, None)
                display_rows.append((0, key, product, '', shop_records, None))

        display_rows.sort(key=lambda entry: entry[0])

        # Row 0 is a pinned, non-editable "+" shortcut row; the products follow
        # it, so every product sits one table-row below its own rank number.
        self.product_table.clearSpans()
        self.product_table.setRowCount(0)
        self.product_table.setRowCount(len(display_rows) + 1)
        self._set_add_row(0)

        # Fetch best prices from DB
        db = SessionLocal()

        for product_index, (priority, key, product, platform_value, shop_records, platform_raw_name) in enumerate(display_rows):
            row = product_index + 1  # offset by the pinned "+" row at index 0
            rank = product_index + 1

            rank_item = QTableWidgetItem(str(rank))
            rank_item.setData(Qt.ItemDataRole.UserRole, key)
            rank_item.setFlags(rank_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.product_table.setItem(row, 0, rank_item)
            self._set_rank_cell_widget(
                row, rank, key,
                is_first=(product_index == 0),
                is_last=(product_index == len(display_rows) - 1),
            )

            name_item = QTableWidgetItem(product.name)
            name_item.setData(Qt.ItemDataRole.UserRole, product.id)
            self.product_table.setItem(row, 1, name_item)
            self.product_table.setItem(row, 2, QTableWidgetItem(platform_value))
            self.product_table.setItem(row, 3, QTableWidgetItem(f"{product.target_price} €"))

            self._set_shops_cell(row, shop_records, all_shops)
            self._set_edit_cell_widget(row, product.id)
            self._set_delete_cell_widget(row, product.id, product.name, platform_raw_name)

            # Best price column — lowest price among shops that currently have
            # one. Unavailable shops are excluded so a stale price is never shown;
            # which shops are unavailable is surfaced per-shop in the Shops column.
            priced = db.query(ProductShop).filter(
                ProductShop.product_id == product.id,
                ProductShop.available.is_(True),
                ProductShop.last_price.isnot(None)
            ).all()

            if priced:
                best_price = min(s.last_price for s in priced)
                best_price_text = f"{best_price:.2f} €"
            else:
                best_price_text = "—"

            self.product_table.setItem(row, 5, QTableWidgetItem(best_price_text))

        db.close()
        # Narrow pinned "+" row; standard height for the product rows below it.
        self.product_table.setRowHeight(0, 24)
        ROW_HEIGHT = 36
        for row in range(1, self.product_table.rowCount()):
            self.product_table.setRowHeight(row, ROW_HEIGHT)

    # =========================================
    # DRAG-AND-DROP PRIORITY REORDERING
    # =========================================

    def on_row_dropped(self, source_row: int, target_row: int):
        """A row was dragged from source_row to target_row. Recompute the
        (product_id, platform_id) order and persist it, then fully rebuild
        the table from the database so items and cell widgets stay in sync."""
        keys = []
        for row in range(self.product_table.rowCount()):
            item = self.product_table.item(row, 0)
            keys.append(item.data(Qt.ItemDataRole.UserRole) if item is not None else None)

        if source_row < 0 or source_row >= len(keys):
            return

        moving_key = keys.pop(source_row)
        insert_at = target_row - 1 if target_row > source_row else target_row
        insert_at = max(0, min(insert_at, len(keys)))
        keys.insert(insert_at, moving_key)

        ordered_keys = [key for key in keys if key is not None and key[1] is not None]
        if ordered_keys:
            reorder_platform_priorities(ordered_keys)

        # We're still inside Qt's drag-and-drop event loop here (dropEvent
        # hasn't returned to startDrag() yet). Rebuilding the table now would
        # race with Qt's own internal drag cleanup, so defer it to the next
        # event loop iteration, once the drag has fully finished.
        QTimer.singleShot(0, self._finish_row_drop)

    def _finish_row_drop(self):
        self.load_products()
        self.product_table.clearSelection()
        self.product_table.setCurrentCell(-1, -1)

    # =========================================
    # UPDATE URLs BUTTON (main window)
    # =========================================

    def on_update_urls_clicked(self):
        """Resolve missing URLs for all products currently shown in the table."""
        product_ids = set()
        for row in range(self.product_table.rowCount()):
            item = self.product_table.item(row, 1)
            if item:
                pid = item.data(Qt.ItemDataRole.UserRole)
                if pid is not None:
                    product_ids.add(pid)

        if not product_ids:
            QMessageBox.information(self, "No products", "No products found in the table.")
            return

        confirm = QMessageBox.question(
            self,
            "Update URLs",
            f"Update missing URLs for {len(product_ids)} product(s)?\n"
            "Only shops without a URL will be updated.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.start_resolver_worker(list(product_ids))

    # =========================================
    # PRODUCT ADDED → AUTO RESOLVE URLS
    # =========================================

    def on_product_added(self, product_id: int):
        """Called after a product is saved. Refreshes table then resolves missing URLs."""
        self.load_products()
        self.start_resolver_worker([product_id])

    def start_resolver_worker(self, product_ids: list):
        self.status_label.setText(f"Resolving URLs for {len(product_ids)} product(s)...")

        worker = ResolverWorker(product_ids)
        worker.signals.started.connect(
            lambda: self.status_label.setText("URL resolver running...")
        )
        worker.signals.progress.connect(self.on_resolver_progress)
        worker.signals.finished.connect(self.on_resolver_finished)
        worker.signals.error.connect(self.on_resolver_error)
        self.thread_pool.start(worker)

    def on_resolver_progress(self, product_id: int, shop_name: str, url: str):
        """Called after each individual shop URL is resolved. Updates the Shops cell."""
        db = SessionLocal()
        shop_records = db.query(ProductShop).filter(
            ProductShop.product_id == product_id
        ).all()
        db.close()

        all_shops = get_available_shops()

        for row in range(self.product_table.rowCount()):
            item = self.product_table.item(row, 1)
            if item and item.data(Qt.ItemDataRole.UserRole) == product_id:
                self._set_shops_cell(row, shop_records, all_shops)

    def on_resolver_finished(self, results: dict):
        resolved = sum(
            1 for shops in results.values()
            for url in shops.values() if url
        )
        self.status_label.setText(f"URL resolver done — {resolved} URL(s) resolved.")
        self.load_products()

    def on_resolver_error(self, message: str):
        self.status_label.setText(f"Resolver error: {message}")

    # =========================================
    # RETRY QUEUE (background timer)
    # =========================================

    def check_retry_queue(self):
        worker = RetryWorker()
        worker.signals.progress.connect(self.on_resolver_progress)
        worker.signals.finished.connect(self.on_retry_finished)
        worker.signals.error.connect(self.on_resolver_error)
        self.thread_pool.start(worker)

    def on_retry_finished(self, resolved_count: int):
        if resolved_count > 0:
            self.status_label.setText(f"Retry resolver: {resolved_count} URL(s) resolved.")
            self.load_products()

    # =========================================
    # OPEN SETTINGS BOT DIALOG
    # =========================================

    def open_settings_bot_dialog(self):
        dialog = SettingsBotDialog(parent=self)
        dialog.exec()

    # =========================================
    # START BOT
    # =========================================

    def start_bot_worker(self):
        db = SessionLocal()
        setting = db.query(Setting).first()
        db.close()

        if setting is None:
            dialog = SettingsBotDialog(parent=self, auto_start=True)
            dialog.settings_saved.connect(self._launch_bot_worker)
            dialog.exec()
            return

        self._launch_bot_worker()

    def _launch_bot_worker(self):
        self.bot_running = True
        self.bot_worker_active = True
        self.bot_stop_event.clear()
        # A pass is starting — pause the between-passes countdown.
        self.countdown_timer.stop()
        self.start_bot_button.setEnabled(False)
        self.stop_bot_button.setEnabled(True)
        self.status_label.setText("Starting bot...")

        worker = BotWorker(self.bot_stop_event)
        worker.signals.started.connect(lambda: self.status_label.setText("Bot is running..."))
        worker.signals.finished.connect(self.on_bot_finished)
        worker.signals.error.connect(self.on_bot_error)

        self.thread_pool.start(worker)

    def _reschedule_or_stop(self, pass_status: str, stopped_status: str):
        """Shared post-pass logic for on_bot_finished/on_bot_error.

        If the user hasn't pressed Stop, schedule the next pass after the
        configured interval. Otherwise finalise the "stopped" state."""
        if self.bot_running and not self.bot_stop_event.is_set():
            interval = load_settings()["check_interval_minutes"]
            self.status_label.setText(f"{pass_status} Next check in {interval} min.")
            self.bot_schedule_timer.start(interval * 60_000)
            self.countdown_timer.start()
        else:
            self.bot_running = False
            self.countdown_timer.stop()
            self.status_label.setText(stopped_status)
            self.start_bot_button.setEnabled(True)
            self.stop_bot_button.setEnabled(False)

    def _update_countdown(self):
        """Refresh the status label with the time left until the next scheduled
        price check. Driven by the 1-minute countdown_timer; reads the live
        remaining time straight off bot_schedule_timer so it never drifts.
        remainingTime() returns -1 once the schedule timer has fired/stopped,
        so the >0 guard also covers the moment a pass is about to launch."""
        remaining = self.bot_schedule_timer.remainingTime()
        if remaining > 0:
            mins = (remaining + 59_999) // 60_000  # ceil to whole minutes
            self.status_label.setText(f"Next automatic check in {mins} min.")

    def on_bot_finished(self):
        self.bot_worker_active = False
        self.load_products()
        self._reschedule_or_stop("Bot finished.", "Bot stopped.")

    def on_bot_error(self, message):
        self.bot_worker_active = False
        self._reschedule_or_stop(f"Bot error: {message}", f"Bot error: {message}")

    def stop_bot_worker(self):
        self.bot_running = False
        self.bot_schedule_timer.stop()
        self.countdown_timer.stop()
        self.bot_stop_event.set()
        self.stop_bot_button.setEnabled(False)

        if self.bot_worker_active:
            self.status_label.setText("Stopping bot (finishing current check)...")
        else:
            self.status_label.setText("Bot stopped.")
            self.start_bot_button.setEnabled(True)

    def closeEvent(self, event):
        if self.bot_running:
            self.stop_bot_worker()
        self.retry_timer.stop()
        self.countdown_timer.stop()
        super().closeEvent(event)

# Establish execution mode (console/logs + headless resolution) before anything
# scrapes or prints. Must run before the browsers or Qt event loop start.
init_runtime_mode()

app = QApplication(sys.argv)

window = MainWindow()

window.show()

sys.exit(app.exec())