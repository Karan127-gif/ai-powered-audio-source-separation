"""
auth_window.py  –  Animated login page
• Right panel: live animated waveform bars (audio visualizer effect)
• Form panel:  fades + slides in on startup via QPropertyAnimation
• Background:  subtle pulsing glow rings
"""
import random
import math

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTabWidget, QScrollArea, QFrame,
    QGraphicsOpacityEffect
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, QPoint
)
from PyQt6.QtGui import (
    QFont, QPainter, QColor, QPen, QBrush,
    QLinearGradient, QRadialGradient
)

from config import (
    COLOR_BG_DARK, COLOR_BG_SURFACE, COLOR_BG_CARD,
    COLOR_BORDER, COLOR_TEXT, COLOR_TEXT_MUTED,
    COLOR_ACCENT, COLOR_ACCENT_SOFT, COLOR_CORAL, COLOR_GREEN
)
from database import Database

# ── Stylesheet ─────────────────────────────────────────────────────────────────
STYLE = f"""
QMainWindow, QWidget {{
    background: {COLOR_BG_DARK};
    color: {COLOR_TEXT};
    font-family: 'Inter', 'Segoe UI', sans-serif;
}}
QLineEdit {{
    background: {COLOR_BG_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 9px;
    color: {COLOR_TEXT};
    padding: 12px 14px;
    font-size: 13px;
    font-family: 'Inter', 'Segoe UI';
}}
QLineEdit:focus {{
    border: 1px solid {COLOR_ACCENT};
    background: #13132A;
}}
QLineEdit::placeholder {{ color: {COLOR_TEXT_MUTED}; }}
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar::tab {{
    background: transparent;
    color: {COLOR_TEXT_MUTED};
    padding: 10px 32px;
    font-family: 'Inter';
    font-size: 12px;
    font-weight: 500;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {COLOR_ACCENT};
    border-bottom: 2px solid {COLOR_ACCENT};
    font-weight: 700;
}}
QScrollBar:vertical {{
    background: transparent; width: 5px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{ background: {COLOR_BORDER}; border-radius: 3px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


# ── Animated waveform canvas ──────────────────────────────────────────────────
class WaveCanvas(QWidget):
    """Draws animated audio-waveform bars that pulse over time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._phase  = 0.0
        self._bars   = 48
        self._heights = [random.uniform(0.05, 0.95) for _ in range(self._bars)]
        self._targets = list(self._heights)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)   # 25 fps

    def _tick(self):
        self._phase += 0.04
        # Smoothly chase target heights
        for i in range(self._bars):
            diff = self._targets[i] - self._heights[i]
            self._heights[i] += diff * 0.12
        # Occasionally randomise a bar
        if random.random() < 0.35:
            idx = random.randint(0, self._bars - 1)
            self._targets[idx] = random.uniform(0.04, 0.92)
        # Slow sine ripple
        for i in range(self._bars):
            sin_push = math.sin(self._phase + i * 0.22) * 0.12
            self._heights[i] = max(0.03, min(0.98, self._heights[i] + sin_push * 0.04))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(9, 9, 14))  # COLOR_BG_DARK

        w = self.width()
        h = self.height()
        cx = w // 2
        cy = h // 2

        # --- Background glow rings -----------------------------------------
        for r, alpha in [(220, 12), (160, 18), (100, 24), (60, 30)]:
            grad = QRadialGradient(cx, cy, r)
            grad.setColorAt(0.0, QColor(124, 92, 240, alpha))
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

        # --- Waveform bars ------------------------------------------------
        bar_w = max(4, w // self._bars - 3)
        gap   = (w - self._bars * bar_w) // (self._bars + 1)
        x     = gap

        for i, ht in enumerate(self._heights):
            bar_h = int(ht * h * 0.72)
            y     = cy - bar_h // 2

            # Colour gradient: violet → cyan based on position
            t = i / self._bars
            r = int(80  + (124 - 80)  * t)
            g = int(20  + (200 - 20)  * (1 - abs(t - 0.5) * 2))
            b = int(200 + (240 - 200) * (1 - t))
            alpha = int(100 + 130 * ht)

            grad = QLinearGradient(x, y, x, y + bar_h)
            grad.setColorAt(0.0, QColor(r, g, b, min(255, alpha + 60)))
            grad.setColorAt(0.5, QColor(r, g, b, alpha))
            grad.setColorAt(1.0, QColor(r, g, b, min(255, alpha + 60)))

            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            radius = bar_w // 2
            p.drawRoundedRect(x, y, bar_w, bar_h, radius, radius)

            x += bar_w + gap

        # --- "AI Audio Separator" label at bottom -------------------------
        p.setPen(QColor(255, 255, 255, 28))
        p.setFont(QFont("Inter", 11))
        p.drawText(self.rect().adjusted(0, 0, 0, -16),
                   Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                   "AI Audio Separator Pro")

        p.end()

    def stop(self):
        self._timer.stop()


# ── Auth window ────────────────────────────────────────────────────────────────
class AuthWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.db = Database()
        self.setWindowTitle("Audio Separator Pro")
        self.setStyleSheet(STYLE)
        self.setMinimumSize(900, 600)
        self._build_ui()
        self._animate_form_in()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Left brand panel ──────────────────────────────────────────────────
        brand = QWidget()
        brand.setFixedWidth(360)
        brand.setStyleSheet(f"""
            background: {COLOR_BG_SURFACE};
            border-right: 1px solid {COLOR_BORDER};
        """)
        blayout = QVBoxLayout(brand)
        blayout.setContentsMargins(44, 70, 44, 40)
        blayout.setSpacing(0)

        # Animated logo symbol
        logo = QLabel("◎")
        logo.setFont(QFont("Inter", 52, QFont.Weight.Bold))
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(f"color: {COLOR_ACCENT};")
        blayout.addWidget(logo)

        # Subtle logo pulse via stylesheet cycling
        self._logo_lbl = logo
        self._logo_tick = 0
        logo_timer = QTimer(self)
        logo_timer.timeout.connect(self._pulse_logo)
        logo_timer.start(700)

        blayout.addSpacing(18)

        title = QLabel("Audio Separator Pro")
        title.setFont(QFont("Inter", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        blayout.addWidget(title)

        blayout.addSpacing(6)

        tagline = QLabel("AI-powered stem separation")
        tagline.setFont(QFont("Inter", 11))
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        blayout.addWidget(tagline)

        blayout.addSpacing(28)

        chips = [
            ("✦", COLOR_ACCENT,       "Vocals, Drums, Bass & More"),
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
            blayout.addWidget(row_w)
            blayout.addSpacing(7)

        blayout.addStretch()

        back_btn = QPushButton("← Back to Home")
        back_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {COLOR_TEXT_MUTED};
                border: none; font-size: 11px; font-family: 'Inter';
            }}
            QPushButton:hover {{ color: {COLOR_ACCENT}; }}
        """)
        back_btn.clicked.connect(self.controller.show_landing)
        blayout.addWidget(back_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(brand)

        # ── Right: animated waveform background + form overlay ────────────────
        right_container = QWidget()
        right_container.setStyleSheet(f"background: {COLOR_BG_DARK};")
        right_stack = QHBoxLayout(right_container)
        right_stack.setContentsMargins(0, 0, 0, 0)
        right_stack.setSpacing(0)

        # Waveform canvas fills the whole right panel
        self._wave = WaveCanvas()
        right_stack.addWidget(self._wave)

        # Form overlaid in absolute position (we use a stacked approach)
        # Actually use a centered scroll area on top:
        self._form_scroll = QScrollArea(right_container)
        self._form_scroll.setWidgetResizable(True)
        self._form_scroll.setStyleSheet("background: transparent; border: none;")
        self._form_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        form_host = QWidget()
        form_host.setStyleSheet("background: transparent;")
        fhl = QVBoxLayout(form_host)
        fhl.setContentsMargins(0, 0, 0, 0)
        fhl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Glass card
        self._container = QFrame()
        self._container.setFixedWidth(440)
        self._container.setStyleSheet(f"""
            QFrame {{
                background: rgba(13,13,26,0.92);
                border-radius: 20px;
                border: 1px solid rgba(124,92,240,0.25);
            }}
        """)
        cl = QVBoxLayout(self._container)
        cl.setContentsMargins(40, 32, 40, 40)
        cl.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._make_login_tab(),    "Sign In")
        self.tabs.addTab(self._make_register_tab(), "Create Account")
        cl.addWidget(self.tabs)

        fhl.addWidget(self._container, alignment=Qt.AlignmentFlag.AlignCenter)
        self._form_scroll.setWidget(form_host)

        # Position the scroll over the wave canvas
        outer.addWidget(right_container)

        # We need the form to float over the wave canvas.
        # Reuse a direct overlay via geometry — set after show.
        self._form_scroll.setParent(right_container)
        self._form_scroll.raise_()
        # Will be resized in resizeEvent

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep form_scroll overlaid exactly on the right container
        if hasattr(self, '_form_scroll') and hasattr(self, '_wave'):
            rect = self._wave.geometry()
            parent_geo = self._wave.parent()
            if parent_geo:
                # The right_container fills remaining width
                brand_w = 360
                w = self.width() - brand_w
                h = self.height()
                self._wave.setGeometry(0, 0, w, h)
                self._form_scroll.setGeometry(0, 0, w, h)

    # ── Logo pulse ─────────────────────────────────────────────────────────────
    def _pulse_logo(self):
        symbols = ["◎", "◉", "◎"]
        self._logo_tick = (self._logo_tick + 1) % len(symbols)
        s = symbols[self._logo_tick]
        alphas = [255, 200, 255]
        a = alphas[self._logo_tick]
        self._logo_lbl.setText(s)
        self._logo_lbl.setStyleSheet(
            f"color: rgba(124,92,240,{a}); font-size: 52px; font-weight: bold;"
        )

    # ── Form fade-in ───────────────────────────────────────────────────────────
    def _animate_form_in(self):
        effect = QGraphicsOpacityEffect(self._container)
        self._container.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(900)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._form_anim = anim   # keep reference

    # ── Login tab ─────────────────────────────────────────────────────────────
    def _make_login_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 20, 0, 0)
        l.setSpacing(12)

        self.login_username = QLineEdit()
        self.login_username.setPlaceholderText("Username")
        self.login_username.returnPressed.connect(self._handle_login)

        self.login_password = QLineEdit()
        self.login_password.setPlaceholderText("Password")
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_password.returnPressed.connect(self._handle_login)

        self.login_msg = QLabel("")
        self.login_msg.setFont(QFont("Inter", 10))
        self.login_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.login_msg.setWordWrap(True)

        login_btn = QPushButton("Sign In →")
        login_btn.setFixedHeight(48)
        login_btn.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        login_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLOR_ACCENT};
                color: white; border-radius: 10px; border: none;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover {{ background: {COLOR_ACCENT_SOFT}; color: #0F0F18; }}
            QPushButton:pressed {{ background: #5a3fcc; }}
        """)
        login_btn.clicked.connect(self._handle_login)

        for widget in [self.login_username, self.login_password,
                       login_btn, self.login_msg]:
            l.addWidget(widget)
        l.addStretch()
        return w

    def _handle_login(self):
        username = self.login_username.text().strip()
        password = self.login_password.text()
        if not username or not password:
            self.login_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.login_msg.setText("Please enter username and password.")
            return
        user, msg = self.db.login(username, password)
        if user:
            self.login_msg.setStyleSheet(f"color: {COLOR_GREEN};")
            self.login_msg.setText("✓ Login successful!")
            self.controller.on_login_success(user)
        else:
            self.login_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.login_msg.setText(msg)

    # ── Register tab ──────────────────────────────────────────────────────────
    def _make_register_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 20, 0, 0)
        l.setSpacing(12)

        self.reg_username = QLineEdit()
        self.reg_username.setPlaceholderText("Username")

        self.reg_email = QLineEdit()
        self.reg_email.setPlaceholderText("Email (optional)")

        self.reg_password = QLineEdit()
        self.reg_password.setPlaceholderText("Password")
        self.reg_password.setEchoMode(QLineEdit.EchoMode.Password)

        self.reg_confirm = QLineEdit()
        self.reg_confirm.setPlaceholderText("Confirm Password")
        self.reg_confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.reg_confirm.returnPressed.connect(self._handle_register)

        self.reg_msg = QLabel("")
        self.reg_msg.setFont(QFont("Inter", 10))
        self.reg_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reg_msg.setWordWrap(True)

        reg_btn = QPushButton("Create Account")
        reg_btn.setFixedHeight(48)
        reg_btn.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        reg_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLOR_ACCENT};
                border: 1.5px solid {COLOR_ACCENT};
                border-radius: 10px;
            }}
            QPushButton:hover {{ background: rgba(124,92,240,0.15); }}
        """)
        reg_btn.clicked.connect(self._handle_register)

        for widget in [self.reg_username, self.reg_email,
                       self.reg_password, self.reg_confirm,
                       reg_btn, self.reg_msg]:
            l.addWidget(widget)

        bonus = QLabel("✦  5 free credits on registration")
        bonus.setFont(QFont("Inter", 10))
        bonus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bonus.setStyleSheet(f"""
            color: {COLOR_ACCENT};
            background: rgba(124,92,240,0.08);
            border: 1px solid rgba(124,92,240,0.20);
            border-radius: 6px; padding: 5px 0;
        """)
        l.addWidget(bonus)
        l.addStretch()
        return w

    def _handle_register(self):
        username = self.reg_username.text().strip()
        email    = self.reg_email.text().strip()
        password = self.reg_password.text()
        confirm  = self.reg_confirm.text()

        if not username or not password:
            self.reg_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.reg_msg.setText("Username and password are required.")
            return
        if password != confirm:
            self.reg_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.reg_msg.setText("Passwords do not match.")
            return
        if len(password) < 4:
            self.reg_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.reg_msg.setText("Password must be at least 4 characters.")
            return

        ok, msg = self.db.register_user(username, password, email)
        if ok:
            self.reg_msg.setStyleSheet(f"color: {COLOR_GREEN};")
            self.reg_msg.setText("✓ Account created! You can now sign in.")
            self.tabs.setCurrentIndex(0)
            self.login_username.setText(username)
        else:
            self.reg_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.reg_msg.setText(msg)

    def closeEvent(self, event):
        if hasattr(self, '_wave'):
            self._wave.stop()
        super().closeEvent(event)
