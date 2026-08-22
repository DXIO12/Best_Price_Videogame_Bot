from application.services.product_service import (
    delete_products,
    get_products,
    delete_product_platforms,
    get_platform_priorities,
    to_gui_names,
)
from application.language_selector import tr
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QSizePolicy,
    QMessageBox,
    QCheckBox,
    QWidget,
)

class DeleteProductDialog(QDialog):

    product_deleted = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.setWindowTitle(tr("delete_product.window_title"))

        self.resize(700, 400)

        self.setup_ui()

    def setup_ui(self):

        layout = QVBoxLayout()

        title = QLabel(tr("delete_product.heading"))
        layout.addWidget(title)

        self.product_table = QTableWidget()
        self.product_table.setColumnCount(4)
        self.product_table.setHorizontalHeaderLabels([
            tr("delete_product.header_delete"),
            tr("delete_product.header_product"),
            tr("delete_product.header_platform"),
            tr("delete_product.header_target_price")
        ])
        self.product_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.product_table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )
        self.product_table.setColumnWidth(0, 80)
        self.product_table.setColumnWidth(1, 240)
        self.product_table.setColumnWidth(2, 150)
        self.product_table.setColumnWidth(3, 140)

        layout.addWidget(self.product_table)

        button_layout = QHBoxLayout()

        self.delete_button = QPushButton(tr("delete_product.btn_delete_selected"))
        self.cancel_button = QPushButton(tr("common.cancel"))

        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

        self.cancel_button.clicked.connect(self.close)
        self.delete_button.clicked.connect(self.confirm_delete)

        self.load_products()

    def load_products(self):
        products = get_products()
        priorities = get_platform_priorities()

        # Build rows per platform using the relational platform list, keeping the
        # same priority order the main window shows so both tables line up.
        # Rows carry both names: the GUI label is displayed, the DB name is what
        # delete_product_platforms() matches on.
        display_rows = []  # (product_id, product_name, platform_db, platform_gui, target_price)
        for product in products:
            if product.platforms:
                plats = to_gui_names([p.name for p in product.platforms])
                for platform, plat_gui in zip(product.platforms, plats):
                    priority = priorities.get((product.id, platform.id), 0)
                    display_rows.append(
                        (priority, product.id, product.name, platform.name, plat_gui, product.target_price)
                    )
            else:
                # No platform assigned: no product_platforms row to read a
                # priority from, so it sorts first like in the main window.
                display_rows.append((0, product.id, product.name, '', '', product.target_price))

        display_rows.sort(key=lambda entry: entry[0])
        display_rows = [entry[1:] for entry in display_rows]

        self.product_table.setRowCount(0)
        self.product_table.setRowCount(len(display_rows))

        for row, (pid, name, plat, plat_gui, price) in enumerate(display_rows):
            checkbox = QCheckBox()
            checkbox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            checkbox.setStyleSheet("QCheckBox { margin: 0px; padding: 0px; }")
            checkbox.setProperty("product_id", pid)
            checkbox.setProperty("platform", plat)
            checkbox_widget = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_widget)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.addStretch()
            checkbox_layout.addWidget(checkbox)
            checkbox_layout.addStretch()
            checkbox_widget.setLayout(checkbox_layout)
            self.product_table.setCellWidget(row, 0, checkbox_widget)

            self.product_table.setItem(row, 1, QTableWidgetItem(name))
            self.product_table.setItem(row, 2, QTableWidgetItem(plat_gui))
            self.product_table.setItem(row, 3, QTableWidgetItem(f"{price} €"))

    def confirm_delete(self):
        # Collect platforms to remove per product id
        to_remove = {}
        product_names = {}  # pid → name
        for row in range(self.product_table.rowCount()):
            checkbox_widget = self.product_table.cellWidget(row, 0)
            checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget is not None else None
            if checkbox is not None and checkbox.isChecked():
                pid = checkbox.property("product_id")
                plat = checkbox.property("platform")
                if pid is None:
                    continue
                to_remove.setdefault(pid, []).append(plat)
                if pid not in product_names:
                    name_item = self.product_table.item(row, 1)
                    product_names[pid] = name_item.text() if name_item else str(pid)

        if not to_remove:
            QMessageBox.warning(
                self,
                tr("delete_product.none_selected_title"),
                tr("delete_product.none_selected_body")
            )
            return

        confirm = QMessageBox.question(
            self,
            tr("delete_product.confirm_title"),
            tr("delete_product.confirm_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if confirm == QMessageBox.StandardButton.Yes:
            for pid, plats in to_remove.items():
                delete_product_platforms(pid, plats)
                name = product_names.get(pid, str(pid))
                plats_str = ", ".join(plats) if plats else "all platforms"
                print(f"===================================")
                print(f"[Delete] '{name}' — platforms removed: {plats_str}")
            self.product_deleted.emit()
            self.close()