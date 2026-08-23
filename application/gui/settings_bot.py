from application.config.logger import get_logger
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QComboBox,
    QLineEdit,
    QPushButton,
    QLabel,
    QSpinBox,
    QCheckBox,
    QMessageBox,
    QWidget,
    QTabWidget,
    QFileDialog,
    QInputDialog,
    QFrame,
)
from PyQt6.QtCore import pyqtSignal

from application.database.db import SessionLocal, active_path
from application.database.models import Product, Setting
from application.gui.import_products_dialog import ImportProductsDialog, MODE_REPLACE
from application.services.product_io import (
    ProductIOError,
    apply_merge,
    apply_replace,
    export_products,
    read_export_file,
    rename_database,
    suggested_export_name,
)
from application.bot.notifier import send_telegram_message
from application.config.runtime_config import get_debug_mode, write_config_settings
from application.language_selector import available_languages, get_language, set_language, tr

log = get_logger("gui.settings")


DEFAULTS = {
    "check_interval_minutes": 30,
    "notify_only_best_price": False,
    "repeat_notifications": True,
    "repeat_notification_minutes": 90,
    "allow_parallel_scraping": False,
    "max_parallel_workers": 4,
}

# Tooltips live in the catalogs under "settings.tooltip_<field key>". They are
# fetched per call rather than held in a module-level dict: such a dict is
# built once at import, which would pin every tooltip to whatever language was
# active at startup and leave them stale after a language change.


class SettingsBotDialog(QDialog):

    settings_saved = pyqtSignal()
    # Raised by the Data tab when the product list itself changed, so the
    # main window can rebuild its table. Kept apart from settings_saved:
    # that one fires on Save and only ever means "the options changed".
    products_changed = pyqtSignal()

    def __init__(self, parent=None, auto_start: bool = False,
                 open_on_data: bool = False, bot_active: bool = False):
        super().__init__(parent)
        self.auto_start = auto_start
        # Opened from the header's import/export button rather than the gear:
        # the Data tab is what that button is for, so land on it.
        self.open_on_data = open_on_data
        # Importing or renaming while a pass is scraping would pull the
        # database out from under the running worker, so both are refused
        # until the bot is stopped.
        self.bot_active = bot_active
        # "Settings", not "Settings Bot": the window now also holds
        # application-level options (language, debug mode, parallel scraping).
        self.setWindowTitle(tr("settings.window_title"))
        # Tall enough for the Application tab, which is now the longer of the
        # two: the Telegram rows and their test button sit below debug mode.
        self.resize(520, 400)
        self._load_data()
        self._setup_ui()

    def _load_data(self):
        db = SessionLocal()
        self._existing = db.query(Setting).first()
        db.close()

    def _label_widget(self, field_key: str, label_text: str) -> QWidget:
        """Returns [Label] [ℹ button] widget for use as a form row label."""
        widget = QWidget()
        h = QHBoxLayout(widget)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        h.addWidget(QLabel(label_text))
        info_btn = QPushButton("i")
        info_btn.setFixedSize(20, 20)
        info_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border-radius: 10px;
                font-weight: bold;
                font-size: 11px;
                border: none;
                padding: 0px;
            }
            QPushButton:hover { background-color: #1976D2; }
        """)
        tip = tr(f"settings.tooltip_{field_key}")
        info_btn.setToolTip(tip)
        info_btn.clicked.connect(
            lambda _, t=tip, title=label_text: QMessageBox.information(self, title, t)
        )
        h.addWidget(info_btn)
        h.addStretch()
        return widget

    def _make_form_page(self):
        """Returns (page, form) for one tab: the form on top, stretch below.

        The stretch matters: without it QFormLayout spreads the leftover
        height between its rows, so tabs with fewer controls would show
        wider gaps than the others."""
        page = QWidget()
        v = QVBoxLayout(page)
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        v.addLayout(form)
        v.addStretch()
        return page, form

    def _setup_ui(self):
        layout = QVBoxLayout()

        # Application first: opened from the gear, the app-wide options
        # (language above all) are what the user came for. The exception is the
        # auto_start flow — the dialog only appears there because the bot has no
        # configuration yet, so it opens on Bot, where that configuration lives.
        tabs = QTabWidget()
        tabs.addTab(self._build_app_tab(), tr("settings.tab_app"))
        bot_index = tabs.addTab(self._build_bot_tab(), tr("settings.tab_bot"))
        # Data last: it is the only tab holding actions rather than options,
        # and the only one reached by its own button in the header.
        data_index = tabs.addTab(self._build_data_tab(), tr("settings.tab_data"))
        if self.auto_start:
            tabs.setCurrentIndex(bot_index)
        elif self.open_on_data:
            tabs.setCurrentIndex(data_index)
        layout.addWidget(tabs)

        btn_layout = QHBoxLayout()
        save_label = tr("settings.btn_start_bot") if self.auto_start else tr("common.save")
        save_btn = QPushButton(save_label)
        cancel_btn = QPushButton(tr("common.cancel"))
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        save_btn.clicked.connect(self._on_save)
        cancel_btn.clicked.connect(self.close)

        self.setLayout(layout)

    def _build_bot_tab(self) -> QWidget:
        """How the bot behaves: polling cadence and notification rules."""
        s = self._existing
        page, form = self._make_form_page()

        # check_interval_minutes
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 1440)
        self._interval_spin.setSuffix(tr("settings.suffix_minutes"))
        self._interval_spin.setValue(
            s.check_interval_minutes if s and s.check_interval_minutes
            else DEFAULTS["check_interval_minutes"]
        )
        form.addRow(
            self._label_widget("check_interval_minutes", tr("settings.label_check_interval")),
            self._interval_spin,
        )

        # notify_only_best_price
        self._best_price_chk = QCheckBox()
        self._best_price_chk.setChecked(
            s.notify_only_best_price if s and s.notify_only_best_price is not None
            else DEFAULTS["notify_only_best_price"]
        )
        form.addRow(
            self._label_widget("notify_only_best_price", tr("settings.label_notify_only_best_price")),
            self._best_price_chk,
        )

        # repeat_notifications
        self._repeat_chk = QCheckBox()
        self._repeat_chk.setChecked(
            s.repeat_notifications if s and s.repeat_notifications is not None
            else DEFAULTS["repeat_notifications"]
        )
        form.addRow(
            self._label_widget("repeat_notifications", tr("settings.label_repeat_notifications")),
            self._repeat_chk,
        )

        # repeat_notification_minutes (enabled only when repeat_notifications is ON)
        self._repeat_spin = QSpinBox()
        self._repeat_spin.setRange(1, 1440)
        self._repeat_spin.setSuffix(tr("settings.suffix_minutes"))
        self._repeat_spin.setValue(
            s.repeat_notification_minutes if s and s.repeat_notification_minutes
            else DEFAULTS["repeat_notification_minutes"]
        )
        self._repeat_spin.setEnabled(self._repeat_chk.isChecked())
        self._repeat_chk.toggled.connect(self._repeat_spin.setEnabled)
        form.addRow(
            self._label_widget(
                "repeat_notification_minutes",
                tr("settings.label_repeat_notification_minutes"),
            ),
            self._repeat_spin,
        )

        return page

    def _build_app_tab(self) -> QWidget:
        """How the app itself runs: language, scraping concurrency, debug mode."""
        s = self._existing
        page, form = self._make_form_page()

        # language — first row: it is the one setting that changes every other
        # label on screen. Options come from whatever catalogs exist on disk,
        # so a new languages/*.json shows up here without touching this file.
        self._language_combo = QComboBox()
        for code, display_name in available_languages():
            self._language_combo.addItem(display_name, code)
        current = self._language_combo.findData(get_language())
        if current >= 0:
            self._language_combo.setCurrentIndex(current)
        form.addRow(
            self._label_widget("language", tr("settings.label_language")),
            self._language_combo,
        )

        # allow_parallel_scraping
        self._parallel_chk = QCheckBox()
        self._parallel_chk.setChecked(
            s.allow_parallel_scraping if s and s.allow_parallel_scraping is not None
            else DEFAULTS["allow_parallel_scraping"]
        )
        form.addRow(
            self._label_widget("allow_parallel_scraping", tr("settings.label_parallel_scraping")),
            self._parallel_chk,
        )

        # max_parallel_workers (enabled only when allow_parallel_scraping is ON)
        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(2, 8)
        self._workers_spin.setSuffix(tr("settings.suffix_shops_at_once"))
        self._workers_spin.setValue(
            s.max_parallel_workers if s and s.max_parallel_workers
            else DEFAULTS["max_parallel_workers"]
        )
        self._workers_spin.setEnabled(self._parallel_chk.isChecked())
        self._parallel_chk.toggled.connect(self._workers_spin.setEnabled)
        form.addRow(
            self._label_widget("max_parallel_workers", tr("settings.label_max_parallel_workers")),
            self._workers_spin,
        )

        # debug_mode (frozen-aware default when no explicit value is stored yet)
        self._debug_chk = QCheckBox()
        self._debug_chk.setChecked(
            s.debug_mode if s and s.debug_mode is not None
            else get_debug_mode()
        )
        form.addRow(
            self._label_widget("debug_mode", tr("settings.label_debug_mode")),
            self._debug_chk,
        )

        # Telegram credentials. These live here rather than only in a .env so a
        # packaged build can be configured from inside the app — see the
        # comment on Setting.telegram_bot_token.
        self._token_edit = QLineEdit(s.telegram_bot_token if s and s.telegram_bot_token else "")
        # Masked: a bot token is a bearer credential, and this dialog gets
        # opened while screen-sharing. The Test button below is how you confirm
        # it was pasted correctly, so nothing is lost by not showing it.
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_edit.setPlaceholderText(tr("settings.placeholder_telegram_token"))
        form.addRow(
            self._label_widget("telegram_bot_token", tr("settings.label_telegram_token")),
            self._token_edit,
        )

        self._chat_edit = QLineEdit(s.telegram_chat_id if s and s.telegram_chat_id else "")
        self._chat_edit.setPlaceholderText(tr("settings.placeholder_telegram_chat_id"))
        form.addRow(
            self._label_widget("telegram_chat_id", tr("settings.label_telegram_chat_id")),
            self._chat_edit,
        )

        self._test_btn = QPushButton(tr("settings.btn_test_telegram"))
        self._test_btn.clicked.connect(self._on_test_telegram)
        form.addRow("", self._test_btn)

        return page

    def _on_test_telegram(self):
        """Send a real message with whatever is typed in the two fields.

        Deliberately uses the field contents rather than what is stored: the
        point is to check a token *before* saving it, and to give the person
        setting this up the one thing a masked field cannot — proof that it
        works."""
        token = self._token_edit.text().strip()
        chat_id = self._chat_edit.text().strip()

        if not token or not chat_id:
            QMessageBox.warning(self, tr("settings.btn_test_telegram"),
                                tr("settings.telegram_test_missing"))
            return

        self._test_btn.setEnabled(False)
        self._test_btn.setText(tr("settings.telegram_test_sending"))
        # Repaint before the blocking request, or the button never visibly changes.
        self._test_btn.repaint()
        try:
            ok = send_telegram_message(token, chat_id, tr("settings.telegram_test_message"))
        finally:
            self._test_btn.setEnabled(True)
            self._test_btn.setText(tr("settings.btn_test_telegram"))

        if ok:
            QMessageBox.information(self, tr("settings.btn_test_telegram"),
                                    tr("settings.telegram_test_ok"))
        else:
            QMessageBox.critical(self, tr("settings.btn_test_telegram"),
                                 tr("settings.telegram_test_failed"))

    # =========================================
    # DATA TAB
    # =========================================

    def _build_data_tab(self) -> QWidget:
        """Moving the tracking list between two bots, and where it lives.

        Unlike the other two tabs, nothing here waits for Save: exporting,
        importing and renaming act the moment they are confirmed, the way the
        Telegram test button already does. Save/Cancel at the bottom belong to
        the dialog, not to this tab — they still commit Application and Bot."""
        page, form = self._make_form_page()

        self._export_btn = QPushButton(tr("settings.btn_export_products"))
        self._export_btn.clicked.connect(self._on_export_products)
        form.addRow(
            self._label_widget("export_products", tr("settings.label_export_products")),
            self._export_btn,
        )

        self._import_btn = QPushButton(tr("settings.btn_import_products"))
        self._import_btn.clicked.connect(self._on_import_products)
        form.addRow(
            self._label_widget("import_products", tr("settings.label_import_products")),
            self._import_btn,
        )

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        form.addRow(separator)

        # Name first, then where it lives: the name is the part that can be
        # changed, the path is context for it.
        name_widget = QWidget()
        name_layout = QHBoxLayout(name_widget)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(8)
        self._db_name_label = QLabel()
        name_layout.addWidget(self._db_name_label)
        name_layout.addStretch()
        self._rename_btn = QPushButton(tr("settings.btn_rename_database"))
        self._rename_btn.clicked.connect(self._on_rename_database)
        name_layout.addWidget(self._rename_btn)
        form.addRow(
            self._label_widget("database_name", tr("settings.label_database_name")),
            name_widget,
        )

        self._db_path_label = QLabel()
        self._db_path_label.setWordWrap(True)
        self._db_path_label.setStyleSheet("QLabel { color: #9e9e9e; }")
        form.addRow(tr("settings.label_database_path"), self._db_path_label)

        self._product_count_label = QLabel()
        self._product_count_label.setStyleSheet("QLabel { color: #9e9e9e; }")
        form.addRow(tr("settings.label_product_count"), self._product_count_label)

        self._refresh_data_info()
        return page

    def _refresh_data_info(self):
        """Re-read name, path and product count — they change under this tab
        whenever an import or a rename succeeds."""
        current = active_path()
        self._db_name_label.setText(current.name)
        self._db_path_label.setText(str(current.parent))

        db = SessionLocal()
        try:
            count = db.query(Product).count()
        finally:
            db.close()
        self._product_count_label.setText(str(count))

    def _refuse_while_bot_active(self) -> bool:
        """True when the action must not run, having already told the user why.

        A pass in flight holds sessions against the current file; importing or
        renaming underneath it would either corrupt the pass or, for a rename,
        leave the next session opening a database that is no longer there."""
        if not self.bot_active:
            return False
        QMessageBox.warning(
            self,
            tr("settings.tab_data"),
            tr("settings.data_bot_active"),
        )
        return True

    # -- export -------------------------------------------------------------

    def _on_export_products(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("settings.export_dialog_title"),
            str(Path.home() / suggested_export_name()),
            tr("settings.json_filter"),
        )
        if not path:
            return

        try:
            count = export_products(Path(path))
        except ProductIOError as exc:
            QMessageBox.critical(
                self,
                tr("settings.export_dialog_title"),
                tr("settings.export_failed", error=str(exc)),
            )
            return

        QMessageBox.information(
            self,
            tr("settings.export_dialog_title"),
            tr("settings.export_done", count=count, path=path),
        )

    # -- import -------------------------------------------------------------

    def _on_import_products(self):
        if self._refuse_while_bot_active():
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("settings.import_dialog_title"),
            str(Path.home()),
            tr("settings.json_filter"),
        )
        if not path:
            return

        try:
            preview = read_export_file(Path(path))
        except ProductIOError as exc:
            QMessageBox.critical(
                self,
                tr("settings.import_dialog_title"),
                tr("settings.import_unreadable", error=str(exc)),
            )
            return

        chooser = ImportProductsDialog(preview, parent=self)
        if chooser.exec() != QDialog.DialogCode.Accepted:
            return

        try:
            if chooser.mode == MODE_REPLACE:
                result = apply_replace(preview)
            else:
                result = apply_merge(preview, chooser.placement, chooser.manual_order)
        except Exception as exc:  # noqa: BLE001 - a half-applied import must still report
            log.error(f"Import failed: {exc}")
            QMessageBox.critical(
                self,
                tr("settings.import_dialog_title"),
                tr("settings.import_failed", error=str(exc)),
            )
            self._refresh_data_info()
            self.products_changed.emit()
            return

        self._refresh_data_info()
        self.products_changed.emit()

        message = tr("settings.import_done", added=result.added, skipped=result.skipped) \
            if chooser.mode != MODE_REPLACE \
            else tr("settings.import_done_replace", added=result.added, removed=result.removed)
        if result.unknown_platforms:
            message += "\n\n" + tr(
                "settings.import_unknown_platforms",
                platforms=", ".join(sorted(result.unknown_platforms)),
            )

        QMessageBox.information(self, tr("settings.import_dialog_title"), message)

    # -- rename -------------------------------------------------------------

    def _on_rename_database(self):
        if self._refuse_while_bot_active():
            return

        current = active_path().name
        new_name, accepted = QInputDialog.getText(
            self,
            tr("settings.rename_dialog_title"),
            tr("settings.rename_dialog_label"),
            QLineEdit.EchoMode.Normal,
            current,
        )
        if not accepted or not new_name.strip() or new_name.strip() == current:
            return

        try:
            rename_database(new_name)
        except ProductIOError as exc:
            reason = str(exc)
            if reason == "invalid":
                text = tr("settings.rename_invalid")
            elif reason == "exists":
                text = tr("settings.rename_exists", name=new_name.strip())
            else:
                text = tr("settings.rename_failed", error=reason)
            QMessageBox.critical(self, tr("settings.rename_dialog_title"), text)
            return

        self._refresh_data_info()
        QMessageBox.information(
            self,
            tr("settings.rename_dialog_title"),
            tr("settings.rename_done", name=active_path().name),
        )

    def _on_save(self):
        interval = self._interval_spin.value()
        notify_best = self._best_price_chk.isChecked()
        repeat = self._repeat_chk.isChecked()
        repeat_mins = self._repeat_spin.value()
        parallel = self._parallel_chk.isChecked()
        workers = self._workers_spin.value()
        debug = self._debug_chk.isChecked()
        language = self._language_combo.currentData() or get_language()
        telegram_token = self._token_edit.text().strip()
        telegram_chat = self._chat_edit.text().strip()

        db = SessionLocal()
        setting = db.query(Setting).first()
        if setting is None:
            setting = Setting()
            db.add(setting)

        setting.check_interval_minutes = interval
        setting.notify_only_best_price = notify_best
        setting.repeat_notifications = repeat
        setting.repeat_notification_minutes = repeat_mins
        setting.allow_parallel_scraping = parallel
        setting.max_parallel_workers = workers
        setting.debug_mode = debug
        setting.language = language
        setting.telegram_bot_token = telegram_token or None
        setting.telegram_chat_id = telegram_chat or None

        db.commit()
        db.close()

        # Mirror to config.json for external tooling (DB stays source of truth).
        write_config_settings({
            "check_interval_minutes": interval,
            "notify_only_best_price": notify_best,
            "repeat_notifications": repeat,
            "repeat_notification_minutes": repeat_mins,
            "allow_parallel_scraping": parallel,
            "max_parallel_workers": workers,
            "debug_mode": debug,
            "language": language,
        })

        # Applied before settings_saved fires, so whoever listens (the main
        # window, to relabel itself) already sees the new language.
        set_language(language)

        log.rule()
        log.info(f"Check Interval:          {interval} min")
        log.info(f"Notify Only Best Price:  {notify_best}")
        log.info(f"Repeat Notifications:    {repeat}")
        if repeat:
            log.info(f"Repeat After:            {repeat_mins} min")
        log.info(f"Parallel Scraping:       {parallel}")
        if parallel:
            log.info(f"Parallel Workers:        {workers}")
        log.info(f"Debug Mode:              {debug}")
        log.info(f"Language:                {language}")
        # The token is never logged, only whether one is present.
        log.info(f"Telegram:                "
                 f"{'configured' if telegram_token and telegram_chat else 'not configured'}")
        log.rule()

        self.settings_saved.emit()
        self.accept()
