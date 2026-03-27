"""Theme tokens and stylesheet helpers for the BOM Workbench shell."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PySide6.QtWidgets import QApplication, QWidget

COLORS: Final[dict[str, str]] = {
    "bg_primary": "#1a1a2e",
    "bg_secondary": "#16213e",
    "bg_tertiary": "#0f3460",
    "bg_surface": "#1e2746",
    "text_primary": "#e8e8e8",
    "text_secondary": "#a0a0b0",
    "text_disabled": "#606070",
    "accent_primary": "#4a9eff",
    "accent_hover": "#6bb3ff",
    "accent_pressed": "#3580d4",
    "status_success": "#4ade80",
    "status_warning": "#fbbf24",
    "status_error": "#f87171",
    "status_info": "#60a5fa",
    "border_subtle": "#2a2a4a",
    "border_default": "#3a3a5a",
    "border_focus": "#4a9eff",
}

TYPOGRAPHY: Final[dict[str, object]] = {
    "font_family": "Segoe UI, Inter, -apple-system, sans-serif",
    "font_size_xs": 11,
    "font_size_sm": 12,
    "font_size_md": 13,
    "font_size_lg": 15,
    "font_size_xl": 18,
    "font_size_xxl": 22,
    "font_weight_normal": 400,
    "font_weight_medium": 500,
    "font_weight_bold": 600,
}

SPACING: Final[dict[str, int]] = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
}

_THEME_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "resources" / "themes" / "dark.qss"
)


def _build_fallback_stylesheet() -> str:
    """Generate a readable dark stylesheet when the resource file is missing."""
    return f"""
QWidget {{
    background-color: {COLORS["bg_primary"]};
    color: {COLORS["text_primary"]};
    font-family: {TYPOGRAPHY["font_family"]};
    font-size: {TYPOGRAPHY["font_size_md"]}pt;
}}

QMainWindow, QFrame {{
    background-color: {COLORS["bg_primary"]};
}}

QFrame#AppBar,
QFrame#NavRail,
QFrame#InspectorPanel,
QStatusBar {{
    background-color: {COLORS["bg_secondary"]};
    border: 1px solid {COLORS["border_subtle"]};
}}

QLabel {{
    color: {COLORS["text_primary"]};
}}

QLabel[muted="true"] {{
    color: {COLORS["text_secondary"]};
}}

QPushButton,
QToolButton {{
    background-color: {COLORS["bg_surface"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border_default"]};
    border-radius: 8px;
    padding: {SPACING["sm"]}px {SPACING["md"]}px;
}}

QPushButton:hover,
QToolButton:hover {{
    background-color: {COLORS["bg_tertiary"]};
    border-color: {COLORS["accent_hover"]};
}}

QPushButton:checked,
QToolButton:checked {{
    background-color: {COLORS["accent_primary"]};
    border-color: {COLORS["accent_primary"]};
}}

QLineEdit,
QTextEdit,
QPlainTextEdit,
QSpinBox,
QComboBox {{
    background-color: {COLORS["bg_surface"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border_default"]};
    border-radius: 8px;
    padding: {SPACING["sm"]}px;
    selection-background-color: {COLORS["accent_primary"]};
}}

QTableView,
QTreeView,
QListView {{
    background-color: {COLORS["bg_secondary"]};
    alternate-background-color: {COLORS["bg_surface"]};
    color: {COLORS["text_primary"]};
    gridline-color: {COLORS["border_subtle"]};
    selection-background-color: {COLORS["accent_primary"]};
    selection-color: {COLORS["text_primary"]};
}}

QProgressBar {{
    background-color: {COLORS["bg_surface"]};
    border: 1px solid {COLORS["border_default"]};
    border-radius: 8px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {COLORS["accent_primary"]};
    border-radius: 8px;
}}
""".strip()


def load_stylesheet() -> str:
    """Load the preferred dark theme stylesheet or a generated fallback."""
    if _THEME_PATH.is_file():
        return _THEME_PATH.read_text(encoding="utf-8")
    return _build_fallback_stylesheet()


def apply_theme(target: QApplication | QWidget) -> str:
    """Apply the shell theme to a Qt application or widget tree."""
    stylesheet = load_stylesheet()
    target.setStyleSheet(stylesheet)
    return stylesheet
