from services.product_service import (
    modify_product,
    apply_shop_changes,
    get_products,
    to_gui_names,
    get_platform_priorities,
)
from gui.add_product_dialog import MultiSelectDropdown, get_available_shops
from database.db import SessionLocal
from database.models import ProductShop
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QCheckBox,
    QSizePolicy,
    QWidget,
    QAbstractItemView,
    QLineEdit,
    QHeaderView,
)


def _shop_button_text(records) -> str:
    """Label for the Shops column button: every shop with ✓ (has URL) or ✖ (no URL)."""
    if not records:
        return "No shops"
    return "  ".join(f"{r.shop} {'✓' if r.url else '✖'}" for r in records)


class ModifyProductDialog(QDialog):

    product_modified = pyqtSignal()

    def __init__(self, preselect_product_id: int | None = None):
        super().__init__()

        self.setWindowTitle("Modify Product")

        self.resize(950, 520)

        self._preselect_product_id = preselect_product_id
        self._loading = False
        self.setup_ui()
        self.load_products()
        self._preselect_product()

    def setup_ui(self):

        layout = QVBoxLayout()

        title = QLabel("Select products to modify (click checkbox column to select, double-click cells to edit)")
        layout.addWidget(title)

        self.product_table = QTableWidget()
        self.product_table.setColumnCount(5)
        self.product_table.setHorizontalHeaderLabels([
            "Modify",
            "Product",
            "Platform",
            "Shops",
            "Target Price"
        ])
        # Enable editing on double-click for text cells (not widget columns)
        self.product_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
        )
        self.product_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.product_table.setColumnWidth(0, 70)
        self.product_table.setColumnWidth(1, 200)
        self.product_table.setColumnWidth(2, 120)
        self.product_table.setColumnWidth(4, 120)
        self.product_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )

        self.product_table.itemChanged.connect(self._on_item_changed)

        layout.addWidget(self.product_table)

        button_layout = QHBoxLayout()

        self.modify_button = QPushButton("Apply Changes")
        self.cancel_button = QPushButton("Cancel")

        button_layout.addWidget(self.modify_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.modify_button.clicked.connect(self.on_apply_changes)
        self.cancel_button.clicked.connect(self.close)

        self.setLayout(layout)

    def load_products(self):
        products = get_products()

        # Pre-load all ProductShop records to avoid N+1 queries
        db = SessionLocal()
        all_shop_recs = db.query(ProductShop).all()
        db.close()
        shops_by_pid: dict[int, list] = {}
        for r in all_shop_recs:
            shops_by_pid.setdefault(r.product_id, []).append(r)

        # Platform options for the dropdown
        platform_options = [
            "PS5",
            "NS2",
            "NS",
            "PC",
            "Xbox Series X"
        ]

        # Build rows per platform (one row per platform), kept in the same
        # priority order the main window shows so both tables line up.
        self.product_rows = []
        display_rows = []
        priorities = get_platform_priorities()

        for product in products:
            if product.platforms:
                plats = to_gui_names([p.name for p in product.platforms])
            else:
                plats = ['']

            self.product_rows.append({
                'product_id': product.id,
                'original_name': product.name,
                'original_platforms': plats,
                'original_price': product.target_price
            })

            if product.platforms:
                for platform, plat in zip(product.platforms, plats):
                    priority = priorities.get((product.id, platform.id), 0)
                    display_rows.append((priority, product.id, product.name, plat, product.target_price))
            else:
                # No platform assigned: no product_platforms row to read a
                # priority from, so it sorts first like in the main window.
                display_rows.append((0, product.id, product.name, '', product.target_price))

        display_rows.sort(key=lambda entry: entry[0])
        display_rows = [entry[1:] for entry in display_rows]

        self._loading = True
        self.product_table.setRowCount(0)
        self.product_table.setRowCount(len(display_rows))
        self.platform_widgets = {}

        for row, (pid, name, plat, price) in enumerate(display_rows):
            # Col 0 — Checkbox
            checkbox = QCheckBox()
            checkbox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            checkbox.setStyleSheet("QCheckBox { margin: 0px; padding: 0px; }")
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.addStretch()
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.addStretch()
            checkbox_widget.setLayout(checkbox_layout)
            checkbox.setProperty("row", row)
            checkbox.setProperty("product_id", pid)
            checkbox.setProperty("platform", plat)
            self.product_table.setCellWidget(row, 0, checkbox_widget)

            # Col 1 — Product name (editable)
            name_item = QTableWidgetItem(name)
            self.product_table.setItem(row, 1, name_item)

            # Col 2 — Platform (MultiSelectDropdown)
            platform_dropdown = MultiSelectDropdown(
                platform_options,
                selected=[plat] if plat else [],
                include_all_option=False
            )
            self.product_table.setCellWidget(row, 2, platform_dropdown)
            self.platform_widgets[row] = platform_dropdown
            platform_dropdown.shops_changed.connect(lambda _sel, r=row: self._auto_check_row(r))

            # Col 3 — Shops button
            shop_btn = QPushButton(_shop_button_text(shops_by_pid.get(pid, [])))
            shop_btn.setToolTip("Click to manage shops and URLs for this product")
            shop_btn.clicked.connect(
                lambda checked, p=pid, n=name: self.open_shop_manager(p, n)
            )
            self.product_table.setCellWidget(row, 3, shop_btn)

            # Col 4 — Target Price (editable)
            price_item = QTableWidgetItem(f"{price} €")
            self.product_table.setItem(row, 4, price_item)

        self._loading = False

    def _preselect_product(self):
        """Tick the Modify checkbox for the product the user double-clicked in
        the main window (all of its platform rows). No-op when the dialog is
        opened from the button, where no product is preselected."""
        if self._preselect_product_id is None:
            return
        for row in range(self.product_table.rowCount()):
            widget = self.product_table.cellWidget(row, 0)
            checkbox = widget.findChild(QCheckBox) if widget else None
            if checkbox and checkbox.property("product_id") == self._preselect_product_id:
                checkbox.setChecked(True)

    def _on_item_changed(self, item):
        """Auto-check a row's 'Modify' box when its name or price cell is edited."""
        if item.column() in (1, 4):
            self._auto_check_row(item.row())

    def _auto_check_row(self, row):
        """Mark a row's 'Modify' checkbox as checked, ignored while the table is loading."""
        if self._loading:
            return
        checkbox_widget = self.product_table.cellWidget(row, 0)
        checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget else None
        if checkbox is not None:
            checkbox.setChecked(True)

    def on_apply_changes(self):
        """Collect selected products with edited values and apply changes."""
        selected_changes = {}  # {product_id: {name, platforms, price}}

        for row in range(self.product_table.rowCount()):
            checkbox_widget = self.product_table.cellWidget(row, 0)
            checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget is not None else None
            if checkbox is not None and checkbox.isChecked():
                product_id = checkbox.property("product_id")

                # Get edited values from table cells
                name_item = self.product_table.item(row, 1)
                platform_widget = self.platform_widgets.get(row)
                price_item = self.product_table.item(row, 4)

                try:
                    edited_name = name_item.text() if name_item else ""

                    # Get selected platforms from the MultiSelectDropdown widget
                    if platform_widget:
                        edited_platforms = platform_widget.get_selected()
                    else:
                        edited_platforms = []

                    # Extract price number from "X.XX €" format
                    price_text = price_item.text() if price_item else "0"
                    price_text = price_text.replace(" €", "").strip()
                    edited_price = float(price_text) if price_text else 0.0
                except (ValueError, AttributeError):
                    QMessageBox.warning(
                        self,
                        "Invalid input",
                        f"Row {row + 1}: Invalid price value. Please enter a valid number."
                    )
                    return

                # Store changes grouped by product_id
                if product_id not in selected_changes:
                    selected_changes[product_id] = {
                        'name': edited_name,
                        'platforms': edited_platforms,
                        'price': edited_price
                    }
                else:
                    # If same product appears in multiple rows, merge the platforms
                    existing = selected_changes[product_id]
                    existing_plats = set(existing['platforms'])
                    new_plats = set(edited_platforms)
                    combined = list(existing_plats | new_plats)
                    existing['platforms'] = combined

        if not selected_changes:
            QMessageBox.warning(
                self,
                "No products selected",
                "Please select at least one product to modify."
            )
            return

        # Build confirmation text. Shop edits are already saved by the Manage
        # Shops dialog, so they never show up here.
        changes_text = "The following product changes will be applied:\n\n"
        for pid, changes in selected_changes.items():
            platforms_str = ', '.join(changes['platforms']) if changes['platforms'] else "None"
            changes_text += f"Product: {changes['name']}\n"
            changes_text += f"Platforms: {platforms_str}\n"
            changes_text += f"Price: {changes['price']} €\n\n"

        confirm = QMessageBox.question(
            self,
            "Confirm Changes",
            changes_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.Yes:
            print(f"===================================")
            for product_id, changes in selected_changes.items():
                modify_product(
                    product_id,
                    changes['platforms'],
                    new_name=changes['name'],
                    new_target_price=changes['price']
                )

                original = next(
                    (r for r in self.product_rows if r['product_id'] == product_id), None
                )
                if original:
                    diffs = []
                    if changes['name'] != original['original_name']:
                        diffs.append(f"name: '{original['original_name']}' → '{changes['name']}'")
                    if set(changes['platforms']) != set(original['original_platforms']):
                        diffs.append(
                            f"platforms: {original['original_platforms']} → {changes['platforms']}"
                        )
                    if changes['price'] != original['original_price']:
                        diffs.append(
                            f"price: {original['original_price']}€ → {changes['price']}€"
                        )
                    if diffs:
                        print(f"[Modify] '{changes['name']}' — {', '.join(diffs)}")
                    else:
                        print(f"[Modify] '{changes['name']}' — no changes detected")

            self.load_products()
            QMessageBox.information(self, "Success", "Products updated successfully.")
            self.product_modified.emit()
            self.close()

    # =========================================
    # OPEN SHOP MANAGER DIALOG
    # =========================================

    def open_shop_manager(self, product_id: int, product_name: str):
        dialog = ShopManagerDialog(product_id, product_name, parent=self)
        dialog.exec()
        if dialog.changes_applied:
            # Already written to the DB by the dialog: just resync what is shown
            # here and in the main window. The row's 'Modify' checkbox is left
            # alone — there is nothing left for Apply Changes to do.
            self._refresh_shop_button(product_id)
            self.product_modified.emit()

    def _refresh_shop_button(self, product_id: int):
        """Re-read one product's shops and relabel its Shops button.

        Only that button is touched: reloading the whole table would throw away
        the name/platform/price edits the user has not applied yet."""
        db = SessionLocal()
        records = db.query(ProductShop).filter(
            ProductShop.product_id == product_id
        ).all()
        db.close()

        text = _shop_button_text(records)

        for row in range(self.product_table.rowCount()):
            checkbox_widget = self.product_table.cellWidget(row, 0)
            checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget else None
            if checkbox and checkbox.property("product_id") == product_id:
                btn = self.product_table.cellWidget(row, 3)
                if isinstance(btn, QPushButton):
                    btn.setText(text)


# =============================================================
# SHOP MANAGER DIALOG
# =============================================================

class ShopManagerDialog(QDialog):
    """
    Dialog to manage shops and URLs for a single product.
    - Checkbox per shop: check to include, uncheck to remove.
    - URL field: editable — manual URL takes priority over the auto-resolver.
    - Confirm summarises every change and, once accepted, saves it straight to
      the DB, so Apply Changes never asks about shops again.
    """

    def __init__(self, product_id: int, product_name: str, parent=None):
        super().__init__(parent)
        self.product_id = product_id
        self.setWindowTitle(f"Manage Shops — {product_name}")
        self.resize(660, 400)
        self.changes_applied = False
        self._load_data()
        self._setup_ui()

    # ---------------------------------------------------------
    # Data loading
    # ---------------------------------------------------------

    def _load_data(self):
        db = SessionLocal()
        records = db.query(ProductShop).filter(
            ProductShop.product_id == self.product_id
        ).all()
        db.close()

        self._db_records = {r.shop.strip().lower(): r for r in records}

        available = get_available_shops()           # capitalized names
        known_keys = {s.lower() for s in available}

        # Include shops already in DB that aren't in the available list
        extra = [
            r.shop for r in records
            if r.shop.strip().lower() not in known_keys
        ]
        self._all_shops = available + extra

    # ---------------------------------------------------------
    # UI
    # ---------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout()

        layout.addWidget(QLabel(
            "Check a shop to include it · Uncheck to remove it\n"
            "Edit the URL field to set a manual URL (overrides the auto-resolver)"
        ))

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Include", "Shop", "URL"])
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.setColumnWidth(0, 70)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setRowCount(len(self._all_shops))

        self._row_data = []

        for row, shop_display in enumerate(self._all_shops):
            key = shop_display.strip().lower()
            record = self._db_records.get(key)

            original_enabled = record is not None
            original_url = (record.url or "") if record else ""

            # Col 0 — Include checkbox (centred)
            checkbox = QCheckBox()
            checkbox.setChecked(original_enabled)
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb_layout.addStretch()
            cb_layout.addWidget(checkbox)
            cb_layout.addStretch()
            self.table.setCellWidget(row, 0, cb_widget)

            # Col 1 — Shop name (read-only)
            shop_item = QTableWidgetItem(shop_display)
            shop_item.setFlags(shop_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, shop_item)

            # Col 2 — URL (editable QLineEdit)
            url_edit = QLineEdit(original_url)
            url_edit.setPlaceholderText("Leave empty — auto-resolver will fill this")
            self.table.setCellWidget(row, 2, url_edit)

            self._row_data.append({
                "shop": shop_display,
                "key": key,
                "original_enabled": original_enabled,
                "original_url": original_url,
                "record_id": record.id if record else None,
                "checkbox": checkbox,
                "url_edit": url_edit,
            })

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        confirm_btn = QPushButton("Confirm")
        cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(confirm_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        confirm_btn.clicked.connect(self._on_confirm)
        cancel_btn.clicked.connect(self.close)

        self.setLayout(layout)

    # ---------------------------------------------------------
    # Save logic
    # ---------------------------------------------------------

    def _collect_changes(self):
        """Diff the table against the DB state loaded when the dialog opened.

        Returns (to_add, to_remove, to_update, summary_lines) — the first three
        in the shape apply_shop_changes() expects, the last one describing every
        change for the confirmation dialog."""
        to_add = []
        to_remove = []
        to_update = []
        summary = []

        for info in self._row_data:
            enabled = info["checkbox"].isChecked()
            new_url = info["url_edit"].text().strip()
            was_enabled = info["original_enabled"]
            old_url = info["original_url"]
            shop = info["shop"]
            rid = info["record_id"]

            if enabled and not was_enabled:
                to_add.append({"shop": shop, "url": new_url})
                summary.append(
                    f"  • {shop}: shop added "
                    + ("with a manual URL" if new_url else "(auto-resolver will search)")
                )

            elif not enabled and was_enabled:
                to_remove.append((rid, shop))
                summary.append(f"  • {shop}: shop removed")

            elif enabled and was_enabled and new_url != old_url:
                to_update.append((rid, new_url))
                if not new_url:
                    detail = "URL cleared (auto-resolver will search again)"
                elif old_url:
                    detail = "existing URL replaced with a new manual URL"
                else:
                    detail = "manual URL set"
                summary.append(f"  • {shop}: {detail}")

        return to_add, to_remove, to_update, summary

    def _on_confirm(self):
        to_add, to_remove, to_update, summary = self._collect_changes()

        if not to_add and not to_remove and not to_update:
            self.reject()
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Shop Changes",
            "The following shop changes will be applied:\n\n"
            + "\n".join(summary)
            + "\n\nDo you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        apply_shop_changes(self.product_id, to_add, to_remove, to_update)
        self.changes_applied = True
        self.accept()