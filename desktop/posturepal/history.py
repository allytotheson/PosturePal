"""Bounded, paginated inspection of persisted posture samples."""

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class AngleChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.setMinimumHeight(220)
        self.setAccessibleName("Upper and lower angles for the displayed sample page")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        area = QRectF(54, 24, max(1, self.width() - 78), max(1, self.height() - 68))
        if not self.rows:
            p.setPen(QColor("#68717b"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No recorded samples")
            return
        first = self.rows[0][3]
        duration = max(0.05, self.rows[-1][3] - first)
        angles = [r[i] for r in self.rows for i in (4, 5)]
        low, high = min(-5, min(angles) - 3), max(5, max(angles) + 3)

        def point(row, column):
            return QPointF(
                area.left() + (row[3] - first) / duration * area.width(),
                area.bottom() - (row[column] - low) / (high - low) * area.height(),
            )

        for i in range(5):
            value = low + (high - low) * i / 4
            y = area.bottom() - area.height() * i / 4
            p.setPen(QPen(QColor("#e4e7eb"), 1))
            p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            p.setPen(QColor("#68717b"))
            p.drawText(
                QRectF(0, y - 10, 47, 20), Qt.AlignmentFlag.AlignRight, f"{value:.0f}°"
            )
        p.setPen(QColor("#68717b"))
        p.drawText(
            QRectF(area.left(), area.bottom() + 10, area.width(), 22),
            Qt.AlignmentFlag.AlignCenter,
            f"0 – {duration:.2f} seconds from first sample on this page",
        )
        for col, color in ((4, "#b87966"), (5, "#4b7da7")):
            p.setPen(QPen(QColor(color), 2))
            for a, b in zip(self.rows, self.rows[1:]):
                # Disconnections / pauses should not appear as continuous data.
                if 0 <= b[3] - a[3] <= 0.5:
                    p.drawLine(point(a, col), point(b, col))
            for r in self.rows:
                p.drawEllipse(point(r, col), 1.4, 1.4)


class SessionDetails(QDialog):
    PAGE_SIZE = 200

    def __init__(self, storage, session_id, parent=None):
        super().__init__(parent)
        self.storage, self.session_id = storage, session_id
        self.offset, self.total = 0, 0
        self.setWindowTitle(f"PosturePal · Session {session_id} samples")
        self.resize(1080, 720)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addWidget(
            QLabel(
                "Upper back: coral   ·   Lower back: blue   ·   Chart shows the current page only"
            )
        )
        self.chart = AngleChart()
        layout.addWidget(self.chart)
        self.table = QTableWidget(0, 18)
        self.table.setHorizontalHeaderLabels(
            [
                "Received (local time)",
                "Sequence (host counter for BLE)",
                "Device time (ms)",
                "Host monotonic (s)",
                "Upper (°)",
                "Lower (°)",
                "Upper state",
                "Lower state",
                "Battery (%)",
                "Device status",
                "Upper threshold (°)",
                "Lower threshold (°)",
                "Dwell (ms)",
                "Upper baseline (°)",
                "Lower baseline (°)",
                "Alert requested (not measured)",
                "Upper recovery (°)",
                "Lower recovery (°)",
            ]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.table, 1)
        controls = QHBoxLayout()
        self.previous = QPushButton("Previous 200")
        self.previous.clicked.connect(lambda: self.move(-self.PAGE_SIZE))
        controls.addWidget(self.previous)
        self.next = QPushButton("Next 200")
        self.next.clicked.connect(lambda: self.move(self.PAGE_SIZE))
        controls.addWidget(self.next)
        refresh = QPushButton("Refresh samples")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        controls.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        controls.addWidget(close)
        layout.addLayout(controls)
        self.refresh()

    def refresh(self):
        try:
            self.storage.flush()
            self.total = self.storage.sample_count(self.session_id)
            self.show_page()
        except Exception as exc:
            self.summary.setText(f"Could not load samples: {exc}")

    def move(self, amount):
        self.offset = max(
            0,
            min(
                max(0, ((self.total - 1) // self.PAGE_SIZE) * self.PAGE_SIZE),
                self.offset + amount,
            ),
        )
        try:
            self.show_page()
        except Exception as exc:
            self.summary.setText(f"Could not load samples: {exc}")

    def show_page(self):
        rows = self.storage.sample_page(self.session_id, self.offset, self.PAGE_SIZE)
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate(row):
                if j == 0:
                    value = (
                        datetime.fromisoformat(value)
                        .astimezone()
                        .strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    )
                elif value is None:
                    value = "—"
                elif isinstance(value, float):
                    value = f"{value:.3f}"
                self.table.setItem(i, j, QTableWidgetItem(str(value)))
        self.chart.rows = rows
        self.chart.update()
        if self.total:
            self.summary.setText(
                f"Session {self.session_id} · Samples {self.offset + 1}–{self.offset + len(rows)} of {self.total}. "
                "Angles are baseline-relative. Settings and baseline columns reflect each sample’s capture time."
            )
        else:
            self.summary.setText(
                "No individual samples were recorded for this session. Older sessions contain summaries only. "
                "New readings will appear after recording starts and you refresh."
            )
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(self.offset + len(rows) < self.total)
