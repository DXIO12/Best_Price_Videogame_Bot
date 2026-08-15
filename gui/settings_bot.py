from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QPushButton,
    QLabel,
    QSpinBox,
    QCheckBox,
    QMessageBox,
    QWidget,
    QTabWidget,
)
from PyQt6.QtCore import pyqtSignal

from database.db import SessionLocal
from database.models import Setting
from config.runtime_config import get_debug_mode, write_config_settings


DEFAULTS = {
    "check_interval_minutes": 30,
    "notify_only_best_price": False,
    "repeat_notifications": True,
    "repeat_notification_minutes": 90,
    "allow_parallel_scraping": False,
    "max_parallel_workers": 4,
}

_TOOLTIPS = {
    "check_interval_minutes": (
        "How often (in minutes) the bot checks product prices.\n"
        "Default: 30 min."
    ),
    "notify_only_best_price": (
        "ON  → Only the cheapest shop that beats the target triggers a notification.\n"
        "OFF → Every shop below the target price sends its own notification."
    ),
    "repeat_notifications": (
        "ON  → Re-send the notification after the cooldown period,\n"
        "      even if the price hasn't changed.\n"
        "OFF → Notify only when the price drops for the first time."
    ),
    "repeat_notification_minutes": (
        "Minutes to wait before repeating a notification for the same product.\n"
        "Only active when 'Repeat notifications' is ON.\n"
        "Default: 90 min."
    ),
    "allow_parallel_scraping": (
        "ON  → Several shops are scraped at the same time, so a full check\n"
        "      takes about as long as the slowest shop instead of the sum\n"
        "      of them all.\n"
        "OFF → One shop after another (original behaviour).\n"
        "Each shop is still visited by a single worker, so no site ever\n"
        "receives two simultaneous requests."
    ),
    "max_parallel_workers": (
        "How many shops are scraped at the same time.\n"
        "Only active when 'Parallel scraping' is ON.\n"
        "Each worker launches its OWN browser: expect roughly 0.5 GB of RAM\n"
        "per worker, and with Debug mode ON you will see this many browser\n"
        "windows open at once.\n"
        "Default: 4. Going above that buys very little time for the memory\n"
        "it costs (see the benchmark in the README)."
    ),
    "debug_mode": (
        "ON  → Visible browser windows while scraping + a console with logs.\n"
        "OFF → Headless scraping in the background (Release mode).\n"
        "Takes effect on the next app launch. Default: ON in development, "
        "OFF in the packaged executable."
    ),
}


class SettingsBotDialog(QDialog):

    settings_saved = pyqtSignal()

    def __init__(self, parent=None, auto_start: bool = False):
        super().__init__(parent)
        self.auto_start = auto_start
        # "Settings", not "Settings Bot": the window now also holds
        # application-level options (debug mode, parallel scraping).
        self.setWindowTitle("Settings")
        self.resize(460, 270)
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
        tip = _TOOLTIPS.get(field_key, "")
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

        tabs = QTabWidget()
        tabs.addTab(self._build_bot_tab(), "Bot")
        tabs.addTab(self._build_app_tab(), "Application")
        layout.addWidget(tabs)

        btn_layout = QHBoxLayout()
        save_label = "Start Bot" if self.auto_start else "Save"
        save_btn = QPushButton(save_label)
        cancel_btn = QPushButton("Cancel")
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
        self._interval_spin.setSuffix(" min")
        self._interval_spin.setValue(
            s.check_interval_minutes if s and s.check_interval_minutes
            else DEFAULTS["check_interval_minutes"]
        )
        form.addRow(
            self._label_widget("check_interval_minutes", "Check interval:"),
            self._interval_spin,
        )

        # notify_only_best_price
        self._best_price_chk = QCheckBox()
        self._best_price_chk.setChecked(
            s.notify_only_best_price if s and s.notify_only_best_price is not None
            else DEFAULTS["notify_only_best_price"]
        )
        form.addRow(
            self._label_widget("notify_only_best_price", "Notify only best price"),
            self._best_price_chk,
        )

        # repeat_notifications
        self._repeat_chk = QCheckBox()
        self._repeat_chk.setChecked(
            s.repeat_notifications if s and s.repeat_notifications is not None
            else DEFAULTS["repeat_notifications"]
        )
        form.addRow(
            self._label_widget("repeat_notifications", "Repeat notifications"),
            self._repeat_chk,
        )

        # repeat_notification_minutes (enabled only when repeat_notifications is ON)
        self._repeat_spin = QSpinBox()
        self._repeat_spin.setRange(1, 1440)
        self._repeat_spin.setSuffix(" min")
        self._repeat_spin.setValue(
            s.repeat_notification_minutes if s and s.repeat_notification_minutes
            else DEFAULTS["repeat_notification_minutes"]
        )
        self._repeat_spin.setEnabled(self._repeat_chk.isChecked())
        self._repeat_chk.toggled.connect(self._repeat_spin.setEnabled)
        form.addRow(
            self._label_widget("repeat_notification_minutes", "Repeat notification after:"),
            self._repeat_spin,
        )

        return page

    def _build_app_tab(self) -> QWidget:
        """How the app itself runs: scraping concurrency and debug mode."""
        s = self._existing
        page, form = self._make_form_page()

        # allow_parallel_scraping
        self._parallel_chk = QCheckBox()
        self._parallel_chk.setChecked(
            s.allow_parallel_scraping if s and s.allow_parallel_scraping is not None
            else DEFAULTS["allow_parallel_scraping"]
        )
        form.addRow(
            self._label_widget("allow_parallel_scraping", "Parallel scraping"),
            self._parallel_chk,
        )

        # max_parallel_workers (enabled only when allow_parallel_scraping is ON)
        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(2, 8)
        self._workers_spin.setSuffix(" shops at once")
        self._workers_spin.setValue(
            s.max_parallel_workers if s and s.max_parallel_workers
            else DEFAULTS["max_parallel_workers"]
        )
        self._workers_spin.setEnabled(self._parallel_chk.isChecked())
        self._parallel_chk.toggled.connect(self._workers_spin.setEnabled)
        form.addRow(
            self._label_widget("max_parallel_workers", "Scrape in parallel:"),
            self._workers_spin,
        )

        # debug_mode (frozen-aware default when no explicit value is stored yet)
        self._debug_chk = QCheckBox()
        self._debug_chk.setChecked(
            s.debug_mode if s and s.debug_mode is not None
            else get_debug_mode()
        )
        form.addRow(
            self._label_widget("debug_mode", "Debug mode"),
            self._debug_chk,
        )

        return page

    def _on_save(self):
        interval = self._interval_spin.value()
        notify_best = self._best_price_chk.isChecked()
        repeat = self._repeat_chk.isChecked()
        repeat_mins = self._repeat_spin.value()
        parallel = self._parallel_chk.isChecked()
        workers = self._workers_spin.value()
        debug = self._debug_chk.isChecked()

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
        })

        print("===================================")
        print(f"[Settings Bot] Check Interval:          {interval} min")
        print(f"[Settings Bot] Notify Only Best Price:  {notify_best}")
        print(f"[Settings Bot] Repeat Notifications:    {repeat}")
        if repeat:
            print(f"[Settings Bot] Repeat After:            {repeat_mins} min")
        print(f"[Settings Bot] Parallel Scraping:       {parallel}")
        if parallel:
            print(f"[Settings Bot] Parallel Workers:        {workers}")
        print(f"[Settings Bot] Debug Mode:              {debug}")
        print("===================================")

        self.settings_saved.emit()
        self.accept()
