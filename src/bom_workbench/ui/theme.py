"""Theme tokens and stylesheet helpers for the BOM Workbench shell."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PySide6.QtWidgets import QApplication, QWidget

COLORS: Final[dict[str, str]] = {
    "bg_primary": "#0b1020",
    "bg_secondary": "#11192d",
    "bg_tertiary": "#1a2640",
    "bg_surface": "#151e34",
    "text_primary": "#f7f9ff",
    "text_secondary": "#98a5c6",
    "text_disabled": "#65708c",
    "accent_primary": "#4b7fff",
    "accent_hover": "#6ee0ff",
    "accent_pressed": "#385ecc",
    "status_success": "#56c89a",
    "status_warning": "#f2c55c",
    "status_error": "#f0839a",
    "status_info": "#78c9ff",
    "border_subtle": "#24314e",
    "border_default": "#2a3858",
    "border_focus": "#6dd7ff",
}

TYPOGRAPHY: Final[dict[str, object]] = {
    "font_family": '"Segoe UI Variable Text", "Segoe UI", "Inter", sans-serif',
    "font_size_xs": 11,
    "font_size_sm": 12,
    "font_size_md": 13,
    "font_size_lg": 16,
    "font_size_xl": 20,
    "font_size_xxl": 26,
    "font_weight_normal": 400,
    "font_weight_medium": 600,
    "font_weight_bold": 700,
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
    color: {COLORS["text_primary"]};
    font-family: {TYPOGRAPHY["font_family"]};
    font-size: {TYPOGRAPHY["font_size_md"]}pt;
}}

QMainWindow {{
    background-color: {COLORS["bg_primary"]};
}}

QFrame#AppBar {{
    background-color: {COLORS["bg_secondary"]};
    border-bottom: 1px solid {COLORS["border_subtle"]};
}}

QFrame#NavRail,
QFrame#InspectorPanel,
QFrame#PageHero,
QFrame#InfoCard,
QGroupBox,
QFrame#ImportIntakeCard,
QFrame#rowInspector,
QStatusBar,
QFrame#InspectorPlaceholder {{
    background-color: {COLORS["bg_secondary"]};
    border: 1px solid {COLORS["border_subtle"]};
    border-radius: 18px;
}}

QLabel {{
    color: {COLORS["text_primary"]};
}}

QLabel#AppTitle,
QLabel#pageHeading,
QLabel#inspectorHeading {{
    font-size: {TYPOGRAPHY["font_size_xxl"]}pt;
    font-weight: {TYPOGRAPHY["font_weight_bold"]};
}}

QLabel[muted="true"] {{
    color: {COLORS["text_secondary"]};
}}

QPushButton,
QToolButton {{
    background-color: {COLORS["bg_surface"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border_default"]};
    border-radius: 14px;
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
    border-radius: 14px;
    padding: {SPACING["sm"]}px;
    selection-background-color: {COLORS["accent_primary"]};
}}

QTableView,
QTreeView,
QListView,
QTableWidget {{
    background-color: {COLORS["bg_secondary"]};
    alternate-background-color: {COLORS["bg_surface"]};
    color: {COLORS["text_primary"]};
    gridline-color: {COLORS["border_subtle"]};
    selection-background-color: {COLORS["accent_primary"]};
    selection-color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border_subtle"]};
    border-radius: 18px;
}}

QProgressBar {{
    background-color: {COLORS["bg_surface"]};
    border: 1px solid {COLORS["border_default"]};
    border-radius: 10px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {COLORS["accent_primary"]};
    border-radius: 10px;
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
