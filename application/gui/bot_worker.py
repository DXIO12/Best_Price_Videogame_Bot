import threading

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot

from application.bot.bot import check_prices


class BotWorkerSignals(QObject):
    started = pyqtSignal()
    finished = pyqtSignal()
    error = pyqtSignal(str)


class BotWorker(QRunnable):
    def __init__(self, stop_event: threading.Event | None = None,
                 pause_event: threading.Event | None = None):
        super().__init__()
        self.signals = BotWorkerSignals()
        self.stop_event = stop_event
        self.pause_event = pause_event

    @pyqtSlot()
    def run(self):
        self.signals.started.emit()
        try:
            check_prices(stop_event=self.stop_event, pause_event=self.pause_event)
        except Exception as error:
            self.signals.error.emit(str(error))
        finally:
            self.signals.finished.emit()