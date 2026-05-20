from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot

from bot import check_prices


class BotWorkerSignals(QObject):
    started = pyqtSignal()
    finished = pyqtSignal()
    error = pyqtSignal(str)


class BotWorker(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = BotWorkerSignals()

    @pyqtSlot()
    def run(self):
        self.signals.started.emit()
        try:
            check_prices()
        except Exception as error:
            self.signals.error.emit(str(error))
        finally:
            self.signals.finished.emit()
