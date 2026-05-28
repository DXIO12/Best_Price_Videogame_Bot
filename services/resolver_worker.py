"""
resolver_worker.py
==================
Runs resolve_urls_for_product() in a background thread via QThreadPool.
Emits signals for started, finished (with results), and error.
"""

from PyQt6.QtCore import QObject, pyqtSignal, QRunnable, pyqtSlot

from services.resolve_urls_service import resolve_urls_for_products


class ResolverWorkerSignals(QObject):
    started  = pyqtSignal()
    finished = pyqtSignal(dict)   # {product_id: {shop: url_or_None}}
    error    = pyqtSignal(str)


class ResolverWorker(QRunnable):
    """
    Resolves missing URLs for a list of product IDs in a background thread.

    Usage:
        worker = ResolverWorker([product_id_1, product_id_2])
        worker.signals.finished.connect(self.on_resolver_finished)
        self.thread_pool.start(worker)
    """

    def __init__(self, product_ids: list[int]):
        super().__init__()
        self.product_ids = product_ids
        self.signals = ResolverWorkerSignals()

    @pyqtSlot()
    def run(self):
        self.signals.started.emit()
        try:
            results = resolve_urls_for_products(self.product_ids)
            self.signals.finished.emit(results)
        except Exception as e:
            self.signals.error.emit(str(e))