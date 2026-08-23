"""Ask what to do with a product file: merge it in, or replace the list.

Nothing is written from here. The dialog only collects the answer — mode,
placement, and (for a hand-sorted merge) the row order — and the Data tab hands
that to ``product_io``. Cancelling anywhere along the way, including inside the
ordering dialog, cancels the whole import.
"""

from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from application.gui.priority_order_dialog import PriorityOrderDialog
from application.language_selector import tr
from application.services.product_io import (
    PLACEMENT_END,
    PLACEMENT_MANUAL,
    PLACEMENT_START,
    merge_order_tokens,
)

MODE_MERGE = "merge"
MODE_REPLACE = "replace"


class ImportProductsDialog(QDialog):
    """Mode + placement chooser for one already-parsed import file."""

    def __init__(self, preview, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("import_products.window_title"))
        self.resize(470, 330)

        self._preview = preview
        self.mode = MODE_MERGE
        self.placement = PLACEMENT_END
        self.manual_order: list[tuple] | None = None

        self._setup_ui()

    # -- construction -------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)

        file_label = QLabel(self._preview.path.name)
        file_label.setWordWrap(True)
        layout.addWidget(file_label)

        summary = QLabel(tr(
            "import_products.summary",
            total=len(self._preview.products),
            new=len(self._preview.new),
        ))
        summary.setWordWrap(True)
        summary.setStyleSheet("QLabel { color: #9e9e9e; }")
        layout.addWidget(summary)

        # -- merge ----------------------------------------------------------
        self._merge_radio = QRadioButton(tr("import_products.mode_merge"))
        self._merge_radio.setChecked(True)
        layout.addWidget(self._merge_radio)
        layout.addWidget(self._hint(
            tr("import_products.mode_merge_hint", current=self._preview.current_count),
            "#9e9e9e",
        ))

        placement_row = QHBoxLayout()
        placement_row.setContentsMargins(20, 0, 0, 0)
        self._placement_label = QLabel(tr("import_products.label_placement"))
        placement_row.addWidget(self._placement_label)

        self._placement_combo = QComboBox()
        self._placement_combo.addItem(tr("import_products.placement_end"), PLACEMENT_END)
        self._placement_combo.addItem(tr("import_products.placement_start"), PLACEMENT_START)
        self._placement_combo.addItem(tr("import_products.placement_manual"), PLACEMENT_MANUAL)
        placement_row.addWidget(self._placement_combo)
        layout.addLayout(placement_row)

        # -- replace --------------------------------------------------------
        self._replace_radio = QRadioButton(tr("import_products.mode_replace"))
        layout.addWidget(self._replace_radio)
        layout.addWidget(self._hint(
            tr("import_products.mode_replace_hint", current=self._preview.current_count),
            "#cc3333",
        ))

        group = QButtonGroup(self)
        group.addButton(self._merge_radio)
        group.addButton(self._replace_radio)

        # Placement only means anything for a merge — same idiom as the
        # Application tab, where the worker count follows the parallel checkbox.
        self._merge_radio.toggled.connect(self._placement_combo.setEnabled)
        self._merge_radio.toggled.connect(self._placement_label.setEnabled)

        layout.addWidget(self._hint(tr("import_products.note_excluded"), "#9e9e9e"))
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._import_button = QPushButton(tr("import_products.btn_import"))
        self._import_button.clicked.connect(self._on_import)
        cancel_button = QPushButton(tr("common.cancel"))
        # Default, so Enter on a dialog that can wipe the list does nothing.
        cancel_button.setDefault(True)
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self._import_button)
        buttons.addWidget(cancel_button)
        layout.addLayout(buttons)

        # Nothing new to add: merging would be a no-op, so only replace is left.
        if not self._preview.new:
            self._merge_radio.setEnabled(False)
            self._replace_radio.setChecked(True)

        self.setLayout(layout)

    @staticmethod
    def _hint(text: str, colour: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setContentsMargins(20, 0, 0, 0)
        label.setStyleSheet(f"QLabel {{ color: {colour}; }}")
        return label

    # -- accept path --------------------------------------------------------

    def _on_import(self):
        if self._replace_radio.isChecked():
            if not self._confirm_replace():
                return
            self.mode = MODE_REPLACE
            self.accept()
            return

        self.mode = MODE_MERGE
        self.placement = self._placement_combo.currentData()

        if self.placement == PLACEMENT_MANUAL:
            order_dialog = PriorityOrderDialog(merge_order_tokens(self._preview), parent=self)
            if order_dialog.exec() != QDialog.DialogCode.Accepted:
                return  # cancelling the order cancels the import, not just the order
            self.manual_order = order_dialog.ordered_tokens()

        self.accept()

    def _confirm_replace(self) -> bool:
        """Second gate for the only destructive choice on this dialog."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("import_products.confirm_replace_title"))
        box.setText(tr(
            "import_products.confirm_replace_body",
            current=self._preview.current_count,
            incoming=len(self._preview.products),
        ))
        box.setInformativeText(tr("import_products.confirm_replace_hint"))

        confirm = box.addButton(
            tr("import_products.confirm_replace_yes"),
            QMessageBox.ButtonRole.DestructiveRole,
        )
        cancel = box.addButton(tr("common.cancel"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is confirm
