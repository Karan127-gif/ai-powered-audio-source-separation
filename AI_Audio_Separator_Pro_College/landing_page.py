import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from config import (
    COLOR_BG_DARK, COLOR_BG_SURFACE, COLOR_BG_CARD,
    COLOR_BORDER, COLOR_TEXT, COLOR_TEXT_MUTED,
    COLOR_ACCENT, COLOR_ACCENT_SOFT,
    APP_NAME, APP_VERSION, AUDIO_VISUAL_PATH
)
from database import Database
from auth_window import WaveCanvas

STYLE = f"""
QMainWindow, QWidget {{
    background-color: {COLOR_BG_DARK};
    color: {COLOR_TEXT};
    font-family: 'Inter', 'Segoe UI', sans-serif;
}}
QScrollBar:vertical {{
    background: transparent; width: 5px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_BORDER}; border-radius: 3px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


class LandingPage(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.db = Database()
        self.setWindowTitle(APP_NAME)
        self.setStyleSheet(STYLE)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left brand panel (mirrors auth_window style) ───────────────────────
        left = QWidget()
        left.setFixedWidth(420)
        left.setStyleSheet(f"""
            background: {COLOR_BG_SURFACE};
            border-right: 1px solid {COLOR_BORDER};
        """)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(50, 80, 50, 50)
        left_layout.setSpacing(0)

        # Logo symbol
        logo_lbl = QLabel("◎")
        logo_lbl.setFont(QFont("Inter", 60, QFont.Weight.Bold))
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_lbl.setStyleSheet(f"color: {COLOR_ACCENT};")
        left_layout.addWidget(logo_lbl)

        left_layout.addSpacing(16)

        title = QLabel("AI Audio\nSeparator Pro")
        title.setFont(QFont("Inter", 28, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.5px; line-height: 1.1;")
        left_layout.addWidget(title)

        left_layout.addSpacing(10)

        tagline = QLabel("Separate vocals, drums, bass & more\nwith AI-powered precision.")
        tagline.setFont(QFont("Inter", 11))
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        tagline.setWordWrap(True)
        left_layout.addWidget(tagline)

        left_layout.addSpacing(36)

        # Feature chips (matching auth_window style)
        chips = [
            ("✦", COLOR_ACCENT,       "AI Stem Separation"),
            ("✦", COLOR_ACCENT_SOFT,  "4 Stems in Seconds"),
            ("✦", "#6366F1",          "High-Quality WAV Output"),
        ]
        for icon, color, text in chips:
            row = QHBoxLayout()
            ic = QLabel(icon)
            ic.setFont(QFont("Inter", 10))
            ic.setStyleSheet(f"color: {color};")
            ic.setFixedWidth(20)
            tx = QLabel(text)
            tx.setFont(QFont("Inter", 11))
            tx.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            row.addWidget(ic)
            row.addWidget(tx)
            row.addStretch()
            row_w = QWidget()
            row_w.setStyleSheet("background: transparent;")
            row_w.setLayout(row)
            left_layout.addWidget(row_w)
            left_layout.addSpacing(6)

        left_layout.addSpacing(32)

        # Get Started button
        login_btn = QPushButton("Get Started →")
        login_btn.setFixedHeight(52)
        login_btn.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        login_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLOR_ACCENT};
                color: white; border-radius: 12px; border: none;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover {{ background: {COLOR_ACCENT_SOFT}; color: #0F0F18; }}
            QPushButton:pressed {{ background: #5a3fcc; }}
        """)
        login_btn.clicked.connect(self.controller.show_auth)
        left_layout.addWidget(login_btn)

        left_layout.addStretch()

        version_lbl = QLabel(f"v{APP_VERSION}  ·  © 2026 {APP_NAME}")
        version_lbl.setFont(QFont("Inter", 9))
        version_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        left_layout.addWidget(version_lbl)

        root.addWidget(left)

        # ── Right panel: animated waveform ─────────────────────────────────────
        right = QWidget()
        right.setStyleSheet(f"background: {COLOR_BG_DARK};")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Live animated waveform canvas
        self._wave = WaveCanvas()
        right_layout.addWidget(self._wave)

        # Overlay: stat bar at bottom of image
        overlay = QWidget()
        overlay.setFixedHeight(80)
        overlay.setStyleSheet(f"""
            background: rgba(9,9,14,0.85);
            border-top: 1px solid {COLOR_BORDER};
        """)
        ol = QHBoxLayout(overlay)
        ol.setContentsMargins(40, 0, 40, 0)
        ol.setSpacing(0)

        for stat, label in [("1.2K+", "Conversions"), ("500+", "Active Users"),
                             ("4 Stems", "Per Song"), ("HQ WAV", "Output")]:
            col = QVBoxLayout()
            num = QLabel(stat)
            num.setFont(QFont("Inter", 18, QFont.Weight.Bold))
            num.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl2 = QLabel(label)
            lbl2.setFont(QFont("Inter", 9))
            lbl2.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            lbl2.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(num)
            col.addWidget(lbl2)
            ol.addLayout(col)
            if label != "Output":
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setFixedWidth(1)
                sep.setStyleSheet(f"background: {COLOR_BORDER};")
                ol.addWidget(sep)

        right_layout.addWidget(overlay)
        root.addWidget(right)

    def closeEvent(self, event):
        """Stop the waveform animation timer to prevent background timer leaks."""
        if hasattr(self, '_wave'):
            try:
                self._wave.stop()
            except Exception:
                pass
        super().closeEvent(event)
