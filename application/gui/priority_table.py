"""The product table widget, shared by the main window and the import flow.

Lives outside ``main_window`` because that module is also the GUI's entry point:
it builds a QApplication and calls ``app.exec()`` at import time, so importing
anything from it would start a second copy of the app.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QTableWidget


class PriorityTableWidget(QTableWidget):
    """QTableWidget whose drop handling is fully overridden.

    Qt's built-in InternalMove drag-and-drop only relocates the
    QTableWidgetItems, not cell widgets (we use a QLabel for the Shops
    column), which desyncs rows after a drag. Instead we just figure out
    source/target row and let the owner rebuild the whole table from the
    database, which keeps items and cell widgets consistent.
    """

    rowDropped = pyqtSignal(int, int)  # source_row, target_row

    def dropEvent(self, event):
        source_row = self.currentRow()
        pos = event.position().toPoint()
        index = self.indexAt(pos)

        # Threshold is 15% of the row's height into the hovered row.
        # Dragging downward: crossing just the top 15% of a lower row is
        # enough to register "insert below it". Dragging upward: crossing
        # just the bottom 15% of a higher row is enough for "insert above
        # it". This needs noticeably less mouse travel than a full half-row
        # crossing, so a one-row move triggers sooner and feels snappier.
        if index.isValid():
            row_rect = self.visualRect(index)
            hovered_row = index.row()
            if hovered_row > source_row:
                threshold_y = row_rect.top() + row_rect.height() * 0.15
            elif hovered_row < source_row:
                threshold_y = row_rect.top() + row_rect.height() * 0.85
            else:
                threshold_y = row_rect.center().y()
            target_row = hovered_row if pos.y() < threshold_y else hovered_row + 1
        else:
            target_row = self.rowCount()

        # Tell Qt the drop was a no-op (IgnoreAction) rather than a Move.
        # If we let it resolve as a Move, QAbstractItemView's own internals
        # delete the dragged row *after* this method returns — on top of
        # whatever we already did — which silently drops a row from the
        # table. We handle the reorder entirely ourselves, so Qt must not
        # touch the model at all.
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()

        if source_row != -1 and target_row != source_row and target_row != source_row + 1:
            self.rowDropped.emit(source_row, target_row)
