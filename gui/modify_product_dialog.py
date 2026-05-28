from services.product_service import modify_product, get_products
from gui.add_product_dialog import MultiSelectDropdown
from PyQt6.QtCore import pyqtSignal
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
    QAbstractItemView
)

class ModifyProductDialog(QDialog):

    product_modified = pyqtSignal()
    resolve_urls_requested = pyqtSignal(list)  # emits list of product_ids

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Modify Product")

        self.resize(700, 500)

        self.setup_ui()
        self.load_products()

    def setup_ui(self):

        layout = QVBoxLayout()

        title = QLabel("Select products to modify (click checkbox column to select, double-click cells to edit)")
        layout.addWidget(title)

        self.product_table = QTableWidget()
        self.product_table.setColumnCount(4)
        self.product_table.setHorizontalHeaderLabels([
            "Modify",
            "Product",
            "Platform",
            "Target Price"
        ])
        # Enable editing on double-click (but not for platform column which uses widget)
        self.product_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
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

        self.modify_button = QPushButton("Apply Changes")
        self.resolve_button = QPushButton("Resolve URLs")
        self.cancel_button = QPushButton("Cancel")

        button_layout.addWidget(self.modify_button)
        button_layout.addWidget(self.resolve_button)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.modify_button.clicked.connect(self.on_apply_changes)
        self.resolve_button.clicked.connect(self.on_resolve_urls)
        self.cancel_button.clicked.connect(self.close)

        self.setLayout(layout)

    def load_products(self):
        products = get_products()

        # Platform options for the dropdown
        platform_options = [
            "PS5",
            "NS2",
            "NS",
            "PC",
            "Xbox Series X"
        ]

        # Build rows per platform (split comma-separated platform field)
        self.product_rows = []
        display_rows = []
        
        for product in products:
            if product.platforms:
                plats = [platform.name for platform in product.platforms]
            else:
                plats = ['']
            
            # Store product info for later use
            self.product_rows.append({
                'product_id': product.id,
                'original_name': product.name,
                'original_platforms': plats,
                'original_price': product.target_price
            })
            
            for plat in plats:
                display_rows.append((product.id, product.name, plat, product.target_price))

        self.product_table.setRowCount(0)
        self.product_table.setRowCount(len(display_rows))
        self.platform_widgets = {}  # Dictionary to store platform widgets by row

        for row, (pid, name, plat, price) in enumerate(display_rows):
            # Checkbox column (full-cell widget)
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

            # Product name (editable)
            name_item = QTableWidgetItem(name)
            self.product_table.setItem(row, 1, name_item)

            # Platform (MultiSelectDropdown widget)
            platform_dropdown = MultiSelectDropdown(
                platform_options,
                selected=[plat] if plat else [],
                include_all_option=False
            )
            self.product_table.setCellWidget(row, 2, platform_dropdown)
            self.platform_widgets[row] = platform_dropdown

            # Target Price (editable, with € symbol)
            price_item = QTableWidgetItem(f"{price} €")
            self.product_table.setItem(row, 3, price_item)

    def on_resolve_urls(self):
        """Collect checked product IDs and request URL resolution for them."""
        product_ids = set()

        for row in range(self.product_table.rowCount()):
            checkbox_widget = self.product_table.cellWidget(row, 0)
            checkbox = checkbox_widget.findChild(QCheckBox) if checkbox_widget else None
            if checkbox and checkbox.isChecked():
                pid = checkbox.property("product_id")
                if pid is not None:
                    product_ids.add(pid)

        if not product_ids:
            QMessageBox.warning(
                self,
                "No products selected",
                "Please select at least one product to resolve URLs for."
            )
            return

        confirm = QMessageBox.question(
            self,
            "Resolve URLs",
            f"Resolve missing URLs for {len(product_ids)} product(s)?\n"
            "Only shops without a URL will be updated.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.resolve_urls_requested.emit(list(product_ids))
            self.close()

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
                price_item = self.product_table.item(row, 3)

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

        # Show confirmation
        changes_text = "The following changes will be applied:\n\n"
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
            # Apply changes to database
            for product_id, changes in selected_changes.items():
                modify_product(
                    product_id,
                    changes['platforms'],
                    new_name=changes['name'],
                    new_target_price=changes['price']
                )

            self.load_products()
            QMessageBox.information(self, "Success", "Products updated successfully.")
            self.product_modified.emit()
            self.close()