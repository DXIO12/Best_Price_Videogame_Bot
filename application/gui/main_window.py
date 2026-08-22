import sys
import threading
from application.config.runtime_config import init_runtime_mode
from application.bot.bot import load_settings
from application.gui.add_product_dialog import AddProductDialog, get_available_shops
from application.gui.delete_product_dialog import DeleteProductDialog
from application.gui.modify_product_dialog import ModifyProductDialog
from application.gui.settings_bot import SettingsBotDialog
from application.language_selector import init_language, tr
from application.services.product_service import (
    get_products_with_shops,
    to_gui_names,
    get_platform_priorities,
    reorder_platform_priorities,
    delete_product_platforms,
    delete_products,
)
from PyQt6 import sip
from PyQt6.QtCore import QThreadPool, Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui import QCursor
from application.database.db import SessionLocal
from application.database.models import ProductShop, Setting
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
    QSizePolicy,
    QToolButton,
    QToolTip
)

from application.gui import icons
from application.gui.bot_worker import BotWorker
from application.services.resolver_worker import ResolverWorker, RetryWorker
from application.services.resolve_urls_service import MAX_RETRIES
from application.services.url_resolvers.resolution import ResolutionStatus


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

        self.setWindowTitle(tr("main.window_title"))

        self.resize(1200, 700)
        self._center_on_screen()

        self.thread_pool = QThreadPool()

        # Recurring bot state
        self.bot_running = False
        self.bot_worker_active = False
        self.bot_stop_event = threading.Event()
        # Set means "paused": a running pass parks at its next product/shop
        # checkpoint and stays there until this is cleared again.
        self.bot_pause_event = threading.Event()
        self.bot_paused = False
        # Countdown frozen when Pause was pressed between passes, so Continue
        # resumes the time that was actually left instead of a whole interval.
        self.paused_remaining_ms = 0
        # Restart was pressed while a pass was still winding down — the relaunch
        # waits for that pass's finished/error signal (see _reschedule_or_stop),
        # because two BotWorkers must never scrape at the same time.
        self.bot_restart_pending = False
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

        # Re-issues the unavailable-store tooltip on an interval so it stays
        # visible for as long as the cursor rests on the ⚠ marker, instead of
        # vanishing after QToolTip's own short default display duration.
        # Set up before setup_ui/load_products, which already clear it.
        self._shop_tooltip_target = None
        self._shop_tooltip_timer = QTimer(self)
        self._shop_tooltip_timer.timeout.connect(self._refresh_shop_tooltip)

        # The resolve-URLs icon lives in a table cell that load_products()
        # rebuilds wholesale, so its enabled state cannot live on the widget
        # alone: it is kept here and re-applied by _set_add_row on every
        # rebuild. Both must exist before setup_ui/load_products run.
        self._resolver_busy = False
        self.update_urls_button = None

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

        # TITLE + SETTINGS GEAR
        # Kept on self so _retranslate_ui can relabel it after a language change.
        self.title_label = QLabel(tr("main.heading"))

        # The gear groups every kind of customisation (bot behaviour and app
        # behaviour), so it sits apart from the action buttons: top-right
        # corner, flush with the window edge — directly above "Delete Product".
        self.settings_bot_button = QToolButton()
        self.settings_bot_button.setIcon(icons.settings_icon())
        self.settings_bot_button.setIconSize(QSize(22, 22))
        self.settings_bot_button.setAutoRaise(True)
        self.settings_bot_button.setToolTip(tr("main.tooltip_settings"))
        self.settings_bot_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        title_layout = QHBoxLayout()
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        title_layout.addWidget(self.settings_bot_button)

        main_layout.addLayout(title_layout)

        # BUTTON LAYOUT
        button_layout = QHBoxLayout()

        self.add_product_button = QPushButton(
            tr("main.btn_add_product")
        )

        self.delete_product_button = QPushButton(
            tr("main.btn_delete_product")
        )

        self.modify_product_button = QPushButton(
            tr("main.btn_modify_product")
        )

        # Bot transport row: Start · Pause · Stop. The first two swap their icon
        # and label depending on state (see _update_bot_buttons), which also sets
        # every label and enabled flag below — hence no text passed here.
        self.start_bot_button = QPushButton()
        self.start_bot_button.setMinimumWidth(180)
        self.start_bot_button.setIconSize(QSize(16, 16))

        self.pause_bot_button = QPushButton()
        self.pause_bot_button.setMinimumWidth(180)
        self.pause_bot_button.setIconSize(QSize(16, 16))

        self.stop_bot_button = QPushButton()
        self.stop_bot_button.setMinimumWidth(180)
        self.stop_bot_button.setIconSize(QSize(16, 16))
        self.stop_bot_button.setIcon(icons.stop_icon())

        self._update_bot_buttons()

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
        self.settings_bot_button.clicked.connect(self.open_settings_bot_dialog)
        self.start_bot_button.clicked.connect(self.start_bot_worker)
        self.pause_bot_button.clicked.connect(self.pause_bot_worker)
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

        self._retranslate_table_headers()

        self.product_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.product_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)

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

        # START · PAUSE · STOP BOT (centered)
        # Update URLs used to sit in a row of its own here; it now lives as an
        # icon in the pinned first table row, over the Shops column it acts on.
        start_button_layout = QHBoxLayout()
        start_button_layout.addStretch()
        start_button_layout.addWidget(self.start_bot_button)
        start_button_layout.addWidget(self.pause_bot_button)
        start_button_layout.addWidget(self.stop_bot_button)
        start_button_layout.addStretch()
        main_layout.addLayout(start_button_layout)

        self.status_label = QLabel()
        self._set_status("main.status_ready")
        main_layout.addWidget(self.status_label)

        self.setLayout(main_layout)

    # =========================================
    # TRANSLATION
    # =========================================

    def _retranslate_table_headers(self):
        """(Re)label the product table's header row and its per-column tooltips.

        Split out of setup_ui because _retranslate_ui needs the same work after
        a language change — setHorizontalHeaderLabels replaces the header items,
        so the tooltips have to be re-applied right after it, every time."""
        self.product_table.setHorizontalHeaderLabels([
            tr("main.header_priority"),
            tr("main.header_product"),
            tr("main.header_platform"),
            tr("main.header_target_price"),
            tr("main.header_shops"),
            tr("main.header_best_price"),
            "",
            ""
        ])
        self.product_table.horizontalHeaderItem(0).setToolTip(tr("main.tooltip_header_priority"))
        self.product_table.horizontalHeaderItem(4).setToolTip(tr("main.tooltip_header_shops"))
        self.product_table.horizontalHeaderItem(6).setToolTip(tr("main.tooltip_edit_product"))
        self.product_table.horizontalHeaderItem(7).setToolTip(tr("main.tooltip_delete_product"))

    def _set_status(self, key: str, **kwargs):
        """Show a status message, remembering which key produced it.

        Storing the key (rather than only the rendered text) is what lets
        _retranslate_ui redraw the *current* status in the new language instead
        of leaving it stranded in the old one."""
        self._status_key = key
        self._status_kwargs = kwargs
        self.status_label.setText(tr(key, **kwargs))

    def _retranslate_ui(self):
        """Re-apply every string in this window after a language change.

        Only MainWindow needs this: the dialogs are constructed fresh each time
        they are opened, so they pick up the new language on their own."""
        self.setWindowTitle(tr("main.window_title"))
        self.title_label.setText(tr("main.heading"))
        self.settings_bot_button.setToolTip(tr("main.tooltip_settings"))

        self.add_product_button.setText(tr("main.btn_add_product"))
        self.modify_product_button.setText(tr("main.btn_modify_product"))
        self.delete_product_button.setText(tr("main.btn_delete_product"))
        # Relabels whichever variant the three bot buttons are currently showing
        # (Start vs Restart, Pause vs Continue).
        self._update_bot_buttons()

        self._retranslate_table_headers()
        # Rebuilds every cell and cell widget, which is where the "＋", resolve
        # URLs, edit and delete tooltips (and the Shops column text) come from.
        self.load_products()
        self._set_status(self._status_key, **self._status_kwargs)

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
    #
    # The marker names double as catalog keys under "main.shop_marker". Their
    # text is looked up at hover time rather than stored in a class-level dict:
    # such a dict is built once at import, so it would keep serving the language
    # that was active at startup even after the user switches.
    SHOP_MARKERS = ("no_url", "retry_scheduled", "retry_exhausted", "unavailable")
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
            return tr("common.all")

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
        return ", ".join(parts) if parts else tr("common.none")

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
        """Pinned, non-editable first row carrying the two table-wide actions:
        a '+' button spanning the edit + delete columns, which opens the Add
        Product dialog, and a sync icon over the Shops column, which resolves
        the shop URLs that are still missing. Kept as a real table row (not a
        bar above the table) so each action lines up with the column it acts
        on."""
        # Blank, non-interactive cells for the data columns (0-5): enabled but
        # not selectable/editable/draggable, so this row can't be picked up by
        # the drag-and-drop reorder and never opens the modify dialog. The
        # Shops cell keeps its blank item too — the button below is a cell
        # *widget*, drawn on top, and the item is what keeps the cell inert.
        for col in range(6):
            blank = QTableWidgetItem("")
            blank.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.product_table.setItem(row, col, blank)

        # Resolve URLs, centered over the Shops column (4). Recreated on every
        # load_products() rather than reparented: reparenting a widget whose
        # container setCellWidget is about to destroy is fragile, and rebuilding
        # per row is what every other cell widget in this table already does.
        # Hence _resolver_busy, which outlives the widget, decides `enabled`.
        shops_container = QWidget()
        shops_layout = QHBoxLayout(shops_container)
        shops_layout.setContentsMargins(0, 0, 0, 0)
        shops_layout.addStretch()

        self.update_urls_button = QToolButton()
        self.update_urls_button.setIcon(icons.sync_icon())
        self.update_urls_button.setIconSize(QSize(18, 18))
        # Wider than tall on purpose: the Shops column is the widest in the
        # table, so a square hit area looks lost in it, and the row is capped at
        # 24 px (see load_products) — the height cannot grow to match. The
        # explicit size also stops autoRaise's hover frame from hugging the
        # glyph so tightly that it reads as a rendering artefact. The width
        # matches the '+' below, so the table's two row-wide actions carry the
        # same visual weight.
        self.update_urls_button.setFixedSize(72, 22)
        self.update_urls_button.setAutoRaise(True)
        self.update_urls_button.setToolTip(tr("main.tooltip_update_urls"))
        self.update_urls_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.update_urls_button.setEnabled(not self._resolver_busy)
        self.update_urls_button.clicked.connect(self.on_update_urls_clicked)

        shops_layout.addWidget(self.update_urls_button)
        shops_layout.addStretch()
        self.product_table.setCellWidget(row, 4, shops_container)

        # A single '+' button spanning the edit (6) and delete (7) columns.
        self.product_table.setSpan(row, 6, 1, 2)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        add_button = QToolButton()
        add_button.setText("＋")
        add_button.setAutoRaise(True)
        add_button.setToolTip(tr("main.tooltip_add_product"))
        add_button.setStyleSheet("QToolButton { font-size: 18px; font-weight: bold; }")
        # Stretched across the full width of the spanned cell, so the hit area
        # matches the two columns the span already covers. Expanding rather than
        # a fixed width because columns 6 and 7 are ResizeToContents: their width
        # follows the pencil and bin glyphs and is not known here. Height is
        # capped like the sync button — the row is 24 px (see load_products).
        add_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        add_button.setFixedHeight(22)
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
        edit_button.setIcon(icons.edit_icon())
        edit_button.setIconSize(QSize(16, 16))
        edit_button.setAutoRaise(True)
        edit_button.setToolTip(tr("main.tooltip_edit_product"))
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
        delete_button.setToolTip(tr("main.tooltip_delete_product"))
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
            tr("main.confirm_delete_title"),
            tr("main.confirm_delete_body", label=label),
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
        text = tr(f"main.shop_marker.{url}") if url in self.SHOP_MARKERS else None
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
            QMessageBox.information(
                self,
                tr("main.no_products_title"),
                tr("main.no_products_body"),
            )
            return

        confirm = QMessageBox.question(
            self,
            tr("main.update_urls_title"),
            tr("main.update_urls_body", count=len(product_ids)),
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

    def _set_resolver_busy(self, busy: bool):
        """Lock the resolve-URLs icon while a pass is in flight, so a second
        pass can't be launched over the first. The flag outlives the button,
        which load_products() destroys and recreates (see _set_add_row)."""
        self._resolver_busy = busy
        if self.update_urls_button is not None:
            self.update_urls_button.setEnabled(not busy)

    def start_resolver_worker(self, product_ids: list):
        self._set_resolver_busy(True)
        self._set_status("main.status_resolving", count=len(product_ids))

        worker = ResolverWorker(product_ids)
        worker.signals.started.connect(
            lambda: self._set_status("main.status_resolver_running")
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

    @staticmethod
    def _shops_with_status(results: dict, status: ResolutionStatus) -> str:
        """Comma-joined names of the shops that came back with one status.

        Deduplicated across products: resolving three games at once must not
        print "Pccomponentes, Pccomponentes, Pccomponentes".
        """
        names: list[str] = []
        for shops in results.values():
            for shop, outcome in shops.items():
                if outcome.status is status and shop not in names:
                    names.append(shop)
        return ", ".join(names)

    def on_resolver_finished(self, results: dict):
        """Report the pass, naming the shops that gave a definitive "no".

        Those rows show no URL and no pending retry, which on its own looks
        identical to a lookup that simply broke — so the reason is spelled out
        here. Every placeholder is a count or a shop name, both untranslated, so
        _retranslate_ui can redraw this line in a new language from the stored
        key and kwargs alone."""
        # Cleared before the load_products() below, so the row is rebuilt with
        # the icon already enabled. ResolverWorker.run emits finished *or*
        # error, never both, so this and on_resolver_error cover every exit.
        self._set_resolver_busy(False)

        resolved = sum(
            1 for shops in results.values()
            for outcome in shops.values() if outcome.url
        )
        not_found = self._shops_with_status(results, ResolutionStatus.NOT_FOUND)
        only_used = self._shops_with_status(results, ResolutionStatus.ONLY_USED)

        if not_found and only_used:
            self._set_status(
                "main.status_resolver_done_both",
                count=resolved, not_found=not_found, only_used=only_used,
            )
        elif not_found:
            self._set_status(
                "main.status_resolver_done_not_found",
                count=resolved, not_found=not_found,
            )
        elif only_used:
            self._set_status(
                "main.status_resolver_done_only_used",
                count=resolved, only_used=only_used,
            )
        else:
            self._set_status("main.status_resolver_done", count=resolved)

        self.load_products()

    def on_resolver_error(self, message: str):
        self._set_resolver_busy(False)
        self._set_status("main.status_resolver_error", message=message)

    # =========================================
    # RETRY QUEUE (background timer)
    # =========================================

    def check_retry_queue(self):
        worker = RetryWorker()
        worker.signals.progress.connect(self.on_resolver_progress)
        worker.signals.finished.connect(self.on_retry_finished)
        worker.signals.error.connect(self.on_retry_error)
        self.thread_pool.start(worker)

    def on_retry_error(self, message: str):
        """Same message as a foreground resolver failure, but it must not touch
        _resolver_busy: this pass runs on its own 5-minute timer, and letting it
        unlock the icon could re-enable it while a foreground pass is still in
        flight — which is exactly what the lock is there to prevent."""
        self._set_status("main.status_resolver_error", message=message)

    def on_retry_finished(self, resolved_count: int):
        if resolved_count > 0:
            self._set_status("main.status_retry_done", count=resolved_count)
            self.load_products()

    # =========================================
    # OPEN SETTINGS BOT DIALOG
    # =========================================

    def open_settings_bot_dialog(self):
        dialog = SettingsBotDialog(parent=self)
        # Saving may have changed the language: relabel this window in place.
        # The dialogs need no such hook — each is rebuilt on its next open.
        dialog.settings_saved.connect(self._retranslate_ui)
        dialog.exec()

    # =========================================
    # START / PAUSE / STOP BOT
    # =========================================

    def _update_bot_buttons(self):
        """Point the three transport buttons at the current state.

        Single source of truth for their icon, label and enabled flag, so no
        handler has to remember the full combination — and so a language change
        can relabel them by calling this alone.

        Paused is the only state where the left button does something: it turns
        into "Restart", the escape hatch from a pass parked half-way through."""
        if self.bot_paused:
            self.start_bot_button.setIcon(icons.restart_icon())
            self.start_bot_button.setText(tr("main.btn_restart_bot"))
            self.pause_bot_button.setIcon(icons.play_icon())
            self.pause_bot_button.setText(tr("main.btn_continue_bot"))
        else:
            self.start_bot_button.setIcon(icons.play_icon())
            self.start_bot_button.setText(tr("main.btn_start_bot"))
            self.pause_bot_button.setIcon(icons.pause_icon())
            self.pause_bot_button.setText(tr("main.btn_pause_bot"))

        self.stop_bot_button.setText(tr("main.btn_stop_bot"))

        # Start stays disabled while a stopped-but-still-winding-down pass runs
        # out; re-enabling it there would let a second BotWorker start on top of
        # the first. Pause is meaningless once a restart is already queued.
        self.start_bot_button.setEnabled(
            self.bot_paused or (not self.bot_running and not self.bot_worker_active)
        )
        self.pause_bot_button.setEnabled(self.bot_running and not self.bot_restart_pending)
        self.stop_bot_button.setEnabled(self.bot_running)

    def start_bot_worker(self):
        # While paused this button reads "Restart", which is a different action.
        if self.bot_paused:
            self.restart_bot_worker()
            return

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
        self.bot_pause_event.clear()
        self.bot_paused = False
        self.paused_remaining_ms = 0
        # A pass is starting — pause the between-passes countdown.
        self.countdown_timer.stop()
        self._update_bot_buttons()
        self._set_status("main.status_starting_bot")

        worker = BotWorker(self.bot_stop_event, self.bot_pause_event)
        worker.signals.started.connect(lambda: self._set_status("main.status_bot_running"))
        worker.signals.finished.connect(self.on_bot_finished)
        worker.signals.error.connect(self.on_bot_error)

        self.thread_pool.start(worker)

    def _reschedule_or_stop(self, next_key: str, stopped_key: str, **kwargs):
        """Shared post-pass logic for on_bot_finished/on_bot_error.

        If the user hasn't pressed Stop, schedule the next pass after the
        configured interval. Otherwise finalise the "stopped" state.

        Takes catalog keys rather than ready-made text so the status can be
        re-rendered later in a different language; ``kwargs`` carries anything
        the message needs that isn't translatable (an error string, say)."""
        # Restart was pressed while this pass was still winding down. Only now,
        # with the old worker gone for good, is it safe to launch the new one.
        if self.bot_restart_pending:
            self.bot_restart_pending = False
            self.bot_stop_event.clear()
            self._launch_bot_worker()
            return

        if self.bot_running and not self.bot_stop_event.is_set():
            interval = load_settings()["check_interval_minutes"]
            # Pause landed on the pass's last leg, so it ran to the end anyway.
            # Hold the whole interval rather than scheduling it: Continue is
            # what should start that clock.
            if self.bot_paused:
                self.paused_remaining_ms = interval * 60_000
                self._set_status("main.status_bot_paused")
                self._update_bot_buttons()
                return
            self._set_status(next_key, interval=interval, **kwargs)
            self.bot_schedule_timer.start(interval * 60_000)
            self.countdown_timer.start()
        else:
            self.bot_running = False
            self.bot_paused = False
            self.countdown_timer.stop()
            self._set_status(stopped_key, **kwargs)
            self._update_bot_buttons()

    def _update_countdown(self):
        """Refresh the status label with the time left until the next scheduled
        price check. Driven by the 1-minute countdown_timer; reads the live
        remaining time straight off bot_schedule_timer so it never drifts.
        remainingTime() returns -1 once the schedule timer has fired/stopped,
        so the >0 guard also covers the moment a pass is about to launch."""
        remaining = self.bot_schedule_timer.remainingTime()
        if remaining > 0:
            mins = (remaining + 59_999) // 60_000  # ceil to whole minutes
            self._set_status("main.status_next_automatic", minutes=mins)

    def on_bot_finished(self):
        self.bot_worker_active = False
        self.load_products()
        self._reschedule_or_stop(
            "main.status_bot_finished_next", "main.status_bot_stopped"
        )

    def on_bot_error(self, message):
        self.bot_worker_active = False
        self._reschedule_or_stop(
            "main.status_bot_error_next", "main.status_bot_error", message=message
        )

    def pause_bot_worker(self):
        """Middle button: Pause, or Continue when already paused."""
        if self.bot_paused:
            self.resume_bot_worker()
            return

        self.bot_paused = True
        self.bot_pause_event.set()

        if self.bot_schedule_timer.isActive():
            # Waiting between passes: freeze what is left of the countdown so
            # Continue picks up from there instead of restarting the interval.
            self.paused_remaining_ms = self.bot_schedule_timer.remainingTime()
            self.bot_schedule_timer.stop()
            self.countdown_timer.stop()
            minutes = (self.paused_remaining_ms + 59_999) // 60_000
            self._set_status("main.status_bot_paused_remaining", minutes=minutes)
        else:
            # A pass is scraping. It parks at its next product/shop checkpoint
            # and does not report back, so the message promises exactly that
            # rather than claiming it has already stopped.
            self._set_status("main.status_pausing_bot")

        self._update_bot_buttons()

    def resume_bot_worker(self):
        """Continue: release a parked pass, or restart the frozen countdown."""
        self.bot_paused = False
        self.bot_pause_event.clear()

        if self.bot_worker_active:
            # The worker thread unblocks itself at the checkpoint it parked on.
            self._set_status("main.status_bot_running")
        elif self.paused_remaining_ms > 0:
            self.bot_schedule_timer.start(self.paused_remaining_ms)
            self.countdown_timer.start()
            minutes = (self.paused_remaining_ms + 59_999) // 60_000
            self.paused_remaining_ms = 0
            self._set_status("main.status_next_automatic", minutes=minutes)
        else:
            # Nothing was pending (paused before anything got scheduled) — the
            # only sensible resume is to run a pass now.
            self._launch_bot_worker()

        self._update_bot_buttons()

    def restart_bot_worker(self):
        """Left button while paused: drop the paused pass and start a fresh one."""
        self.bot_paused = False
        self.bot_pause_event.clear()
        self.paused_remaining_ms = 0
        self.bot_schedule_timer.stop()
        self.countdown_timer.stop()

        if self.bot_worker_active:
            # A parked pass is still alive. Ask it to abandon and let
            # _reschedule_or_stop launch the replacement once it is really gone:
            # two BotWorkers scraping at once would fight over Playwright.
            self.bot_restart_pending = True
            self.bot_stop_event.set()
            self._update_bot_buttons()
            self._set_status("main.status_restarting_bot")
        else:
            self._launch_bot_worker()

    def stop_bot_worker(self):
        self.bot_running = False
        self.bot_paused = False
        self.bot_restart_pending = False
        self.paused_remaining_ms = 0
        self.bot_schedule_timer.stop()
        self.countdown_timer.stop()
        self.bot_stop_event.set()
        # Load-bearing: a pass parked on the pause event never returns, so it
        # would never emit finished — leaving Start disabled forever and hanging
        # the app on exit. Cleared after the stop flag so it wakes up to that.
        self.bot_pause_event.clear()
        self._update_bot_buttons()

        if self.bot_worker_active:
            self._set_status("main.status_stopping_bot")
        else:
            self._set_status("main.status_bot_stopped")

    def closeEvent(self, event):
        # bot_worker_active is checked too: a pass parked on the pause event must
        # be released here or the thread pool never drains and the app hangs.
        if self.bot_running or self.bot_worker_active:
            self.stop_bot_worker()
        self.retry_timer.stop()
        self.countdown_timer.stop()
        super().closeEvent(event)

# Establish execution mode (console/logs + headless resolution) before anything
# scrapes or prints. Must run before the browsers or Qt event loop start.
init_runtime_mode()

# Resolve the UI language before any widget is built — every tr() below reads it.
init_language()

app = QApplication(sys.argv)

window = MainWindow()

window.show()

sys.exit(app.exec())