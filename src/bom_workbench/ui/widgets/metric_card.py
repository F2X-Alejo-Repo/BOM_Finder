"""Simple KPI-style display card."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout


class MetricCard(QFrame):
    """A reusable metric card with a title, value, and optional subtitle."""

    def __init__(
        self,
        title: str = "",
        value: str = "",
        subtitle: str = "",
        parent: Optional[QFrame] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        self._title = QLabel(title, self)
        self._value = QLabel(value, self)
        self._subtitle = QLabel(subtitle, self)

        self._title.setObjectName("metricCardTitle")
        self._value.setObjectName("metricCardValue")
        self._subtitle.setObjectName("metricCardSubtitle")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)
        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._subtitle)

        self.setStyleSheet(
            "QFrame#metricCard {"
            "background:#ffffff;"
            "border:1px solid #dbe4f0;"
            "border-radius:12px;"
            "}"
            "QLabel#metricCardTitle {color:#64748b;font-size:12px;font-weight:600;}"
            "QLabel#metricCardValue {color:#0f172a;font-size:24px;font-weight:700;}"
            "QLabel#metricCardSubtitle {color:#475569;font-size:12px;}"
        )

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle.setText(subtitle)

    def set_metric(self, title: str, value: str, subtitle: str = "") -> None:
        self.set_title(title)
        self.set_value(value)
        self.set_subtitle(subtitle)
