from services.product_service import delete_products, get_products, delete_product_platforms
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox
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
            checkbox_item = QTableWidgetItem()
            checkbox_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable |
                Qt.ItemFlag.ItemIsEnabled
            )
            checkbox_item.setCheckState(Qt.CheckState.Unchecked)
            # store product id and platform in item data
            checkbox_item.setData(Qt.ItemDataRole.UserRole, pid)
            checkbox_item.setData(Qt.ItemDataRole.UserRole + 1, plat)

            self.product_table.setItem(row, 0, checkbox_item)
            self.product_table.setItem(row, 1, QTableWidgetItem(name))
            self.product_table.setItem(row, 2, QTableWidgetItem(plat))
            self.product_table.setItem(row, 3, QTableWidgetItem(f"{price} €"))

    def confirm_delete(self):
        # Collect platforms to remove per product id
        to_remove = {}
        for row in range(self.product_table.rowCount()):
            item = self.product_table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                pid = item.data(Qt.ItemDataRole.UserRole)
                plat = item.data(Qt.ItemDataRole.UserRole + 1)
                if pid is None:
                    continue
                to_remove.setdefault(pid, []).append(plat)

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
            # Call service to remove platforms or delete product if no platforms remain
            for pid, plats in to_remove.items():
                delete_product_platforms(pid, plats)
            self.product_deleted.emit()
            self.close()