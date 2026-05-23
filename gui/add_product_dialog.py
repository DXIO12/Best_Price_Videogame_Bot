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
    QWidgetAction
)
import os

def get_available_shops():
    """Dynamically get shop names from the shops folder"""
    shops_dir = os.path.join(os.path.dirname(__file__), '..', 'shops')
    shops = []

    EXCLUDED_SHOPS = ['playwright_utils.py', 'price_utils.py', 'carrefour.py', 'fnac.py']

    for file in os.listdir(shops_dir):
        if file.endswith('.py') and not file.startswith('__') and file not in EXCLUDED_SHOPS:
            shop_name = file.replace('.py', '').capitalize()
            shops.append(shop_name)

    shops.sort()
    return shops


class SingleClickDoubleSpinBox(QDoubleSpinBox):
    """Custom QDoubleSpinBox that selects all text on a single click"""
    def focusInEvent(self, event):
        super().focusInEvent(event)
        # Use a timer to ensure selectAll happens after the widget is fully focused
        QTimer.singleShot(0, lambda: self.lineEdit().selectAll())


class MultiSelectDropdown(QWidget):
    """Generic dropdown widget for selecting multiple items with checkboxes.

    Parameters:
    - items: list of strings to show
    - selected: optional iterable of items that should be initially selected (defaults to all)
    - include_all_option: whether to show the "ALL" master toggle in the popup
    """

    shops_changed = pyqtSignal(list)

    def __init__(self, items, selected=None, include_all_option=True):
        super().__init__()
        self.shops = list(items)
        # store QAction instances when menu is shown
        self.shop_checkboxes = {}
        # internal state for selections
        if selected is None:
            # default: all selected
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

        # Display label showing selected items
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
            QPushButton:hover {
                background-color: #434348;
            }
        """)

        layout.addWidget(self.display_button)
        self.setLayout(layout)

    def show_popup(self):
        menu = QMenu(self)

        # ALL checkbox (master toggle) implemented as QWidgetAction so menu stays open
        if self.include_all_option:
            all_widget_action = QWidgetAction(menu)
            all_cb = QCheckBox("ALL")
            all_cb.setChecked(all(self._state.values()))
            all_cb.stateChanged.connect(lambda state: self._set_all_state(state == 2))
            all_widget_action.setDefaultWidget(all_cb)
            menu.addAction(all_widget_action)
            menu.addSeparator()

        # Individual item checkboxes (QWidgetAction) so menu doesn't close on toggle
        for shop in self.shops:
            wa = QWidgetAction(menu)
            cb = QCheckBox(shop)
            cb.setChecked(self._state.get(shop, True))
            # store checkbox so we can update it later
            self.shop_checkboxes[shop] = cb
            # capture shop name
            cb.stateChanged.connect(lambda state, s=shop: self._on_checkbox_toggled(s, state == 2))
            wa.setDefaultWidget(cb)
            menu.addAction(wa)

        # Show menu below the button
        pos = self.display_button.mapToGlobal(QPoint(0, self.display_button.height()))
        menu.exec(pos)
        self.update_display()

    def _set_all_state(self, checked: bool):
        """Set all items to checked/unchecked."""
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
        """Handle checkbox toggles without closing the menu."""
        self._state[shop] = checked
        self.update_display()
        self.shops_changed.emit(self.get_selected())

    def _on_action_toggled(self, shop: str, checked: bool, action):
        self._state[shop] = checked
        # keep QAction in sync
        try:
            action.setChecked(checked)
        except Exception:
            pass
        self.update_display()
        self.shops_changed.emit(self.get_selected())

    def update_display(self):
        """Update the display button text based on selected items"""
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
        """Return list of selected items from internal state."""
        return [s for s, v in self._state.items() if v]

    def set_all_checked(self, checked: bool = True):
        """Externally set all items to checked/unchecked."""
        for s in list(self._state.keys()):
            self._state[s] = checked
            if s in self.shop_checkboxes:
                try:
                    # shop_checkboxes now store QCheckBox widgets
                    self.shop_checkboxes[s].setChecked(checked)
                except Exception:
                    pass
        self.update_display()


class AddProductDialog(QDialog):

    product_added = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.setWindowTitle("Add Product")

        self.resize(400, 250)

        self.setup_ui()

    def setup_ui(self):

        layout = QVBoxLayout()

        # PRODUCT NAME
        self.name_label = QLabel("Product Name")

        self.name_input = QLineEdit()

        layout.addWidget(self.name_label)
        layout.addWidget(self.name_input)

        # PLATFORM
        self.platform_label = QLabel("Platform")

        platforms = [
            "PS5",
            "NS2",
            "NS",
            "PS4",
            "PC",
            "Xbox Series X"
        ]

        # Use the same selector widget as shops for platforms (no ALL, default PS5)
        self.platform_selector = MultiSelectDropdown(platforms, selected=["PS5"], include_all_option=False)

        layout.addWidget(self.platform_label)
        layout.addWidget(self.platform_selector)

        # TARGET PRICE
        self.price_label = QLabel("Target Price")

        self.price_input = SingleClickDoubleSpinBox()

        self.price_input.setMaximum(99999)

        self.price_input.setSuffix(" €")

        layout.addWidget(self.price_label)
        layout.addWidget(self.price_input)

        # SHOP SELECTION
        self.shop_label = QLabel("Select Shops")
        available_shops = get_available_shops()
        self.shop_selector = MultiSelectDropdown(available_shops)
        
        layout.addWidget(self.shop_label)
        layout.addWidget(self.shop_selector)

        # BUTTONS
        button_layout = QHBoxLayout()

        self.save_button = QPushButton("Save")

        self.cancel_button = QPushButton("Cancel")

        button_layout.addWidget(self.save_button)

        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

        # SIGNALS
        self.cancel_button.clicked.connect(
            self.close
        )

        self.save_button.clicked.connect(
            self.save_product
        )

    def save_product(self):

        name = self.name_input.text().strip()

        # MULTIPLE PLATFORMS
        selected_platforms = (
            self.platform_selector.get_selected()
        )

        target_price = self.price_input.value()

        # SELECTED SHOPS
        selected_shops = (
            self.shop_selector.get_selected()
        )

        # VALIDATION
        if not name:
            print("Product name is required.")
            return

        if not selected_platforms:
            print("Please select at least one platform.")
            return

        if not selected_shops:
            print("Please select at least one shop.")
            return

        create_product(
            name=name,
            platforms=selected_platforms,
            target_price=target_price,
            shops=selected_shops
        )

        print("Product saved successfully.")

        # UPDATE MAIN WINDOW TABLE
        self.product_added.emit()

        self.close()