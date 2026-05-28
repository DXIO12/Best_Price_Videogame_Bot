from services.product_service import create_product
from PyQt6.QtCore import pyqtSignal, QTimer, QPoint
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QDoubleSpinBox,
    QHBoxLayout,
    QCheckBox,
    QWidget,
    QMenu,
    QWidgetAction,
    QScrollArea,
    QFrame,
    QMessageBox
)
import os


def get_available_shops_urlsearcher():
    """Dynamically get shop names from the shops folder"""
    shops_dir = os.path.join(os.path.dirname(__file__), '..', 'shops')
    shops = []

    EXCLUDED_SHOPS_URLSEARCHER = ['playwright_utils.py', 'price_utils.py', 'carrefour.py', 'fnac.py', 'corteingles.py'] 

    for file in os.listdir(shops_dir):
        if file.endswith('.py') and not file.startswith('__') and file not in EXCLUDED_SHOPS_URLSEARCHER:
            shop_name = file.replace('.py', '').capitalize()
            shops.append(shop_name)

    shops.sort()
    return shops

def get_available_shops():
    """Dynamically get shop names from the shops folder"""
    shops_dir = os.path.join(os.path.dirname(__file__), '..', 'shops')
    shops = []

    EXCLUDED_SHOPS = ['playwright_utils.py', 'price_utils.py', 'fnac.py']  
    for file in os.listdir(shops_dir):
        if file.endswith('.py') and not file.startswith('__') and file not in EXCLUDED_SHOPS:
            shop_name = file.replace('.py', '').capitalize()
            shops.append(shop_name)

    shops.sort()
    return shops

class SingleClickDoubleSpinBox(QDoubleSpinBox):
    def focusInEvent(self, event):
        super().focusInEvent(event)
        QTimer.singleShot(0, lambda: self.lineEdit().selectAll())


class MultiSelectDropdown(QWidget):
    shops_changed = pyqtSignal(list)

    def __init__(self, items, selected=None, include_all_option=True):
        super().__init__()
        self.shops = list(items)
        self.shop_checkboxes = {}
        if selected is None:
            self._state = {s: True for s in self.shops}
        else:
            sel = set(selected)
            self._state = {s: (s in sel) for s in self.shops}
        self.include_all_option = bool(include_all_option)
        self.setup_ui()
        self.update_display()

    def setup_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.display_button = QPushButton("ALL")
        self.display_button.clicked.connect(self.show_popup)
        self.display_button.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding-left: 10px;
                padding-right: 25px;
                height: 30px;
                border: 1px solid #555;
                border-radius: 4px;
                background-color: #434348;
                color: #fff;
            }
            QPushButton:hover { background-color: #434348; }
        """)
        layout.addWidget(self.display_button)
        self.setLayout(layout)

    def show_popup(self):
        menu = QMenu(self)
        if self.include_all_option:
            all_widget_action = QWidgetAction(menu)
            all_cb = QCheckBox("ALL")
            all_cb.setChecked(all(self._state.values()))
            all_cb.stateChanged.connect(lambda state: self._set_all_state(state == 2))
            all_widget_action.setDefaultWidget(all_cb)
            menu.addAction(all_widget_action)
            menu.addSeparator()

        for shop in self.shops:
            wa = QWidgetAction(menu)
            cb = QCheckBox(shop)
            cb.setChecked(self._state.get(shop, True))
            self.shop_checkboxes[shop] = cb
            cb.stateChanged.connect(lambda state, s=shop: self._on_checkbox_toggled(s, state == 2))
            wa.setDefaultWidget(cb)
            menu.addAction(wa)

        pos = self.display_button.mapToGlobal(QPoint(0, self.display_button.height()))
        menu.exec(pos)
        self.update_display()

    def _set_all_state(self, checked: bool):
        for s in list(self._state.keys()):
            self._state[s] = checked
            if s in self.shop_checkboxes:
                try:
                    self.shop_checkboxes[s].setChecked(checked)
                except Exception:
                    pass
        self.update_display()
        self.shops_changed.emit(self.get_selected())

    def _on_checkbox_toggled(self, shop: str, checked: bool):
        self._state[shop] = checked
        self.update_display()
        self.shops_changed.emit(self.get_selected())

    def _on_action_toggled(self, shop: str, checked: bool, action):
        self._state[shop] = checked
        try:
            action.setChecked(checked)
        except Exception:
            pass
        self.update_display()
        self.shops_changed.emit(self.get_selected())

    def update_display(self):
        selected = self.get_selected()
        if len(selected) == len(self.shops):
            self.display_button.setText("ALL")
        elif len(selected) == 0:
            self.display_button.setText("None")
        elif len(selected) == 1:
            self.display_button.setText(selected[0])
        else:
            self.display_button.setText(f"{len(selected)} selected")

    def get_selected(self):
        return [s for s, v in self._state.items() if v]

    def set_all_checked(self, checked: bool = True):
        for s in list(self._state.keys()):
            self._state[s] = checked
            if s in self.shop_checkboxes:
                try:
                    self.shop_checkboxes[s].setChecked(checked)
                except Exception:
                    pass
        self.update_display()


# =========================================================
# MANUAL URL DIALOG
# =========================================================

class ManualUrlDialog(QDialog):

    urls_confirmed = pyqtSignal(dict)
    name_provided = pyqtSignal(str)

    def __init__(self, shops: list, product_name: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Shop URLs")
        self.resize(550, 400)
        self.shops = shops
        self.product_name = product_name
        self.url_inputs = {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        self.name_row = QWidget()
        name_layout = QHBoxLayout()
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_label = QLabel("Product Name:")
        name_label.setFixedWidth(130)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter product name")
        if self.product_name:
            self.name_input.setText(self.product_name)
            self.name_row.setVisible(False)
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        self.name_row.setLayout(name_layout)
        layout.addWidget(self.name_row)

        info_label = QLabel(
            "Enter the product URL for each shop (leave blank to auto-resolve):"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        form_layout = QVBoxLayout()
        form_layout.setContentsMargins(4, 4, 4, 4)

        for shop in sorted(self.shops):
            row = QHBoxLayout()
            label = QLabel(f"{shop}:")
            label.setFixedWidth(130)
            url_input = QLineEdit()
            url_input.setPlaceholderText("https://... (optional)")
            self.url_inputs[shop.lower()] = url_input
            row.addWidget(label)
            row.addWidget(url_input)
            row_widget = QWidget()
            row_widget.setLayout(row)
            form_layout.addWidget(row_widget)

        form_layout.addStretch()
        container.setLayout(form_layout)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        button_layout = QHBoxLayout()
        self.confirm_button = QPushButton("Confirm")
        self.cancel_button = QPushButton("Cancel")
        button_layout.addWidget(self.confirm_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        self.confirm_button.clicked.connect(self.on_confirm)
        self.cancel_button.clicked.connect(self.reject)

    def on_confirm(self):
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                "Missing Product Name",
                "Please enter a product name before saving."
            )
            self.name_row.setVisible(True)
            self.name_input.setFocus()
            return

        shop_urls = {
            shop: inp.text().strip()
            for shop, inp in self.url_inputs.items()
            if inp.text().strip()
        }

        if shop_urls:
            reply = QMessageBox.warning(
                self,
                "Confirm URL Override",
                f"You are about to save {len(shop_urls)} manual URL(s).\n"
                "These will override any automatically resolved URLs in the database.\n\n"
                "Are you sure you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if not self.product_name:
            self.name_provided.emit(name)

        self.urls_confirmed.emit(shop_urls)
        self.accept()


# =========================================================
# ADD PRODUCT DIALOG
# =========================================================

class AddProductDialog(QDialog):

    product_added = pyqtSignal(int)  # emits product_id

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Add Product")
        self.resize(400, 300)
        self.manual_shop_urls = {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Product Name"))
        self.name_input = QLineEdit()
        layout.addWidget(self.name_input)

        layout.addWidget(QLabel("Platform"))
        platforms = ["PS5", "NS2", "NS", "PS4", "PC", "Xbox Series X"]
        self.platform_selector = MultiSelectDropdown(
            platforms, selected=["PS5"], include_all_option=False
        )
        layout.addWidget(self.platform_selector)

        layout.addWidget(QLabel("Target Price"))
        self.price_input = SingleClickDoubleSpinBox()
        self.price_input.setMaximum(99999)
        self.price_input.setSuffix(" €")
        layout.addWidget(self.price_input)

        layout.addWidget(QLabel("Select Shops"))
        self.available_shops = get_available_shops_urlsearcher()
        self.shop_selector = MultiSelectDropdown(self.available_shops)
        layout.addWidget(self.shop_selector)

        self.manual_url_checkbox = QCheckBox("Enter shop URLs manually")
        self.manual_url_checkbox.clicked.connect(self.on_manual_url_clicked)
        layout.addWidget(self.manual_url_checkbox)

        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save")
        self.cancel_button = QPushButton("Cancel")
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        self.cancel_button.clicked.connect(self.close)
        self.save_button.clicked.connect(self.save_product)

    def on_manual_url_clicked(self, checked: bool):
        if not checked:
            self.manual_shop_urls = {}
            return

        selected_shops = get_available_shops()
        if not selected_shops:
            QMessageBox.warning(
                self,
                "No Shops Selected",
                "Please select at least one shop before entering URLs."
            )
            self.manual_url_checkbox.setChecked(False)
            return

        dialog = ManualUrlDialog(
            selected_shops,
            product_name=self.name_input.text().strip(),
            parent=self
        )
        dialog.urls_confirmed.connect(self.on_urls_confirmed)
        dialog.name_provided.connect(self.on_name_provided)

        result = dialog.exec()

        if result != QDialog.DialogCode.Accepted:
            self.manual_shop_urls = {}
            self.manual_url_checkbox.setChecked(False)

    def on_name_provided(self, name: str):
        self.name_input.setText(name)

    def on_urls_confirmed(self, shop_urls: dict):
        self.manual_shop_urls = shop_urls
        self.save_product()

    def save_product(self):
        name = self.name_input.text().strip()
        selected_platforms = self.platform_selector.get_selected()
        target_price = self.price_input.value()
        selected_shops = self.shop_selector.get_selected()

        if not name:
            QMessageBox.warning(
                self,
                "Missing Product Name",
                "Please enter a product name before saving."
            )
            return

        if not selected_platforms:
            print("Please select at least one platform.")
            return

        if not selected_shops:
            print("Please select at least one shop.")
            return

        product_id = create_product(
            name=name,
            platforms=selected_platforms,
            target_price=target_price,
            shops=selected_shops,
            shop_urls=self.manual_shop_urls
        )

        print("Product saved successfully.")
        self.product_added.emit(product_id)
        self.close()