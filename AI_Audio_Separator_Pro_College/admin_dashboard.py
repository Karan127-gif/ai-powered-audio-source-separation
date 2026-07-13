import os
import shutil
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QLineEdit, QTextEdit, QFileDialog, QSizePolicy,
    QMessageBox, QSpinBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap

from config import (COLOR_BG_DARK, COLOR_BG_SURFACE, COLOR_BG_CARD,
                    COLOR_BORDER, COLOR_ACCENT, COLOR_ACCENT_SOFT,
                    COLOR_TEXT, COLOR_TEXT_MUTED, COLOR_CORAL,
                    TEAM_PHOTOS_DIR)
from database import Database

NAV_STYLE = f"""
QWidget#sidebar {{
    background: {COLOR_BG_SURFACE};
    border-right: 1px solid {COLOR_BORDER};
}}
QPushButton#nav_btn {{
    background: transparent;
    color: {COLOR_TEXT_MUTED};
    border: none;
    border-radius: 8px;
    padding: 11px 14px;
    text-align: left;
    font-family: 'Inter', 'Segoe UI';
    font-size: 13px;
    font-weight: 500;
}}
QPushButton#nav_btn:hover {{
    background: rgba(124,92,240, 0.09);
    color: {COLOR_ACCENT_SOFT};
}}
QPushButton#nav_btn:checked {{
    background: rgba(124,92,240, 0.14);
    color: {COLOR_ACCENT};
    border-left: 2px solid {COLOR_ACCENT};
    font-weight: 600;
}}
"""

GLOBAL_STYLE = f"""
QMainWindow, QWidget {{
    background: {COLOR_BG_DARK};
    color: {COLOR_TEXT};
    font-family: 'Inter', 'Segoe UI', sans-serif;
}}
QTableWidget {{
    background: {COLOR_BG_CARD};
    color: {COLOR_TEXT};
    border: none;
    border-radius: 10px;
    gridline-color: {COLOR_BORDER};
    font-family: 'Inter', 'Segoe UI';
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 6px 10px;
}}
QTableWidget::item:selected {{
    background: rgba(124,92,240,0.18);
    color: {COLOR_ACCENT_SOFT};
}}
QHeaderView::section {{
    background: {COLOR_BG_CARD};
    color: {COLOR_ACCENT_SOFT};
    border: none;
    border-bottom: 1px solid {COLOR_BORDER};
    padding: 8px 10px;
    font-weight: bold;
    font-family: 'Inter', 'Segoe UI';
}}
QScrollBar:vertical {{
    background: transparent; width: 5px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_BORDER}; border-radius: 3px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QLineEdit {{
    background: {COLOR_BG_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    color: {COLOR_TEXT};
    padding: 8px 12px;
    font-size: 12px;
    font-family: 'Inter', 'Segoe UI';
}}
QLineEdit:focus {{
    border: 1px solid {COLOR_ACCENT};
}}
QSpinBox {{
    background: {COLOR_BG_CARD};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    color: {COLOR_TEXT};
    padding: 6px 10px;
    font-size: 12px;
    font-family: 'Inter', 'Segoe UI';
}}
"""

def _btn(text, color=None, size=11):
    b = QPushButton(text)
    b.setFixedHeight(36)
    b.setFont(QFont("Inter", size, QFont.Weight.Bold))
    c = color or COLOR_ACCENT
    b.setStyleSheet(f"""
        QPushButton {{
            background: {c}; color: white;
            border-radius: 8px; border: none;
            padding: 0 16px;
        }}
        QPushButton:hover {{ opacity: 0.85; }}
    """)
    return b

def _outline_btn(text, color=None, size=10):
    b = QPushButton(text)
    b.setFixedHeight(30)
    b.setFont(QFont("Inter", size))
    c = color or COLOR_ACCENT
    b.setStyleSheet(f"""
        QPushButton {{
            background: transparent; color: {c};
            border: 1px solid {c};
            border-radius: 6px; padding: 0 10px;
        }}
        QPushButton:hover {{ background: rgba(124,92,240,0.10); color: {COLOR_ACCENT_SOFT}; border-color: {COLOR_ACCENT}; }}
    """)
    return b


class AdminDashboard(QMainWindow):
    def __init__(self, user, controller):
        super().__init__()
        self.user = user
        self.controller = controller
        self.db = Database()
        self.setWindowTitle("AI Audio Separator Pro — Admin")
        self.setStyleSheet(GLOBAL_STYLE + NAV_STYLE)
        self.setMinimumSize(1200, 700)
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(200)
        sbl = QVBoxLayout(sidebar)
        sbl.setContentsMargins(12, 20, 12, 20)
        sbl.setSpacing(4)

        logo = QLabel("◎  Admin Panel")
        logo.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        logo.setStyleSheet(f"color: {COLOR_ACCENT}; padding: 8px 8px 16px 8px; letter-spacing: 0.5px;")
        sbl.addWidget(logo)

        user_lbl = QLabel(f"◈  {self.user['username']}")
        user_lbl.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        user_lbl.setStyleSheet(f"""
            background: rgba(124,92,240,0.10); color: {COLOR_ACCENT_SOFT};
            border-radius: 7px; padding: 5px 10px;
            border: 1px solid rgba(124,92,240,0.18);
        """)
        sbl.addWidget(user_lbl)
        sbl.addSpacing(12)

        self.nav_buttons = []
        pages = [
            ("▤", "Dashboard", 0),
            ("▤", "Users", 1),
            ("▤", "Payments", 2),
            ("▤", "Separations", 3),
            ("▤", "Team Members", 4),
            ("▤", "Feedback", 5),
            ("◎", "Settings", 6),
        ]
        for icon, name, idx in pages:
            btn = QPushButton(f"{icon}  {name}")
            btn.setObjectName("nav_btn")
            btn.setCheckable(True)
            btn.setFixedHeight(42)
            btn.clicked.connect(lambda checked, pi=idx: self._navigate(pi))
            self.nav_buttons.append(btn)
            sbl.addWidget(btn)

        sbl.addStretch()

        logout_btn = QPushButton("→  Sign Out")
        logout_btn.setFixedHeight(36)
        logout_btn.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        logout_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLOR_TEXT_MUTED};
                border: 1px solid {COLOR_BORDER};
                border-radius: 7px;
            }}
            QPushButton:hover {{
                background: rgba(239,68,68,0.10);
                color: #EF4444;
                border: 1px solid rgba(239,68,68,0.25);
            }}
        """)
        logout_btn.clicked.connect(self._logout)
        sbl.addWidget(logout_btn)
        root.addWidget(sidebar)

        # ── Page stack ───────────────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.addWidget(self._make_dashboard_page())
        self.stack.addWidget(self._make_users_page())
        self.stack.addWidget(self._make_payments_page())
        self.stack.addWidget(self._make_separations_page())
        self.stack.addWidget(self._make_team_page())
        self.stack.addWidget(self._make_feedback_page())
        self.stack.addWidget(self._make_settings_page())
        root.addWidget(self.stack)
        self._navigate(0)

    def _navigate(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == idx)
        refresh = {1: self._load_users, 2: self._load_payments,
                   3: self._load_separations, 4: self._load_team,
                   5: self._load_feedback, 6: self._load_settings}
        if idx in refresh:
            refresh[idx]()

    def _wrap_scroll(self, inner):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        inner.setStyleSheet(f"background: {COLOR_BG_DARK};")
        scroll.setWidget(inner)
        return scroll

    def _card_style(self):
        return f"background: {COLOR_BG_CARD}; border-radius: 12px; border: 1px solid {COLOR_BORDER};"

    # ── Dashboard page ────────────────────────────────────────────────────────
    def _make_dashboard_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(24)

        title = QLabel("Dashboard")
        title.setFont(QFont("Inter", 20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.5px;")
        l.addWidget(title)

        stats = self.db.get_stats()
        stats_data = [
            ("▤", "Total Users",       str(stats['total_users'])),
            ("▤", "Total Revenue",     f"₹{stats['total_revenue']:.0f}"),
            ("▤", "Total Separations", str(stats['total_separations'])),
            ("◈", "Credits Sold",      str(stats['total_credits_sold'])),
        ]
        row = QHBoxLayout()
        row.setSpacing(14)
        for icon, label, val in stats_data:
            card = QFrame()
            card.setStyleSheet(self._card_style())
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 18, 20, 18)
            em = QLabel(icon)
            em.setFont(QFont("Inter", 20))
            em.setStyleSheet(f"color: {COLOR_ACCENT};")
            vl = QLabel(val)
            vl.setFont(QFont("Inter", 22, QFont.Weight.Bold))
            vl.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
            lb = QLabel(label)
            lb.setFont(QFont("Inter", 10))
            lb.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            cl.addWidget(em)
            cl.addWidget(vl)
            cl.addWidget(lb)
            row.addWidget(card)
        l.addLayout(row)
        l.addStretch()
        return self._wrap_scroll(inner)

    # ── Users page ────────────────────────────────────────────────────────────
    def _make_users_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(16)

        hdr = QHBoxLayout()
        title = QLabel("User Management")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        hdr.addWidget(title)
        hdr.addStretch()
        refresh_btn = _outline_btn("Refresh")
        refresh_btn.clicked.connect(self._load_users)
        hdr.addWidget(refresh_btn)
        l.addLayout(hdr)

        cols = ["ID", "Username", "Email", "Credits", "Joined", "Actions"]
        self.users_table = self._make_table(cols)
        l.addWidget(self.users_table)
        return self._wrap_scroll(inner)

    def _make_table(self, columns):
        t = QTableWidget()
        t.setColumnCount(len(columns))
        t.setHorizontalHeaderLabels(columns)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        t.setAlternatingRowColors(True)
        t.setStyleSheet(t.styleSheet() + f"alternate-background-color: {COLOR_BG_SURFACE};")
        t.verticalHeader().setVisible(False)
        return t

    def _load_users(self):
        users = self.db.get_all_users()
        t = self.users_table
        t.setRowCount(len(users))
        for i, u in enumerate(users):
            for j, val in enumerate([str(u['id']), u['username'],
                                      u.get('email', ''), str(u['credits']),
                                      u.get('created_at', '')[:10]]):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setItem(i, j, item)
            cell = QWidget()
            cell.setStyleSheet("background: transparent;")
            hr = QHBoxLayout(cell)
            hr.setContentsMargins(4, 2, 4, 2)
            hr.setSpacing(6)
            add_btn = _outline_btn("+ Credits", COLOR_ACCENT, 9)
            add_btn.clicked.connect(lambda _, uid=u['id'], uname=u['username']: self._add_credits_dialog(uid, uname))
            del_btn = _outline_btn("Delete", COLOR_CORAL, 9)
            del_btn.clicked.connect(lambda _, uid=u['id']: self._delete_user(uid))
            hr.addWidget(add_btn)
            hr.addWidget(del_btn)
            t.setCellWidget(i, 5, cell)
            t.setRowHeight(i, 44)

    def _add_credits_dialog(self, user_id, username):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Add Credits — {username}")
        dlg.setStyleSheet(GLOBAL_STYLE)
        dlg.resize(340, 200)
        l = QVBoxLayout(dlg)
        l.setContentsMargins(28, 24, 28, 24)
        l.setSpacing(14)
        l.addWidget(QLabel(f"Add credits to {username}:"))
        spin = QSpinBox()
        spin.setRange(1, 9999)
        spin.setValue(10)
        l.addWidget(spin)
        btn_row = QHBoxLayout()
        ok = _btn("Add Credits")
        ok.clicked.connect(lambda: (self.db.update_credits(user_id, spin.value()), dlg.accept(), self._load_users()))
        cancel = _outline_btn("Cancel", COLOR_CORAL)
        cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(ok)
        btn_row.addWidget(cancel)
        l.addLayout(btn_row)
        dlg.exec()

    def _delete_user(self, user_id):
        self.db.delete_user(user_id)
        self._load_users()

    # ── Payments page ─────────────────────────────────────────────────────────
    def _make_payments_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(16)
        title = QLabel("Payment History")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)
        self.payments_table = self._make_table(["ID", "Username", "Amount (₹)", "Credits", "Method", "TXN ID", "Date"])
        l.addWidget(self.payments_table)
        return self._wrap_scroll(inner)

    def _load_payments(self):
        payments = self.db.get_all_payments()
        t = self.payments_table
        t.setRowCount(len(payments))
        for i, p in enumerate(payments):
            for j, val in enumerate([str(p['id']), p['username'], f"₹{p['amount']:.0f}",
                                      str(p['credits_purchased']), p.get('payment_method', ''),
                                      p.get('transaction_id', ''), p.get('timestamp', '')[:16]]):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setItem(i, j, item)

    # ── Separations page ──────────────────────────────────────────────────────
    def _make_separations_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(16)
        title = QLabel("Separation History")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)
        self.sep_table = self._make_table(["ID", "Username", "File", "Type", "Credits", "Date"])
        l.addWidget(self.sep_table)
        return self._wrap_scroll(inner)

    def _load_separations(self):
        rows = self.db.get_all_separations()
        t = self.sep_table
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, val in enumerate([str(r['id']), r['username'], r.get('filename', ''),
                                      r.get('separation_type', ''), str(r['credits_used']),
                                      r.get('timestamp', '')[:16]]):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setItem(i, j, item)

    # ── Team members page ─────────────────────────────────────────────────────
    def _make_team_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(16)

        hdr = QHBoxLayout()
        title = QLabel("Team Members")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        hdr.addWidget(title)
        hdr.addStretch()
        add_btn = _btn("+ Add Member")
        add_btn.clicked.connect(self._add_team_member_dialog)
        hdr.addWidget(add_btn)
        l.addLayout(hdr)

        self.team_table = self._make_table(["ID", "Photo", "Name", "Role", "Bio", "Actions"])
        self.team_table.setColumnWidth(1, 70)
        l.addWidget(self.team_table)
        return self._wrap_scroll(inner)

    def _load_team(self):
        members = self.db.get_team_members()
        t = self.team_table
        t.setRowCount(len(members))
        for i, m in enumerate(members):
            t.setItem(i, 0, QTableWidgetItem(str(m['id'])))
            photo_cell = QLabel()
            photo_cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            photo_cell.setStyleSheet("background: transparent;")
            if m.get('photo_path') and os.path.exists(m['photo_path']):
                pix = QPixmap(m['photo_path']).scaled(48, 48,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
                photo_cell.setPixmap(pix)
            else:
                photo_cell.setText("◎")
                photo_cell.setFont(QFont("Inter", 22))
                photo_cell.setStyleSheet(f"color: {COLOR_ACCENT}; background: transparent;")
            t.setCellWidget(i, 1, photo_cell)
            for j, val in enumerate([m['name'], m.get('role', ''), m.get('bio', '')[:40]], start=2):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setItem(i, j, item)
            cell = QWidget()
            cell.setStyleSheet("background: transparent;")
            hr = QHBoxLayout(cell)
            hr.setContentsMargins(4, 2, 4, 2)
            hr.setSpacing(6)
            edit_btn = _outline_btn("Edit", COLOR_ACCENT_SOFT, 9)
            edit_btn.clicked.connect(lambda _, mid=m['id']: self._edit_team_member_dialog(mid))
            del_btn = _outline_btn("Delete", COLOR_CORAL, 9)
            del_btn.clicked.connect(lambda _, mid=m['id']: (self.db.delete_team_member(mid), self._load_team()))
            hr.addWidget(edit_btn)
            hr.addWidget(del_btn)
            t.setCellWidget(i, 5, cell)
            t.setRowHeight(i, 60)

    def _team_member_dialog(self, title, name='', role='', bio='', photo_path=''):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setStyleSheet(GLOBAL_STYLE)
        dlg.resize(440, 480)
        l = QVBoxLayout(dlg)
        l.setContentsMargins(28, 24, 28, 24)
        l.setSpacing(12)

        name_ed = QLineEdit(name)
        name_ed.setPlaceholderText("Full Name")
        role_ed = QLineEdit(role)
        role_ed.setPlaceholderText("Role / Position")
        bio_ed = QTextEdit()
        bio_ed.setPlaceholderText("Short bio…")
        bio_ed.setPlainText(bio)
        bio_ed.setMaximumHeight(100)
        bio_ed.setStyleSheet(f"""
            QTextEdit {{
                background: {COLOR_BG_CARD}; color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER}; border-radius: 8px;
                padding: 8px; font-family: 'Inter'; font-size: 12px;
            }}
            QTextEdit:focus {{ border: 1px solid {COLOR_ACCENT}; }}
        """)

        photo_holder = [photo_path]
        photo_preview = QLabel()
        photo_preview.setFixedSize(80, 80)
        photo_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        photo_preview.setStyleSheet(f"""
            border: 2px solid {COLOR_ACCENT};
            border-radius: 40px;
            background: {COLOR_BG_CARD};
        """)
        if photo_path and os.path.exists(photo_path):
            pix = QPixmap(photo_path).scaled(80, 80,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation)
            photo_preview.setPixmap(pix)
        else:
            photo_preview.setText("◎")
            photo_preview.setFont(QFont("Inter", 28))
            photo_preview.setStyleSheet(f"color: {COLOR_ACCENT}; border: 2px solid {COLOR_ACCENT}; border-radius: 40px;")

        upload_btn = _outline_btn("Upload Photo", COLOR_ACCENT)
        def _upload():
            path, _ = QFileDialog.getOpenFileName(dlg, "Select Photo", "", "Images (*.jpg *.jpeg *.png)")
            if path:
                dest = os.path.join(TEAM_PHOTOS_DIR, os.path.basename(path))
                shutil.copy2(path, dest)
                photo_holder[0] = dest
                pix = QPixmap(dest).scaled(80, 80,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation)
                photo_preview.setPixmap(pix)
        upload_btn.clicked.connect(_upload)

        photo_row = QHBoxLayout()
        photo_row.addWidget(photo_preview)
        photo_row.addSpacing(16)
        photo_row.addWidget(upload_btn)
        photo_row.addStretch()

        for lbl, widget in [("Name", name_ed), ("Role", role_ed), ("Bio", bio_ed)]:
            l.addWidget(QLabel(lbl))
            l.addWidget(widget)
        l.addWidget(QLabel("Photo"))
        l.addLayout(photo_row)

        btn_row = QHBoxLayout()
        ok = _btn("Save")
        cancel = _outline_btn("Cancel", COLOR_CORAL)
        cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(ok)
        btn_row.addWidget(cancel)
        l.addLayout(btn_row)

        result = [None]
        def _save():
            result[0] = (name_ed.text().strip(), role_ed.text().strip(),
                         bio_ed.toPlainText().strip(), photo_holder[0])
            dlg.accept()
        ok.clicked.connect(_save)
        dlg.exec()
        return result[0]

    def _add_team_member_dialog(self):
        res = self._team_member_dialog("Add Team Member")
        if res:
            name, role, bio, photo = res
            if name:
                self.db.add_team_member(name, role, bio, photo)
                self._load_team()

    def _edit_team_member_dialog(self, member_id):
        members = {m['id']: m for m in self.db.get_team_members()}
        m = members.get(member_id)
        if not m:
            return
        res = self._team_member_dialog("Edit Team Member",
                                       m['name'], m.get('role', ''),
                                       m.get('bio', ''), m.get('photo_path', ''))
        if res:
            name, role, bio, photo = res
            if name:
                self.db.update_team_member(member_id, name, role, bio, photo)
                self._load_team()

    # ── Feedback page ─────────────────────────────────────────────────────────
    def _make_feedback_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(16)
        title = QLabel("User Feedback")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)
        self.feedback_table = self._make_table(["ID", "Username", "Message", "Date"])
        l.addWidget(self.feedback_table)
        return self._wrap_scroll(inner)

    def _load_feedback(self):
        rows = self.db.get_all_feedback()
        t = self.feedback_table
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, val in enumerate([str(r['id']), r.get('username', 'Anonymous'),
                                      r.get('message', '')[:60],
                                      r.get('timestamp', '')[:16]]):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setItem(i, j, item)

    # ── Settings page ─────────────────────────────────────────────────────────
    def _make_settings_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(20)

        title = QLabel("System Settings")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)

        card = QFrame()
        card.setStyleSheet(self._card_style())
        cl = QVBoxLayout(card)
        cl.setContentsMargins(28, 24, 28, 24)
        cl.setSpacing(16)

        self.settings_fields = {}
        setting_defs = [
            ("contact_email", "Contact Email"),
            ("contact_phone", "Contact Phone"),
            ("app_name",      "App Name"),
            ("free_credits",  "Free Credits for New Users"),
        ]
        for key, label in setting_defs:
            lbl = QLabel(label)
            lbl.setFont(QFont("Inter", 11, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            ed = QLineEdit()
            ed.setPlaceholderText(label)
            self.settings_fields[key] = ed
            cl.addWidget(lbl)
            cl.addWidget(ed)

        save_btn = _btn("Save Settings")
        save_btn.setFixedWidth(160)
        save_btn.clicked.connect(self._save_settings)
        cl.addWidget(save_btn)

        self.settings_msg = QLabel("")
        self.settings_msg.setFont(QFont("Inter", 10))
        cl.addWidget(self.settings_msg)

        l.addWidget(card)
        l.addStretch()
        return self._wrap_scroll(inner)

    def _load_settings(self):
        all_s = self.db.get_all_settings()
        for key, ed in self.settings_fields.items():
            ed.setText(all_s.get(key, ''))

    def _save_settings(self):
        for key, ed in self.settings_fields.items():
            self.db.set_setting(key, ed.text().strip())
        self.settings_msg.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
        self.settings_msg.setText("✓ Settings saved!")

    def _logout(self):
        self.controller.logout()
