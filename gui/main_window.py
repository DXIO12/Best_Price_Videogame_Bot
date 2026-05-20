import sys
from gui.add_product_dialog import AddProductDialog, get_available_shops
from gui.delete_product_dialog import DeleteProductDialog
from gui.modify_product_dialog import ModifyProductDialog
from services.product_service import get_products_with_shops
from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView
)

from gui.bot_worker import BotWorker


class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Price Bot")

        self.resize(1000, 600)

        self.thread_pool = QThreadPool()

        self.setup_ui()

        self.load_products()

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

        self.start_bot_button = QPushButton(
            "Start Bot"
        )
        self.start_bot_button.setMinimumWidth(180)

        # CONNECT BUTTONS
        self.add_product_button.clicked.connect(
            self.open_add_product_dialog
        )
        self.delete_product_button.clicked.connect(
            self.open_delete_product_dialog
        )
        self.modify_product_button.clicked.connect(
            self.open_modify_product_dialog
        )
        self.start_bot_button.clicked.connect(self.start_bot_worker)

        button_layout.addWidget(
            self.add_product_button
        )

        button_layout.addWidget(
            self.delete_product_button
        )

        button_layout.addWidget(
            self.modify_product_button
        )

        main_layout.addLayout(button_layout)

        # PRODUCT TABLE
        self.product_table = QTableWidget()

        self.product_table.setWordWrap(True)
        self.product_table.setColumnCount(4)

        self.product_table.setHorizontalHeaderLabels([
            "Product",
            "Platform",
            "Target Price",
            "Shops"
        ])

        self.product_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.product_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.product_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        main_layout.addWidget(self.product_table)

        # START BOT BUTTON BELOW DELETE/ADD/OTHER BUTTONS
        start_button_layout = QHBoxLayout()
        start_button_layout.addStretch()
        start_button_layout.addWidget(self.start_bot_button)
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
        dialog.product_added.connect(self.load_products)
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

    def open_modify_product_dialog(self):

        dialog = ModifyProductDialog()
        
        # Refresh table when product is modified
        dialog.product_modified.connect(self.load_products)
        dialog.exec()

    # =========================================
    # LOAD PRODUCTS IN THE TABLE
    # =========================================

    def load_products(self):

        products_with_shops = get_products_with_shops()

        all_shops = get_available_shops()

        # Build display rows: split products by platform so each platform has its own row
        display_rows = []  # tuples of (product, platform, shops)
        for product, shops in products_with_shops:
            # split relational platform list into individual platform entries
            if product.platforms:
                plats = [platform.name for platform in product.platforms]
            else:
                plats = ['']

            for plat in plats:
                display_rows.append((product, plat, shops))

        # CLEAR TABLE
        self.product_table.setRowCount(0)
        self.product_table.setRowCount(len(display_rows))

        for row, (product, platform_value, shops) in enumerate(display_rows):

            self.product_table.setItem(row, 0, QTableWidgetItem(product.name))

            self.product_table.setItem(row, 1, QTableWidgetItem(platform_value))

            self.product_table.setItem(row, 2, QTableWidgetItem(f"{product.target_price} €"))

            # Normalize and deduplicate shops for comparison and display
            if shops:
                norm_all = {s.strip().lower() for s in all_shops}
                norm_shops = [s.strip() for s in shops]
                norm_set = {s.lower() for s in norm_shops}

                if norm_set == norm_all:
                    shops_text = "ALL"
                else:
                    # Preserve original order but remove duplicates (case-insensitive)
                    seen = set()
                    deduped = []
                    for s in norm_shops:
                        key = s.lower()
                        if key in seen:
                            continue
                        seen.add(key)
                        deduped.append(s)
                    shops_text = ", ".join(deduped) if deduped else "None"
            else:
                shops_text = "None"

            self.product_table.setItem(row, 3, QTableWidgetItem(shops_text))

        self.product_table.resizeRowsToContents()

    def start_bot_worker(self):
        self.start_bot_button.setEnabled(False)
        self.status_label.setText("Starting bot...")

        worker = BotWorker()
        worker.signals.started.connect(lambda: self.status_label.setText("Bot is running..."))
        worker.signals.finished.connect(self.on_bot_finished)
        worker.signals.error.connect(self.on_bot_error)

        self.thread_pool.start(worker)

    def on_bot_finished(self):
        self.start_bot_button.setEnabled(True)
        self.status_label.setText("Bot finished.")
        self.load_products()

    def on_bot_error(self, message):
        self.start_bot_button.setEnabled(True)
        self.status_label.setText(f"Bot error: {message}")

app = QApplication(sys.argv)

window = MainWindow()

window.show()

sys.exit(app.exec())