"""
payment_window.py  –  Real-world payment flow (crash-safe rewrite)
Uses QFrame cards (not QPushButton with nested layouts) to avoid Qt GC issues.
Steps: 1. Choose Package → 2. Choose Method → 3. Enter Details → 4. Processing → 5. Done
"""
import random
import string
import math

import re

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QWidget, QStackedWidget, QLineEdit,
    QSizePolicy, QProgressBar, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QColor, QLinearGradient, QBrush, QPen

from config import (
    COLOR_BG_DARK, COLOR_BG_SURFACE, COLOR_BG_CARD,
    COLOR_BORDER, COLOR_TEXT, COLOR_TEXT_MUTED,
    COLOR_ACCENT, COLOR_ACCENT_SOFT,
)
from database import Database


# ── Mini waveform widget (same feel as auth page) ──────────────────────────────
class MiniWave(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self._phase = 0.0
        self._bars = 36
        self._heights = [random.uniform(0.1, 0.9) for _ in range(self._bars)]
        self._targets = list(self._heights)
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(50)

    def _tick(self):
        self._phase += 0.06
        for i in range(self._bars):
            self._heights[i] += (self._targets[i] - self._heights[i]) * 0.14
        if random.random() < 0.4:
            self._targets[random.randint(0, self._bars - 1)] = random.uniform(0.05, 0.95)
        for i in range(self._bars):
            push = math.sin(self._phase + i * 0.25) * 0.05
            self._heights[i] = max(0.04, min(0.96, self._heights[i] + push))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(9, 9, 14, 0))
        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2
        bar_w = max(3, w // self._bars - 2)
        gap = (w - self._bars * bar_w) // (self._bars + 1)
        x = gap
        for i, ht in enumerate(self._heights):
            bh = int(ht * h * 0.85)
            y = cy - bh // 2
            t = i / self._bars
            r = int(80 + (124 - 80) * t)
            g = int(20 + 180 * (1 - abs(t - 0.5) * 2))
            b = int(200 + 40 * (1 - t))
            alpha = int(90 + 130 * ht)
            grad = QLinearGradient(x, y, x, y + bh)
            grad.setColorAt(0.0, QColor(r, g, b, min(255, alpha + 50)))
            grad.setColorAt(1.0, QColor(r, g, b, min(255, alpha + 50)))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            rr = bar_w // 2
            p.drawRoundedRect(x, y, bar_w, bh, rr, rr)
            x += bar_w + gap
        p.end()


# ── Clickable card frame ──────────────────────────────────────────────────────
CARD_NORMAL = f"""
    QFrame {{
        background: #141421;
        border: 1px solid rgba(255,255,255,0.05);
        border-radius: 10px;
    }}
"""
CARD_HOVER = f"""
    QFrame {{
        background: rgba(124,92,240,0.07);
        border: 1px solid rgba(124,92,240,0.35);
        border-radius: 10px;
    }}
"""
CARD_SELECTED = f"""
    QFrame {{
        background: rgba(124,92,240,0.14);
        border: 1px solid #7C5CF0;
        border-radius: 10px;
    }}
"""

class ClickableCard(QFrame):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected = False
        self.setStyleSheet(CARD_NORMAL)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def setSelected(self, v: bool):
        self._selected = v
        self.setStyleSheet(CARD_SELECTED if v else CARD_NORMAL)

    def mousePressEvent(self, e):
        self.clicked.emit()

    def enterEvent(self, e):
        if not self._selected:
            self.setStyleSheet(CARD_HOVER)

    def leaveEvent(self, e):
        if not self._selected:
            self.setStyleSheet(CARD_NORMAL)


# ── Main dialog ────────────────────────────────────────────────────────────────
def _style():
    return f"""
        QDialog, QWidget {{
            background: {COLOR_BG_DARK};
            color: {COLOR_TEXT};
            font-family: 'Inter', 'Segoe UI', sans-serif;
        }}
        QLineEdit {{
            background: {COLOR_BG_CARD};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: 8px;
            padding: 10px 14px;
            font-size: 13px;
            font-family: 'Inter', 'Segoe UI';
        }}
        QLineEdit:focus {{ border: 1px solid {COLOR_ACCENT}; }}
    """


class PaymentWindow(QDialog):
    credits_added = pyqtSignal(int)

    PACKAGES = [
        (10,  49,   "Starter",   "Perfect for trying out"),
        (25,  99,   "Basic",     "Most popular choice"),
        (60,  199,  "Standard",  "Great value"),
        (150, 399,  "Pro",       "For power users"),
        (400, 899,  "Unlimited", "Best deal — 55% off"),
    ]

    def __init__(self, user, db: Database, parent=None):
        super().__init__(parent)
        self.user = user
        self.db   = db
        self._credits = None
        self._price   = None
        self._name    = None
        self._method  = None
        self._pkg_cards   = []
        self._meth_cards  = []

        self.setWindowTitle("Recharge Credits")
        self.setStyleSheet(_style())
        self.setMinimumSize(540, 580)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        hdr = QWidget()
        hdr.setFixedHeight(54)
        hdr.setStyleSheet(f"background: {COLOR_BG_SURFACE}; border-bottom: 1px solid {COLOR_BORDER};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(24, 0, 24, 0)
        self._title_lbl = QLabel("Select a Plan")
        self._title_lbl.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        self._step_lbl = QLabel()
        self._step_lbl.setFont(QFont("Inter", 10))
        self._step_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        hl.addWidget(self._title_lbl)
        hl.addStretch()
        hl.addWidget(self._step_lbl)
        root.addWidget(hdr)

        # Stack
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_packages())
        self.stack.addWidget(self._page_method())
        self.stack.addWidget(self._page_details())
        self.stack.addWidget(self._page_processing())
        self.stack.addWidget(self._page_result())
        root.addWidget(self.stack)

        # Footer nav
        nav = QWidget()
        nav.setFixedHeight(62)
        nav.setStyleSheet(f"background: {COLOR_BG_SURFACE}; border-top: 1px solid {COLOR_BORDER};")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(24, 0, 24, 0)

        self._back_btn = QPushButton("← Back")
        self._back_btn.setFixedHeight(36)
        self._back_btn.setFont(QFont("Inter", 11))
        self._back_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {COLOR_TEXT_MUTED};
                border: 1px solid {COLOR_BORDER}; border-radius: 8px; padding: 0 18px; }}
            QPushButton:hover {{ color: {COLOR_TEXT}; border-color: {COLOR_ACCENT}; background: rgba(124,92,240,0.07); }}
        """)
        self._back_btn.clicked.connect(self._go_back)
        self._back_btn.setVisible(False)

        self._next_btn = QPushButton("Next →")
        self._next_btn.setFixedHeight(36)
        self._next_btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self._next_btn.setStyleSheet(f"""
            QPushButton {{ background: {COLOR_ACCENT}; color: white; border-radius: 8px; border: none; padding: 0 26px; }}
            QPushButton:hover {{ background: {COLOR_ACCENT_SOFT}; color: #0F0F18; }}
            QPushButton:disabled {{ background: {COLOR_BG_CARD}; color: {COLOR_TEXT_MUTED}; border: 1px solid {COLOR_BORDER}; }}
        """)
        self._next_btn.setEnabled(False)
        self._next_btn.clicked.connect(self._go_next)

        nl.addWidget(self._back_btn)
        nl.addStretch()
        nl.addWidget(self._next_btn)
        root.addWidget(nav)

        self._goto(0)

    # ── Pages ──────────────────────────────────────────────────────────────────
    def _page_packages(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        l = QVBoxLayout(w)
        l.setContentsMargins(24, 20, 24, 16)
        l.setSpacing(8)

        bal_lbl = QLabel(f"Current balance:  {self.user['credits']} credits")
        bal_lbl.setFont(QFont("Inter", 11))
        bal_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        l.addWidget(bal_lbl)
        l.addSpacing(6)

        for credits, price, name, desc in self.PACKAGES:
            card = ClickableCard()
            card.setFixedHeight(66)
            inner = QHBoxLayout(card)
            inner.setContentsMargins(18, 0, 18, 0)

            # Left side widget
            left_w = QWidget()
            left_w.setStyleSheet("background: transparent;")
            left_l = QVBoxLayout(left_w)
            left_l.setContentsMargins(0, 0, 0, 0)
            left_l.setSpacing(2)
            name_l = QLabel(name)
            name_l.setFont(QFont("Inter", 12, QFont.Weight.Bold))
            name_l.setStyleSheet(f"color: {COLOR_TEXT}; background: transparent;")
            desc_l = QLabel(desc)
            desc_l.setFont(QFont("Inter", 9))
            desc_l.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; background: transparent;")
            left_l.addWidget(name_l)
            left_l.addWidget(desc_l)

            # Right side widget
            right_w = QWidget()
            right_w.setStyleSheet("background: transparent;")
            right_l = QVBoxLayout(right_w)
            right_l.setContentsMargins(0, 0, 0, 0)
            right_l.setSpacing(2)
            right_l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cr_l = QLabel(f"{credits} credits")
            cr_l.setFont(QFont("Inter", 11, QFont.Weight.Bold))
            cr_l.setStyleSheet(f"color: {COLOR_ACCENT_SOFT}; background: transparent;")
            cr_l.setAlignment(Qt.AlignmentFlag.AlignRight)
            pr_l = QLabel(f"₹{price}")
            pr_l.setFont(QFont("Inter", 10))
            pr_l.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; background: transparent;")
            pr_l.setAlignment(Qt.AlignmentFlag.AlignRight)
            right_l.addWidget(cr_l)
            right_l.addWidget(pr_l)

            inner.addWidget(left_w)
            inner.addStretch()
            inner.addWidget(right_w)

            def _on_click(c=card, cr=credits, pr=price, nm=name):
                for cc in self._pkg_cards:
                    cc.setSelected(False)
                c.setSelected(True)
                self._credits = cr
                self._price   = pr
                self._name    = nm
                self._next_btn.setEnabled(True)

            card.clicked.connect(_on_click)
            self._pkg_cards.append(card)
            l.addWidget(card)

        l.addStretch()
        scroll.setWidget(w)
        return scroll

    def _page_method(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(24, 20, 24, 16)
        l.setSpacing(10)

        hd = QLabel("Choose Payment Method")
        hd.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        hd.setStyleSheet(f"color: {COLOR_TEXT};")
        l.addWidget(hd)

        methods = [
            ("upi",        "UPI Payment",          "Google Pay · PhonePe · Paytm · BHIM"),
            ("card",       "Debit / Credit Card",  "Visa · Mastercard · RuPay"),
            ("netbanking", "Net Banking",           "SBI · HDFC · ICICI · Axis · Kotak"),
        ]
        for key, title, sub in methods:
            card = ClickableCard()
            card.setFixedHeight(62)
            inner = QHBoxLayout(card)
            inner.setContentsMargins(18, 0, 18, 0)

            txt_w = QWidget()
            txt_w.setStyleSheet("background: transparent;")
            txt_l = QVBoxLayout(txt_w)
            txt_l.setContentsMargins(0, 0, 0, 0)
            txt_l.setSpacing(2)
            t_lbl = QLabel(title)
            t_lbl.setFont(QFont("Inter", 12, QFont.Weight.Bold))
            t_lbl.setStyleSheet(f"color: {COLOR_TEXT}; background: transparent;")
            s_lbl = QLabel(sub)
            s_lbl.setFont(QFont("Inter", 9))
            s_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; background: transparent;")
            txt_l.addWidget(t_lbl)
            txt_l.addWidget(s_lbl)
            inner.addWidget(txt_w)
            inner.addStretch()

            def _sel(c=card, k=key):
                for cc in self._meth_cards:
                    cc.setSelected(False)
                c.setSelected(True)
                self._method = k
                if self._credits:
                    self._method_summary.setText(
                        f"{self._name}  ·  {self._credits} credits  ·  ₹{self._price}"
                    )
                self._next_btn.setEnabled(True)

            card.clicked.connect(_sel)
            self._meth_cards.append(card)
            l.addWidget(card)

        self._method_summary = QLabel("")
        self._method_summary.setFont(QFont("Inter", 10))
        self._method_summary.setStyleSheet(f"""
            background: rgba(124,92,240,0.08);
            color: {COLOR_ACCENT_SOFT};
            border: 1px solid rgba(124,92,240,0.18);
            border-radius: 8px; padding: 9px 14px;
        """)
        l.addStretch()
        l.addWidget(self._method_summary)
        return w

    def _page_details(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        l = QVBoxLayout(w)
        l.setContentsMargins(24, 20, 24, 20)
        l.setSpacing(12)

        self._detail_hd = QLabel("Payment Details")
        self._detail_hd.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        self._detail_hd.setStyleSheet(f"color: {COLOR_TEXT};")
        l.addWidget(self._detail_hd)

        # UPI
        self._upi_w = QWidget()
        self._upi_w.setStyleSheet("background: transparent;")
        ul = QVBoxLayout(self._upi_w)
        ul.setContentsMargins(0, 0, 0, 0)
        ul.setSpacing(6)
        ul.addWidget(self._field_label("UPI ID"))
        self.upi_input = QLineEdit()
        self.upi_input.setPlaceholderText("yourname@upi  or  9876543210@paytm")
        self.upi_input.setFixedHeight(44)
        self.upi_input.textChanged.connect(self._check_details)
        ul.addWidget(self.upi_input)
        self._upi_err = QLabel("")
        self._upi_err.setFont(QFont("Inter", 9))
        self._upi_err.setStyleSheet("color: #EF4444; background: transparent; padding-left: 2px;")
        self._upi_err.setVisible(False)
        ul.addWidget(self._upi_err)
        l.addWidget(self._upi_w)

        # Card
        self._card_w = QWidget()
        self._card_w.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(self._card_w)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        cl.addWidget(self._field_label("Card Number"))
        self.card_num = QLineEdit()
        self.card_num.setPlaceholderText("1234 5678 9012 3456")
        self.card_num.setFixedHeight(44)
        self.card_num.setMaxLength(19)
        self.card_num.textChanged.connect(self._format_card_number)
        self.card_num.textChanged.connect(self._check_details)
        cl.addWidget(self.card_num)
        self._card_num_err = QLabel("")
        self._card_num_err.setFont(QFont("Inter", 9))
        self._card_num_err.setStyleSheet("color: #EF4444; background: transparent; padding-left: 2px;")
        self._card_num_err.setVisible(False)
        cl.addWidget(self._card_num_err)
        cl.addWidget(self._field_label("Cardholder Name"))
        self.card_name = QLineEdit()
        self.card_name.setPlaceholderText("Full Name on Card")
        self.card_name.setFixedHeight(44)
        self.card_name.textChanged.connect(self._check_details)
        cl.addWidget(self.card_name)

        row_w = QWidget()
        row_w.setStyleSheet("background: transparent;")
        rl = QHBoxLayout(row_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(10)
        exp_w = QWidget()
        exp_w.setStyleSheet("background: transparent;")
        ew = QVBoxLayout(exp_w)
        ew.setContentsMargins(0, 0, 0, 0)
        ew.addWidget(self._field_label("Expiry MM/YY"))
        self.card_exp = QLineEdit()
        self.card_exp.setPlaceholderText("MM/YY")
        self.card_exp.setFixedHeight(44)
        self.card_exp.setMaxLength(5)
        self.card_exp.textChanged.connect(self._format_expiry)
        self.card_exp.textChanged.connect(self._check_details)
        ew.addWidget(self.card_exp)
        self._exp_err = QLabel("")
        self._exp_err.setFont(QFont("Inter", 9))
        self._exp_err.setStyleSheet("color: #EF4444; background: transparent; padding-left: 2px;")
        self._exp_err.setVisible(False)
        ew.addWidget(self._exp_err)
        cvv_w = QWidget()
        cvv_w.setStyleSheet("background: transparent;")
        cw = QVBoxLayout(cvv_w)
        cw.setContentsMargins(0, 0, 0, 0)
        cw.addWidget(self._field_label("CVV"))
        self.card_cvv = QLineEdit()
        self.card_cvv.setPlaceholderText("•••")
        self.card_cvv.setEchoMode(QLineEdit.EchoMode.Password)
        self.card_cvv.setFixedHeight(44)
        self.card_cvv.setMaxLength(4)
        self.card_cvv.textChanged.connect(self._check_details)
        cw.addWidget(self.card_cvv)
        self._cvv_err = QLabel("")
        self._cvv_err.setFont(QFont("Inter", 9))
        self._cvv_err.setStyleSheet("color: #EF4444; background: transparent; padding-left: 2px;")
        self._cvv_err.setVisible(False)
        cw.addWidget(self._cvv_err)
        rl.addWidget(exp_w)
        rl.addWidget(cvv_w)
        cl.addWidget(row_w)
        l.addWidget(self._card_w)

        # Net banking
        self._nb_w = QWidget()
        self._nb_w.setStyleSheet("background: transparent;")
        nl = QVBoxLayout(self._nb_w)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(8)
        nl.addWidget(self._field_label("Select Your Bank"))
        banksrow_w = QWidget()
        banksrow_w.setStyleSheet("background: transparent;")
        br = QHBoxLayout(banksrow_w)
        br.setContentsMargins(0, 0, 0, 0)
        br.setSpacing(8)
        self._bank_btns = []
        for bank in ["SBI", "HDFC", "ICICI", "Axis", "Kotak"]:
            btn = QPushButton(bank)
            btn.setCheckable(True)
            btn.setFixedHeight(36)
            btn.setStyleSheet(f"""
                QPushButton {{ background: {COLOR_BG_CARD}; color: {COLOR_TEXT_MUTED};
                    border: 1px solid {COLOR_BORDER}; border-radius: 8px; font-size: 11px;
                    font-family: 'Inter'; }}
                QPushButton:checked {{ background: rgba(124,92,240,0.14); color: {COLOR_ACCENT_SOFT};
                    border: 1px solid {COLOR_ACCENT}; font-weight: bold; }}
                QPushButton:hover {{ border-color: {COLOR_ACCENT}; color: {COLOR_ACCENT_SOFT}; background: rgba(124,92,240,0.07); }}
            """)
            def _selb(_, b=btn):
                for bb in self._bank_btns:
                    bb.setChecked(bb is b)
                self._check_details()
            btn.clicked.connect(_selb)
            self._bank_btns.append(btn)
            br.addWidget(btn)
        nl.addWidget(banksrow_w)
        l.addWidget(self._nb_w)

        # Security note
        note = QLabel("🔒  Secured · 256-bit SSL · PCI-DSS compliant")
        note.setFont(QFont("Inter", 9))
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        l.addStretch()
        l.addWidget(note)

        scroll.setWidget(w)
        return scroll

    def _field_label(self, text):
        lbl = QLabel(text)
        lbl.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; background: transparent;")
        return lbl

    def _page_processing(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.setSpacing(16)
        l.setContentsMargins(30, 20, 30, 20)

        # Mini waveform animation
        self._mini_wave = MiniWave()
        l.addWidget(self._mini_wave)

        self._proc_lbl = QLabel("Connecting to payment gateway…")
        self._proc_lbl.setFont(QFont("Inter", 12))
        self._proc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._proc_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        l.addWidget(self._proc_lbl)

        self._proc_bar = QProgressBar()
        self._proc_bar.setFixedHeight(5)
        self._proc_bar.setRange(0, 100)
        self._proc_bar.setValue(0)
        self._proc_bar.setTextVisible(False)
        self._proc_bar.setStyleSheet(f"""
            QProgressBar {{ background: {COLOR_BG_CARD}; border-radius: 3px; border: none; }}
            QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {COLOR_ACCENT}, stop:1 #22D3EE); border-radius: 3px; }}
        """)
        l.addWidget(self._proc_bar)

        steps_lbl = QLabel("Do not close this window")
        steps_lbl.setFont(QFont("Inter", 9))
        steps_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        steps_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        l.addWidget(steps_lbl)
        return w

    def _page_result(self):
        w = QWidget()
        l = QVBoxLayout(w)
        l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.setSpacing(14)
        l.setContentsMargins(40, 30, 40, 30)

        self._result_icon = QLabel("✓")
        self._result_icon.setFont(QFont("Inter", 60, QFont.Weight.Bold))
        self._result_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_icon.setStyleSheet("color: #22C55E;")
        l.addWidget(self._result_icon)

        self._result_title = QLabel("Payment Successful!")
        self._result_title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        self._result_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_title.setStyleSheet(f"color: {COLOR_TEXT};")
        l.addWidget(self._result_title)

        self._result_sub = QLabel()
        self._result_sub.setFont(QFont("Inter", 11))
        self._result_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._result_sub.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        l.addWidget(self._result_sub)

        self._txn_lbl = QLabel()
        self._txn_lbl.setFont(QFont("Inter", 9))
        self._txn_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._txn_lbl.setStyleSheet(f"""
            background: {COLOR_BG_CARD}; color: {COLOR_TEXT_MUTED};
            border-radius: 6px; padding: 8px 16px; border: 1px solid {COLOR_BORDER};
        """)
        l.addWidget(self._txn_lbl)

        done_btn = QPushButton("Done ✓")
        done_btn.setFixedHeight(44)
        done_btn.setFixedWidth(150)
        done_btn.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        done_btn.setStyleSheet("""
            QPushButton { background: #22C55E; color: white; border-radius: 10px; border: none; }
            QPushButton:hover { background: #16A34A; }
        """)
        done_btn.clicked.connect(self.accept)
        l.addWidget(done_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        return w

    # ── Navigation ─────────────────────────────────────────────────────────────
    _TITLES = ["Select a Plan", "Payment Method", "Payment Details", "Processing…", "Complete"]
    _STEPS  = ["Step 1 of 3", "Step 2 of 3", "Step 3 of 3", "", ""]

    def _goto(self, idx):
        self.stack.setCurrentIndex(idx)
        self._title_lbl.setText(self._TITLES[idx])
        self._step_lbl.setText(self._STEPS[idx])
        self._back_btn.setVisible(0 < idx < 3)
        self._next_btn.setVisible(idx < 3)
        if idx == 0:
            self._next_btn.setEnabled(self._credits is not None)
        elif idx == 1:
            self._next_btn.setEnabled(self._method is not None)
            self._next_btn.setText("Next →")
        elif idx == 2:
            self._next_btn.setText("Pay Now ▶")
            self._upi_w.setVisible(self._method == "upi")
            self._card_w.setVisible(self._method == "card")
            self._nb_w.setVisible(self._method == "netbanking")
            self._reset_errors()
            self._check_details()
        elif idx == 3:
            self._start_processing()

    def _go_next(self):
        cur = self.stack.currentIndex()
        self._goto(cur + 1 if cur < 4 else cur)

    def _go_back(self):
        cur = self.stack.currentIndex()
        self._goto(max(0, cur - 1))

    # ── Input helpers ───────────────────────────────────────────────────────────
    def _format_card_number(self, text):
        """Auto-inserts spaces every 4 digits for card number formatting."""
        raw = text.replace(" ", "")
        if not raw.isdigit() and raw:
            return  # ignore non-digit input (except spaces already there)
        formatted = " ".join(raw[i:i+4] for i in range(0, len(raw), 4))
        if formatted != text:
            self.card_num.blockSignals(True)
            self.card_num.setText(formatted)
            self.card_num.setCursorPosition(len(formatted))
            self.card_num.blockSignals(False)

    def _format_expiry(self, text):
        """Auto-inserts / after MM for expiry formatting."""
        raw = text.replace("/", "")
        if not raw.isdigit() and raw:
            return
        if len(raw) >= 2:
            formatted = raw[:2] + "/" + raw[2:4]
        else:
            formatted = raw
        if formatted != text:
            self.card_exp.blockSignals(True)
            self.card_exp.setText(formatted)
            self.card_exp.setCursorPosition(len(formatted))
            self.card_exp.blockSignals(False)

    def _validate_upi(self, text):
        """Returns True if text matches a valid UPI ID pattern."""
        return bool(re.match(r'^[a-zA-Z0-9._-]+@[a-zA-Z0-9]+$', text.strip()))

    def _validate_expiry(self, text):
        """Returns True for MM/YY where MM is 01-12."""
        if not re.match(r'^\d{2}/\d{2}$', text):
            return False
        month = int(text[:2])
        return 1 <= month <= 12

    def _check_details(self):
        m = self._method
        ok = False

        if m == "upi":
            upi_text = self.upi_input.text().strip()
            if not upi_text:
                self._upi_err.setVisible(False)
                self._set_field_border(self.upi_input, 'normal')
            elif self._validate_upi(upi_text):
                self._upi_err.setVisible(False)
                self._set_field_border(self.upi_input, 'valid')
                ok = True
            else:
                self._upi_err.setText("✗ Invalid UPI ID — use format: name@upi or number@bank")
                self._upi_err.setVisible(True)
                self._set_field_border(self.upi_input, 'invalid')

        elif m == "card":
            card_ok = len(self.card_num.text().replace(" ", "")) >= 12
            name_ok = len(self.card_name.text().strip()) > 1
            exp_ok = self._validate_expiry(self.card_exp.text())
            cvv_ok = len(self.card_cvv.text()) >= 3

            # Card number
            if self.card_num.text() and not card_ok:
                self._card_num_err.setText("✗ Card number must be at least 12 digits")
                self._card_num_err.setVisible(True)
                self._set_field_border(self.card_num, 'invalid')
            elif self.card_num.text():
                self._card_num_err.setVisible(False)
                self._set_field_border(self.card_num, 'valid' if card_ok else 'normal')
            else:
                self._card_num_err.setVisible(False)

            # Expiry
            if self.card_exp.text() and not exp_ok:
                self._exp_err.setText("✗ Invalid expiry — use MM/YY (e.g. 12/26)")
                self._exp_err.setVisible(True)
                self._set_field_border(self.card_exp, 'invalid')
            elif self.card_exp.text():
                self._exp_err.setVisible(False)
                self._set_field_border(self.card_exp, 'valid' if exp_ok else 'normal')
            else:
                self._exp_err.setVisible(False)

            # CVV
            if self.card_cvv.text() and not cvv_ok:
                self._cvv_err.setText("✗ CVV must be 3–4 digits")
                self._cvv_err.setVisible(True)
                self._set_field_border(self.card_cvv, 'invalid')
            elif self.card_cvv.text():
                self._cvv_err.setVisible(False)
                self._set_field_border(self.card_cvv, 'valid' if cvv_ok else 'normal')
            else:
                self._cvv_err.setVisible(False)

            ok = card_ok and name_ok and exp_ok and cvv_ok

        elif m == "netbanking":
            ok = any(b.isChecked() for b in self._bank_btns)

        self._next_btn.setEnabled(ok)

    def _reset_errors(self):
        """Hide all inline errors and reset field borders to normal style."""
        for err_lbl in [self._upi_err, self._card_num_err, self._exp_err, self._cvv_err]:
            err_lbl.setVisible(False)
        for field in [self.upi_input, self.card_num, self.card_name, self.card_exp, self.card_cvv]:
            self._set_field_border(field, 'normal')

    def _set_field_border(self, field: QLineEdit, state: str):
        """Sets border colour of a QLineEdit: normal / valid / invalid."""
        colors = {
            'normal':  COLOR_BORDER,
            'valid':   '#22C55E',
            'invalid': '#EF4444',
        }
        bc = colors.get(state, COLOR_BORDER)
        field.setStyleSheet(f"""
            QLineEdit {{
                background: {COLOR_BG_CARD}; color: {COLOR_TEXT};
                border: 1.5px solid {bc}; border-radius: 8px;
                padding: 10px 14px; font-size: 13px; font-family: 'Inter', 'Segoe UI';
            }}
            QLineEdit:focus {{ border: 1.5px solid {COLOR_ACCENT if state == 'normal' else bc}; }}
        """)

    # ── Processing ─────────────────────────────────────────────────────────────
    def _start_processing(self):
        self._proc_bar.setValue(0)
        self._proc_lbl.setText("Connecting to payment gateway…")
        self._prog_timers = []
        steps = [
            (700,  "Authenticating…", 20),
            (1500, "Processing payment…", 45),
            (2400, "Verifying transaction…", 70),
            (3200, "Crediting account…", 90),
        ]
        for delay, msg, prog in steps:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda m=msg, p=prog: self._proc_tick(m, p))
            t.start(delay)
            self._prog_timers.append(t)
        ft = QTimer(self)
        ft.setSingleShot(True)
        ft.timeout.connect(self._finish)
        ft.start(4000)
        self._prog_timers.append(ft)

    def _proc_tick(self, msg, prog):
        self._proc_lbl.setText(msg)
        self._proc_bar.setValue(prog)

    def _finish(self):
        txn = "TXN" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
        method_map = {"upi": "UPI", "card": "Card", "netbanking": "Net Banking"}
        mstr = method_map.get(self._method, "UPI")
        self.db.add_payment(
            user_id=self.user['id'],
            amount=self._price,
            credits_purchased=self._credits,
            payment_method=mstr,
            transaction_id=txn
        )
        # NOTE: do NOT call update_credits here — add_payment already does it internally
        self._proc_bar.setValue(100)
        self._result_sub.setText(f"{self._credits} credits added  ·  ₹{self._price} charged")
        self._txn_lbl.setText(f"TXN ID: {txn}  ·  {mstr}")
        self.credits_added.emit(self._credits)
        self._goto(4)
