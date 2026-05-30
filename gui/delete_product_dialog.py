from services.product_service import delete_products, get_products, delete_product_platforms
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

        self.setWindowTitle("Delete Product")

        self.resize(700, 400)

        self.setup_ui()

    def setup_ui(self):

        layout = QVBoxLayout()

        title = QLabel("Select products to delete")
        layout.addWidget(title)

        self.product_table = QTableWidget()
        self.product_table.setColumnCount(4)
        self.product_table.setHorizontalHeaderLabels([
            "Delete",
            "Product",
            "Platform",
            "Target Price"
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

        self.delete_button = QPushButton("Delete Selected")
        self.cancel_button = QPushButton("Cancel")

        button_layout.addWidget(self.delete_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

        self.cancel_button.clicked.connect(self.close)
        self.delete_button.clicked.connect(self.confirm_delete)

        self.load_products()

    def load_products(self):
        products = get_products()

        # Build rows per platform using the relational platform list
        display_rows = []  # tuples of (product_id, product_name, platform, target_price)
        for product in products:
            if product.platforms:
                plats = [platform.name for platform in product.platforms]
            else:
                plats = ['']
            for plat in plats:
                display_rows.append((product.id, product.name, plat, product.target_price))

        self.product_table.setRowCount(0)
        self.product_table.setRowCount(len(display_rows))

        for row, (pid, name, plat, price) in enumerate(display_rows):
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
            self.product_table.setItem(row, 2, QTableWidgetItem(plat))
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
                "No products selected",
                "Please select at least one product/platform to delete."
            )
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Delete",
            "Are you sure you want to delete the selected product/platform(s)?",
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