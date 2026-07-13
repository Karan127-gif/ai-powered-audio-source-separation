import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QScrollArea, QFileDialog, QProgressBar,
    QComboBox, QTextEdit, QSizePolicy, QDialog, QMessageBox,
    QLineEdit, QListWidget, QDialogButtonBox, QGridLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QDragEnterEvent, QDropEvent

from config import (
    COLOR_BG_DARK, COLOR_BG_SURFACE, COLOR_BG_CARD,
    COLOR_BORDER, COLOR_TEXT, COLOR_TEXT_MUTED,
    COLOR_ACCENT, COLOR_ACCENT_SOFT,
    COLOR_ORANGE, COLOR_CORAL, COLOR_AMBER, COLOR_GREEN, COLOR_CYAN,
    MODEL_PATH, STEM_NAMES, SINGLE_STEM_COST, ALL_STEMS_COST
)
from database import Database
from auth_window import WaveCanvas

# ── Navigation sidebar style ─────────────────────────────────────────────────
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
    letter-spacing: 0.1px;
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

# ── Global application stylesheet ─────────────────────────────────────────────
GLOBAL_STYLE = f"""
QMainWindow, QWidget {{
    background: {COLOR_BG_DARK};
    color: {COLOR_TEXT};
    font-family: 'Inter', 'Segoe UI', sans-serif;
}}
QScrollBar:vertical {{
    background: transparent; width: 5px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_BORDER}; border-radius: 3px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLOR_ACCENT};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QProgressBar {{
    background: {COLOR_BG_CARD}; border-radius: 4px;
    border: 1px solid {COLOR_BORDER}; height: 6px; text-align: center;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {COLOR_ACCENT}, stop:1 {COLOR_CYAN});
    border-radius: 4px;
}}
QComboBox {{
    background: {COLOR_BG_CARD}; color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER}; border-radius: 8px;
    padding: 6px 12px; font-family: 'Inter', 'Segoe UI'; font-size: 12px;
}}
QComboBox:hover {{ border: 1px solid {COLOR_ACCENT}; }}
QComboBox QAbstractItemView {{
    background: {COLOR_BG_CARD}; color: {COLOR_TEXT};
    border: 1px solid {COLOR_BORDER}; selection-background-color: rgba(124,92,240,0.22);
}}
"""


# ── Background threads ────────────────────────────────────────────────────────

class ModelLoaderThread(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def run(self):
        try:
            import torch
            from model import MultiStemUNet
            if not os.path.exists(MODEL_PATH):
                self.error.emit(f"Model file not found: {MODEL_PATH}")
                return
            model = MultiStemUNet(out_channels=4)
            ck = torch.load(MODEL_PATH, map_location='cpu', weights_only=False)
            if isinstance(ck, dict):
                state = ck.get('model_state_dict') or ck.get('state_dict') or ck
            else:
                state = ck
            model.load_state_dict(state, strict=False)
            model.eval()
            self.finished.emit(model)
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n\nTraceback:\n{traceback.format_exc()[-400:]}")


class SeparationThread(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(dict, dict)
    error = pyqtSignal(str)

    def __init__(self, model, audio_path, selected_stems, cost):
        super().__init__()
        self.model = model
        self.audio_path = audio_path
        self.selected_stems = selected_stems
        self.cost = cost

    def run(self):
        try:
            from audio_processor import separate_audio
            results, paths = separate_audio(
                self.audio_path, self.model,
                self.selected_stems,
                progress_cb=lambda pct, msg: self.progress.emit(pct, msg)
            )
            self.finished.emit(results, paths)
        except Exception as e:
            self.error.emit(str(e))


class LoadPreviousThread(QThread):
    """Loads pre-separated WAV files off the main thread to prevent UI freezing."""
    finished = pyqtSignal(dict, dict, str)   # results, output_paths, base_name
    error    = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, stem_paths: dict, base_name: str):
        super().__init__()
        self.stem_paths = stem_paths
        self.base_name  = base_name

    def run(self):
        try:
            import numpy as np
            import soundfile as sf
            results = {}
            output_paths = {}
            items = list(self.stem_paths.items())
            for i, (stem, path) in enumerate(items):
                self.progress.emit(int(100 * i / len(items)), f"Loading {stem}…")
                audio, _ = sf.read(path, dtype='float32')
                if audio.ndim == 1:
                    audio = np.stack([audio, audio], axis=0)
                else:
                    audio = audio.T   # (channels, samples)
                results[stem] = audio
                output_paths[stem] = path
            self.progress.emit(100, "Done")
            self.finished.emit(results, output_paths, self.base_name)
        except Exception as e:
            self.error.emit(str(e))


# ── User Dashboard ────────────────────────────────────────────────────────────

class UserDashboard(QMainWindow):
    def __init__(self, user, controller):
        super().__init__()
        self.user = user
        self.controller = controller
        self.db = Database()
        self.model = None
        self.model_thread = None
        self.sep_thread = None
        self.load_thread = None         # LoadPreviousThread
        self.current_file = None
        self.setWindowTitle("AI Audio Separator Pro — Dashboard")
        self.setStyleSheet(GLOBAL_STYLE + NAV_STYLE)
        self.setMinimumSize(1100, 700)
        self._build_ui()
        # Timeout watchdog: if model hasn't loaded in 90 s, show an error
        self._model_timeout_timer = QTimer()
        self._model_timeout_timer.setSingleShot(True)
        self._model_timeout_timer.timeout.connect(self._on_model_timeout)
        QTimer.singleShot(200, self._start_model_load)
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(500)
        self._poll_timer.timeout.connect(self._poll_ready)
        self._poll_timer.start()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(12, 20, 12, 20)
        sb_layout.setSpacing(4)

        logo = QLabel("◎  AI Separator")
        logo.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        logo.setStyleSheet(f"color: {COLOR_ACCENT}; padding: 8px 8px 16px 8px; letter-spacing: 0.5px;")
        sb_layout.addWidget(logo)

        # Credits badge
        self.credits_lbl = QLabel(f"◈  {self.user['credits']} credits")
        self.credits_lbl.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        self.credits_lbl.setStyleSheet(f"""
            background: rgba(124,92,240,0.10); color: {COLOR_ACCENT_SOFT};
            border-radius: 7px; padding: 5px 10px;
            border: 1px solid rgba(124,92,240,0.18);
        """)
        sb_layout.addWidget(self.credits_lbl)

        # Recharge button
        recharge_btn = QPushButton("+ Recharge Credits")
        recharge_btn.setFixedHeight(34)
        recharge_btn.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        recharge_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(124,92,240,0.15); color: {COLOR_ACCENT_SOFT};
                border-radius: 7px; border: 1px solid rgba(124,92,240,0.25); margin-top: 2px;
            }}
            QPushButton:hover {{ background: {COLOR_ACCENT}; color: white; }}
        """)
        recharge_btn.clicked.connect(self._open_payment)
        sb_layout.addWidget(recharge_btn)

        sb_layout.addSpacing(12)

        # Nav buttons
        self.nav_buttons = []
        pages = [("🏠", "Home", 0), ("✂️", "Separate Audio", 1),
                 ("📋", "History", 2), ("👤", "Profile", 3),
                 ("📝", "Feedback", 4), ("❓", "Help & FAQ", 5),
                 ("📞", "Contact", 6)]
        for icon, name, idx in pages:
            btn = QPushButton(f"{icon}  {name}")
            btn.setObjectName("nav_btn")
            btn.setCheckable(True)
            btn.setFixedHeight(44)
            page_idx = idx
            btn.clicked.connect(lambda checked, pi=page_idx: self._navigate(pi))
            self.nav_buttons.append(btn)
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        # Logout (always visible, outside scroll)
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
        sb_layout.addWidget(logout_btn)

        root.addWidget(sidebar)

        # ── Page stack ───────────────────────────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.addWidget(self._make_home_page())        # 0
        self.stack.addWidget(self._make_separation_page())  # 1
        self.stack.addWidget(self._make_history_page())     # 2
        self.stack.addWidget(self._make_profile_page())     # 3
        self.stack.addWidget(self._make_feedback_page())    # 4
        self.stack.addWidget(self._make_help_page())        # 5
        self.stack.addWidget(self._make_contact_page())     # 6
        root.addWidget(self.stack)

        self._navigate(0)

    # ── Navigation ────────────────────────────────────────────────────────────
    def _navigate(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == idx)
        if idx == 0:
            self._refresh_home_stats()
        if idx == 2:
            self._refresh_history()
        if idx == 3:
            self._refresh_profile()

    # ── Scroll wrapper ────────────────────────────────────────────────────────
    def _wrap_scroll(self, inner_widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background: transparent;")
        inner_widget.setStyleSheet(f"background: {COLOR_BG_DARK};")
        scroll.setWidget(inner_widget)
        return scroll

    # ── Home page ─────────────────────────────────────────────────────────────
    def _make_home_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(24)

        welcome = QLabel(f"Welcome back, {self.user['username']}")
        welcome.setFont(QFont("Inter", 22, QFont.Weight.Bold))
        welcome.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.5px;")
        l.addWidget(welcome)

        sub = QLabel("Ready to separate some audio?")
        sub.setFont(QFont("Segoe UI", 13))
        sub.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        l.addWidget(sub)

        # Stat cards
        stats_row = QHBoxLayout()
        stats_row.setSpacing(16)
        hist = self.db.get_user_history(self.user['id'])
        stat_data = [
            ("🎵", "Songs Separated", str(len(hist))),
            ("💰", "Credits Left", str(self.user['credits'])),
            ("⭐", "Credits Used", str(sum(h['credits_used'] for h in hist))),
        ]
        # Store value-label references so _refresh_home_stats() can update them live
        self._home_stat_vals = {}
        for icon, label, value in stat_data:
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background: {COLOR_BG_CARD};
                    border-radius: 12px;
                    border: 1px solid {COLOR_BORDER};
                }}
            """)
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 18, 20, 18)
            em = QLabel(icon)
            em.setFont(QFont("Inter", 24))
            val_lbl = QLabel(value)
            val_lbl.setFont(QFont("Inter", 22, QFont.Weight.Bold))
            val_lbl.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
            lbl = QLabel(label)
            lbl.setFont(QFont("Inter", 10))
            lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            cl.addWidget(em)
            cl.addWidget(val_lbl)
            cl.addWidget(lbl)
            stats_row.addWidget(card)
            self._home_stat_vals[label] = val_lbl
        l.addLayout(stats_row)

        # Quick actions
        qa_title = QLabel("◆ Quick Actions")
        qa_title.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        qa_title.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; letter-spacing: 0.5px;")
        l.addWidget(qa_title)

        qa_row = QHBoxLayout()
        qa_row.setSpacing(12)
        actions = [("✂️  Separate Audio", 1), ("📋  View History", 2), ("◈  Recharge", None)]
        for btn_text, page_idx in actions:
            btn = QPushButton(btn_text)
            btn.setFixedHeight(44)
            btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(124,92,240,0.12);
                    color: {COLOR_ACCENT_SOFT}; border-radius: 10px;
                    border: 1px solid rgba(124,92,240,0.25);
                }}
                QPushButton:hover {{ background: {COLOR_ACCENT}; color: white; border: 1px solid {COLOR_ACCENT}; }}
            """)
            if page_idx is not None:
                btn.clicked.connect(lambda _, pi=page_idx: self._navigate(pi))
            else:
                btn.clicked.connect(self._open_payment)
            qa_row.addWidget(btn)
        l.addLayout(qa_row)

        # Model status line
        self.model_status_lbl = QLabel("🔄 Loading AI model in background…")
        self.model_status_lbl.setFont(QFont("Inter", 10))
        self.model_status_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        l.addWidget(self.model_status_lbl)

        # ── AI Model Performance card (BSS-Eval metrics from evaluation) ─────
        perf_card = QFrame()
        perf_card.setStyleSheet("""
            QFrame {
                background: #0A0A0F;
                border-radius: 14px;
                border: 1px solid rgba(124,92,240,0.30);
            }
        """)
        pc = QVBoxLayout(perf_card)
        pc.setContentsMargins(24, 20, 24, 20)
        pc.setSpacing(12)

        # Card header row
        hdr_row = QHBoxLayout()
        perf_title = QLabel("🧠  AI Model Performance  —  BSS-Eval Results")
        perf_title.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        perf_title.setStyleSheet("color: #A78BFA; letter-spacing: 0.3px;")
        hdr_row.addWidget(perf_title)
        hdr_row.addStretch()
        pc.addLayout(hdr_row)

        # Subtitle
        perf_sub = QLabel("Evaluated using the BSS-Eval toolkit — SDR: Signal-to-Distortion Ratio · SIR: Signal-to-Interference Ratio · SAR: Signal-to-Artifact Ratio · Higher = better")
        perf_sub.setFont(QFont("Inter", 9))
        perf_sub.setStyleSheet("color: #5A5A78;")
        perf_sub.setWordWrap(True)
        pc.addWidget(perf_sub)

        # Table header
        tbl = QGridLayout()
        tbl.setHorizontalSpacing(24)
        tbl.setVerticalSpacing(10)
        headers = ["Audio Stem", "Mean SDR (dB)", "Mean SIR (dB)", "Mean SAR (dB)"]
        h_style = "color: #A78BFA; font-family: 'Inter'; font-size: 10px; font-weight: bold; letter-spacing: 0.5px;"
        for col, hdr in enumerate(headers):
            h = QLabel(hdr)
            h.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            h.setStyleSheet(h_style)
            tbl.addWidget(h, 0, col)

        # Metric rows — from paper Table 4.1 (corrected)
        rows = [
            ("🎤  Vocals", "10.4", "18.2", "11.5", "#FF6B9D"),
            ("🥁  Drums",  "7.1",  "13.5", "9.4",  "#00D4FF"),
            ("🎸  Bass",   "6.8",  "12.4", "8.2",  "#FFD700"),
            ("🎹  Other",  "4.1",  "9.5",  "6.3",  "#ADFF2F"),
        ]
        val_style_tpl = "color: {}; font-family: 'Inter'; font-size: 12px; font-weight: bold;"
        name_style_tpl = "color: #E8E8F0; font-family: 'Inter'; font-size: 11px;"
        for r, (stem, sdr, sir, sar, color) in enumerate(rows, start=1):
            n = QLabel(stem)
            n.setFont(QFont("Inter", 11))
            n.setStyleSheet(name_style_tpl)
            tbl.addWidget(n, r, 0)
            for c, val in enumerate([sdr, sir, sar], start=1):
                v = QLabel(val)
                v.setFont(QFont("Inter", 12, QFont.Weight.Bold))
                v.setStyleSheet(val_style_tpl.format(color))
                tbl.addWidget(v, r, c)

        pc.addLayout(tbl)

        # Model architecture note
        arch_lbl = QLabel("◎  Model: Multi-Stem U-Net  ·  Architecture: Encoder-Decoder with skip connections  ·  Output: 4 stems × 2 channels  ·  Training: 300 epochs")
        arch_lbl.setFont(QFont("Inter", 9))
        arch_lbl.setStyleSheet("color: #5A5A78;")
        arch_lbl.setWordWrap(True)
        pc.addWidget(arch_lbl)

        l.addWidget(perf_card)

        l.addStretch()
        return self._wrap_scroll(inner)

    # ── Separation page ───────────────────────────────────────────────────────
    def _make_separation_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(40, 36, 40, 36)
        l.setSpacing(16)

        title = QLabel("✂  Separate Audio")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)

        # Drop zone
        self.drop_zone = _DropZone()
        self.drop_zone.file_dropped.connect(self._file_selected)
        l.addWidget(self.drop_zone)

        # Browse + Load previous row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        browse_btn = QPushButton("📂  Browse File")
        browse_btn.setFixedHeight(38)
        browse_btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        browse_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLOR_BG_CARD}; color: {COLOR_ACCENT_SOFT};
                border: 1px solid rgba(124,92,240,0.30); border-radius: 9px;
            }}
            QPushButton:hover {{ background: rgba(124,92,240,0.12); }}
        """)
        browse_btn.clicked.connect(self._browse_file)
        btn_row.addWidget(browse_btn)

        load_prev_btn = QPushButton("📁  Load Previous Results")
        load_prev_btn.setFixedHeight(38)
        load_prev_btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        load_prev_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLOR_BG_CARD}; color: {COLOR_TEXT_MUTED};
                border: 1px solid {COLOR_BORDER}; border-radius: 9px;
            }}
            QPushButton:hover {{ background: rgba(124,92,240,0.08); color: {COLOR_ACCENT_SOFT}; }}
        """)
        load_prev_btn.clicked.connect(self._load_previous_results)
        btn_row.addWidget(load_prev_btn)
        l.addLayout(btn_row)

        self.file_lbl = QLabel("No file selected")
        self.file_lbl.setFont(QFont("Segoe UI", 11))
        self.file_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        self.file_lbl.setWordWrap(True)
        l.addWidget(self.file_lbl)

        # Stem choice
        opt_row = QHBoxLayout()
        mode_lbl = QLabel("Separation Mode:")
        mode_lbl.setFont(QFont("Segoe UI", 12))
        opt_row.addWidget(mode_lbl)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "All 4 Stems (2 credits)",
            "Vocals only (1 credit)",
            "Drums only (1 credit)",
            "Bass only (1 credit)",
            "Other only (1 credit)",
        ])
        self.mode_combo.setStyleSheet(f"""
            QComboBox {{
                background: {COLOR_BG_CARD}; color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER}; border-radius: 8px;
                padding: 8px 12px; font-size: 12px; font-family: 'Inter';
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background: {COLOR_BG_CARD}; color: {COLOR_TEXT};
                selection-background-color: rgba(124,92,240,0.20);
            }}
        """)
        opt_row.addWidget(self.mode_combo)
        opt_row.addStretch()
        l.addLayout(opt_row)

        # Separate button
        self.separate_btn = QPushButton("🎛  Start Separation")
        self.separate_btn.setFixedHeight(48)
        self.separate_btn.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        self.separate_btn.setEnabled(False)
        self.separate_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {COLOR_ORANGE},stop:1 {COLOR_CORAL});
                color: white; border-radius: 12px; border: none;
            }}
            QPushButton:hover {{ background: {COLOR_CORAL}; }}
            QPushButton:disabled {{ background: #555; color: #888; }}
        """)
        self.separate_btn.clicked.connect(self._start_separation)
        l.addWidget(self.separate_btn)

        # Animated waveform shown during separation
        self._sep_wave = WaveCanvas()
        self._sep_wave.setFixedHeight(110)
        self._sep_wave.setVisible(False)
        l.addWidget(self._sep_wave)

        # Progress bar
        self.sep_progress = QProgressBar()
        self.sep_progress.setValue(0)
        self.sep_progress.setVisible(False)
        l.addWidget(self.sep_progress)

        self.sep_status = QLabel("")
        self.sep_status.setFont(QFont("Inter", 10))
        self.sep_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        self.sep_status.setWordWrap(True)
        l.addWidget(self.sep_status)

        # Results placeholder
        self.results_container = QWidget()
        self.results_layout = QVBoxLayout(self.results_container)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        l.addWidget(self.results_container)

        # Model status banner on separation page
        self.sep_model_status = QLabel("🔄 Loading AI model… please wait.")
        self.sep_model_status.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.sep_model_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sep_model_status.setWordWrap(True)
        self.sep_model_status.setStyleSheet(f"""
            background: rgba(124,92,240,0.08);
            color: {COLOR_ACCENT_SOFT};
            border: 1px solid rgba(124,92,240,0.18);
            border-radius: 8px;
            padding: 8px;
            font-family: 'Inter';
        """)
        l.addWidget(self.sep_model_status)

        # Retry button shown only when model load fails
        self._retry_model_btn = QPushButton("🔄  Retry Model Load")
        self._retry_model_btn.setFixedHeight(38)
        self._retry_model_btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self._retry_model_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(239,68,68,0.15); color: #EF4444;
                border: 1px solid rgba(239,68,68,0.35); border-radius: 9px;
            }}
            QPushButton:hover {{ background: rgba(239,68,68,0.28); }}
        """)
        self._retry_model_btn.setVisible(False)
        self._retry_model_btn.clicked.connect(self._retry_model_load)
        l.addWidget(self._retry_model_btn)

        l.addStretch()

        # Wrap in a page widget that centers the inner form
        page = QWidget()
        page_layout = QHBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(self._wrap_scroll(inner))
        return page

    # ── History page ──────────────────────────────────────────────────────────
    def _make_history_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(32, 32, 32, 32)
        l.setSpacing(12)

        title = QLabel("▤ Separation History")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)

        sub = QLabel("All your past separations — click 'Play Stems' to listen again.")
        sub.setFont(QFont("Segoe UI", 11))
        sub.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        sub.setWordWrap(True)
        l.addWidget(sub)

        self.history_container = QWidget()
        self.history_list_layout = QVBoxLayout(self.history_container)
        self.history_list_layout.setContentsMargins(0, 0, 0, 0)
        self.history_list_layout.setSpacing(10)
        l.addWidget(self.history_container)
        l.addStretch()
        return self._wrap_scroll(inner)

    def _refresh_history(self):
        # Use setParent(None) for immediate removal — avoids ghost widgets
        while self.history_list_layout.count():
            item = self.history_list_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        records = self.db.get_user_history(self.user['id'])
        if not records:
            empty = QLabel("No separations yet. Start by uploading an audio file!")
            empty.setFont(QFont("Segoe UI", 12))
            empty.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            self.history_list_layout.addWidget(empty)
            return

        for rec in records:
            card = _HistoryCard(rec)
            self.history_list_layout.addWidget(card)

    # ── Profile page ──────────────────────────────────────────────────────────
    def _make_profile_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(20)

        title = QLabel("▤ Profile & Settings")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)

        # ── Account Info card ────────────────────────────────────────────────
        info_card = QFrame()
        info_card.setStyleSheet(f"background: {COLOR_BG_CARD}; border-radius: 14px; border: 1px solid {COLOR_BORDER};")
        ic = QVBoxLayout(info_card)
        ic.setContentsMargins(28, 22, 28, 22)
        ic.setSpacing(12)
        ic_title = QLabel("Account Information")
        ic_title.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        ic_title.setStyleSheet(f"color: {COLOR_ACCENT_SOFT}; letter-spacing: 0.3px;")
        ic.addWidget(ic_title)

        self.profile_labels = {}
        fields = [
            ("👤 Username", self.user['username']),
            ("✉  Email",    self.user.get('email', '—') or '—'),
            ("🏷  Role",     self.user['role'].capitalize()),
            ("💰 Credits",  str(self.user['credits'])),
            ("📅 Joined",   self.user.get('created_at', '—')[:10]),
        ]
        for key, val in fields:
            row = QHBoxLayout()
            k = QLabel(f"{key}:")
            k.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            k.setFixedWidth(140)
            k.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            v = QLabel(val)
            v.setFont(QFont("Inter", 11))
            v.setStyleSheet(f"color: {COLOR_TEXT};")
            self.profile_labels[key] = v
            row.addWidget(k)
            row.addWidget(v)
            row.addStretch()
            ic.addLayout(row)
        l.addWidget(info_card)

        # ── Change Email card ────────────────────────────────────────────────
        email_card = QFrame()
        email_card.setStyleSheet(f"background: {COLOR_BG_CARD}; border-radius: 14px; border: 1px solid {COLOR_BORDER};")
        ec = QVBoxLayout(email_card)
        ec.setContentsMargins(28, 22, 28, 22)
        ec.setSpacing(10)
        ec_title = QLabel("Change Email")
        ec_title.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        ec_title.setStyleSheet(f"color: {COLOR_ACCENT_SOFT}; letter-spacing: 0.3px;")
        ec.addWidget(ec_title)

        self.new_email_input = QLineEdit()
        self.new_email_input.setPlaceholderText("New email address")
        self.new_email_input.setFixedHeight(40)
        self.new_email_input.setStyleSheet(self._input_style())
        ec.addWidget(self.new_email_input)

        self.email_msg = QLabel("")
        self.email_msg.setFont(QFont("Segoe UI", 10))
        ec.addWidget(self.email_msg)

        save_email_btn = QPushButton("Save Email")
        save_email_btn.setFixedHeight(36)
        save_email_btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        save_email_btn.setStyleSheet(self._btn_style())
        save_email_btn.clicked.connect(self._change_email)
        ec.addWidget(save_email_btn)
        l.addWidget(email_card)

        # ── Change Password card ─────────────────────────────────────────────
        pw_card = QFrame()
        pw_card.setStyleSheet(f"background: {COLOR_BG_CARD}; border-radius: 14px; border: 1px solid {COLOR_BORDER};")
        pc = QVBoxLayout(pw_card)
        pc.setContentsMargins(28, 22, 28, 22)
        pc.setSpacing(10)
        pc_title = QLabel("Change Password")
        pc_title.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        pc_title.setStyleSheet(f"color: {COLOR_ACCENT_SOFT}; letter-spacing: 0.3px;")
        pc.addWidget(pc_title)

        self.current_pw_input = QLineEdit()
        self.current_pw_input.setPlaceholderText("Current password")
        self.current_pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.current_pw_input.setFixedHeight(40)
        self.current_pw_input.setStyleSheet(self._input_style())
        pc.addWidget(self.current_pw_input)

        self.new_pw_input = QLineEdit()
        self.new_pw_input.setPlaceholderText("New password (min 4 characters)")
        self.new_pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pw_input.setFixedHeight(40)
        self.new_pw_input.setStyleSheet(self._input_style())
        pc.addWidget(self.new_pw_input)

        self.confirm_pw_input = QLineEdit()
        self.confirm_pw_input.setPlaceholderText("Confirm new password")
        self.confirm_pw_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_pw_input.setFixedHeight(40)
        self.confirm_pw_input.setStyleSheet(self._input_style())
        self.confirm_pw_input.returnPressed.connect(self._change_password)
        pc.addWidget(self.confirm_pw_input)

        self.pw_msg = QLabel("")
        self.pw_msg.setFont(QFont("Segoe UI", 10))
        pc.addWidget(self.pw_msg)

        change_pw_btn = QPushButton("Update Password")
        change_pw_btn.setFixedHeight(36)
        change_pw_btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        change_pw_btn.setStyleSheet(self._btn_style())
        change_pw_btn.clicked.connect(self._change_password)
        pc.addWidget(change_pw_btn)
        l.addWidget(pw_card)

        # ── Account Stats card ───────────────────────────────────────────────
        stats_card = QFrame()
        stats_card.setStyleSheet(f"background: {COLOR_BG_CARD}; border-radius: 14px; border: 1px solid {COLOR_BORDER};")
        sc = QVBoxLayout(stats_card)
        sc.setContentsMargins(28, 22, 28, 22)
        sc.setSpacing(10)
        sc_title = QLabel("Account Stats")
        sc_title.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        sc_title.setStyleSheet(f"color: {COLOR_ACCENT_SOFT}; letter-spacing: 0.3px;")
        sc.addWidget(sc_title)

        hist = self.db.get_user_history(self.user['id'])
        payments = self.db.get_user_payments(self.user['id'])
        credits_spent = sum(h['credits_used'] for h in hist)
        credits_bought = sum(p['credits_purchased'] for p in payments)

        stats = [
            ("🎵 Songs Separated",  str(len(hist))),
            ("⭐ Credits Spent",     str(credits_spent)),
            ("💳 Credits Purchased", str(credits_bought)),
        ]
        for label, value in stats:
            row = QHBoxLayout()
            k = QLabel(f"{label}:")
            k.setFont(QFont("Inter", 10))
            k.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            k.setFixedWidth(200)
            v = QLabel(value)
            v.setFont(QFont("Inter", 11, QFont.Weight.Bold))
            v.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
            row.addWidget(k)
            row.addWidget(v)
            row.addStretch()
            sc.addLayout(row)
        l.addWidget(stats_card)

        # ── Logout button ────────────────────────────────────────────────────
        logout_btn = QPushButton("→  Sign Out from Account")
        logout_btn.setFixedHeight(40)
        logout_btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        logout_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {COLOR_TEXT_MUTED};
                border: 1px solid {COLOR_BORDER}; border-radius: 10px;
            }}
            QPushButton:hover {{ background: rgba(239,68,68,0.10); color: #EF4444; border: 1px solid rgba(239,68,68,0.25); }}
        """)
        logout_btn.clicked.connect(self._logout)
        l.addWidget(logout_btn)

        l.addStretch()
        return self._wrap_scroll(inner)

    # ── Profile helpers ────────────────────────────────────────────────────────
    def _input_style(self):
        return f"""
            QLineEdit {{
                background: {COLOR_BG_DARK}; color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER}; border-radius: 8px;
                padding: 8px 12px; font-size: 12px; font-family: 'Inter', 'Segoe UI';
            }}
            QLineEdit:focus {{ border: 1px solid {COLOR_ACCENT}; }}
            QLineEdit::placeholder {{ color: {COLOR_TEXT_MUTED}; }}
        """

    def _btn_style(self):
        return f"""
            QPushButton {{
                background: {COLOR_ACCENT};
                color: white; border-radius: 8px; border: none;
            }}
            QPushButton:hover {{ background: {COLOR_ACCENT_SOFT}; color: #12121C; }}
        """

    def _change_email(self):
        new_email = self.new_email_input.text().strip()
        if not new_email or '@' not in new_email:
            self.email_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.email_msg.setText("Please enter a valid email address.")
            return
        ok, msg = self.db.update_email(self.user['id'], new_email)
        if ok:
            self.user['email'] = new_email
            self.new_email_input.clear()
            self.email_msg.setStyleSheet("color: #4CAF50;")
            self.email_msg.setText(f"✅ {msg}")
            if "✉  Email" in self.profile_labels:
                self.profile_labels["✉  Email"].setText(new_email)
        else:
            self.email_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.email_msg.setText(f"❌ {msg}")

    def _change_password(self):
        current = self.current_pw_input.text()
        new_pw  = self.new_pw_input.text()
        confirm = self.confirm_pw_input.text()
        if not current or not new_pw:
            self.pw_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.pw_msg.setText("All fields are required.")
            return
        if len(new_pw) < 4:
            self.pw_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.pw_msg.setText("New password must be at least 4 characters.")
            return
        if new_pw != confirm:
            self.pw_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.pw_msg.setText("New passwords do not match.")
            return
        ok, msg = self.db.change_password(self.user['id'], current, new_pw)
        if ok:
            self.current_pw_input.clear()
            self.new_pw_input.clear()
            self.confirm_pw_input.clear()
            self.pw_msg.setStyleSheet("color: #4CAF50;")
            self.pw_msg.setText(f"✅ {msg}")
        else:
            self.pw_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.pw_msg.setText(f"❌ {msg}")

    def _refresh_profile(self):
        fresh = self.db.get_user(self.user['id'])
        if fresh:
            self.user.update(fresh)
            if "💰 Credits" in self.profile_labels:
                self.profile_labels["💰 Credits"].setText(str(self.user['credits']))
            if "✉  Email" in self.profile_labels:
                self.profile_labels["✉  Email"].setText(self.user.get('email', '—') or '—')
            self.credits_lbl.setText(f"💰 {self.user['credits']} credits")

    # ── Feedback page ─────────────────────────────────────────────────────────
    def _make_feedback_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(16)

        title = QLabel("▤ Send Feedback")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)

        sub = QLabel("We'd love to hear your thoughts! Share your experience below.")
        sub.setFont(QFont("Segoe UI", 12))
        sub.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        l.addWidget(sub)

        self.feedback_text = QTextEdit()
        self.feedback_text.setPlaceholderText("Type your feedback here…")
        self.feedback_text.setMinimumHeight(180)
        self.feedback_text.setStyleSheet(f"""
            QTextEdit {{
                background: {COLOR_BG_CARD}; color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER}; border-radius: 10px;
                padding: 12px; font-size: 12px; font-family: 'Inter', 'Segoe UI';
            }}
            QTextEdit:focus {{ border: 1px solid {COLOR_ACCENT}; }}
        """)
        l.addWidget(self.feedback_text)

        self.feedback_msg = QLabel("")
        self.feedback_msg.setFont(QFont("Segoe UI", 10))
        l.addWidget(self.feedback_msg)

        send_btn = QPushButton("Submit Feedback")
        send_btn.setFixedHeight(44)
        send_btn.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {COLOR_ACCENT}; color: white; border-radius: 10px; border: none;
            }}
            QPushButton:hover {{ background: {COLOR_ACCENT_SOFT}; color: #12121C; }}
        """)
        send_btn.clicked.connect(self._submit_feedback)
        l.addWidget(send_btn)
        l.addStretch()
        return self._wrap_scroll(inner)

    def _submit_feedback(self):
        text = self.feedback_text.toPlainText().strip()
        if not text:
            self.feedback_msg.setStyleSheet(f"color: {COLOR_CORAL};")
            self.feedback_msg.setText("Please enter some feedback before submitting.")
            return
        self.db.save_feedback(self.user['id'], text)
        self.feedback_text.clear()
        self.feedback_msg.setStyleSheet(f"color: #4CAF50;")
        self.feedback_msg.setText("✅ Thank you for your feedback!")

    # ── Help page ─────────────────────────────────────────────────────────────
    def _make_help_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(20)

        title = QLabel("▤ Help & FAQ")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)

        faqs = [
            ("How does audio separation work?",
             "Our AI uses a U-Net deep learning model to separate your audio into up to 4 stems: vocals, drums, bass, and other instruments."),
            ("How much does it cost?",
             "Single stem = 1 credit. All 4 stems = 2 credits. New users get 5 free credits on registration."),
            ("What audio formats are supported?",
             "WAV and MP3 files are supported. For best results, use high-quality WAV files."),
            ("How long does separation take?",
             "Typically 30–90 seconds depending on song length and your hardware."),
            ("How do I get more credits?",
             "Click 'Recharge Credits' in the sidebar and contact the admin."),
        ]

        contact_email = self.db.get_setting('contact_email', 'pashtesahil10@gmail.com')
        contact_phone = self.db.get_setting('contact_phone', '+91-9876543210')

        for q, a in faqs:
            card = QFrame()
            card.setStyleSheet(f"background: {COLOR_BG_CARD}; border-radius: 12px; border: 1px solid {COLOR_BORDER};")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 16, 20, 16)
            cl.setSpacing(8)
            q_lbl = QLabel(f"Q: {q}")
            q_lbl.setFont(QFont("Inter", 11, QFont.Weight.Bold))
            q_lbl.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
            q_lbl.setWordWrap(True)
            a_lbl = QLabel(f"A: {a}")
            a_lbl.setFont(QFont("Inter", 11))
            a_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            a_lbl.setWordWrap(True)
            cl.addWidget(q_lbl)
            cl.addWidget(a_lbl)
            l.addWidget(card)

        contact_card = QFrame()
        contact_card.setStyleSheet(f"background: {COLOR_BG_CARD}; border-radius: 12px; border: 1px solid {COLOR_BORDER};")
        ccl = QVBoxLayout(contact_card)
        ccl.setContentsMargins(20, 16, 20, 16)
        ct = QLabel("▤ Need more help?")
        ct.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        ct.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
        ce = QLabel(f"✉  {contact_email}")
        ce.setFont(QFont("Segoe UI", 11))
        ce.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        cp = QLabel(f"📱  {contact_phone}")
        cp.setFont(QFont("Segoe UI", 11))
        cp.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        ccl.addWidget(ct)
        ccl.addWidget(ce)
        ccl.addWidget(cp)
        l.addWidget(contact_card)
        l.addStretch()
        return self._wrap_scroll(inner)

    # ── Contact page ──────────────────────────────────────────────────────────
    def _make_contact_page(self):
        inner = QWidget()
        l = QVBoxLayout(inner)
        l.setContentsMargins(36, 36, 36, 36)
        l.setSpacing(20)

        title = QLabel("▤ Contact Us")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT}; letter-spacing: -0.3px;")
        l.addWidget(title)

        card = QFrame()
        card.setStyleSheet(f"background: {COLOR_BG_CARD}; border-radius: 16px; border: 1px solid {COLOR_BORDER};")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(30, 28, 30, 28)
        cl.setSpacing(16)

        contact_email = self.db.get_setting('contact_email', 'pashtesahil10@gmail.com')
        contact_phone = self.db.get_setting('contact_phone', '+91-9876543210')

        for icon, label, value in [("\u2709", "Email", contact_email),
                                    ("\u25a4", "Phone", contact_phone),
                                    ("\u25a4", "Support Hours", "Mon–Sat, 10:00 AM – 6:00 PM IST")]:
            row = QHBoxLayout()
            ic = QLabel(f"{icon}  {label}:")
            ic.setFont(QFont("Inter", 12, QFont.Weight.Bold))
            ic.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
            ic.setFixedWidth(160)
            val = QLabel(value)
            val.setFont(QFont("Inter", 12))
            val.setStyleSheet(f"color: {COLOR_TEXT};")
            row.addWidget(ic)
            row.addWidget(val)
            row.addStretch()
            cl.addLayout(row)

        l.addWidget(card)
        l.addStretch()
        return self._wrap_scroll(inner)

    # ── Model loading ─────────────────────────────────────────────────────────
    def _start_model_load(self):
        # Windows requires that PyTorch DLLs (c10.dll etc.) are first loaded on
        # the MAIN thread. Importing torch here (Qt event loop is already running,
        # message pump is alive) satisfies that requirement before the worker
        # thread runs. This prevents WinError 1114.
        try:
            import torch  # noqa: F401 – side-effect: loads DLLs on main thread
        except Exception:
            pass  # If torch is missing entirely, the thread will report the error

        self._retry_model_btn.setVisible(False)
        self.sep_model_status.setText("🔄 Loading AI model… please wait.")
        self.sep_model_status.setStyleSheet(f"""
            background: rgba(124,92,240,0.08); color: {COLOR_ACCENT_SOFT};
            border: 1px solid rgba(124,92,240,0.18);
            border-radius: 8px; padding: 8px; font-family: 'Inter';
        """)
        self.model_status_lbl.setText("🔄 Loading AI model in background…")
        self.model_status_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")

        # Start timeout watchdog (90 seconds)
        self._model_timeout_timer.start(90000)

        self.model_thread = ModelLoaderThread()
        self.model_thread.finished.connect(self._on_model_loaded)
        self.model_thread.error.connect(self._on_model_error)
        self.model_thread.start()

    def _retry_model_load(self):
        """Retry loading the model after a failure."""
        if self.model_thread and self.model_thread.isRunning():
            return  # already loading
        self.model = None
        self.separate_btn.setEnabled(False)
        # Restart poll timer
        if not self._poll_timer.isActive():
            self._poll_timer.start()
        self._start_model_load()

    def _on_model_timeout(self):
        """Called if model hasn't loaded in 90 seconds."""
        if self.model is None:
            self._on_model_error("Model load timed out after 90 seconds. Click Retry.")

    def _on_model_loaded(self, model):
        self._model_timeout_timer.stop()
        self.model = model
        self.model_status_lbl.setText("✅ AI model ready!")
        self.model_status_lbl.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
        self.sep_model_status.setText("✓ AI model ready — select a file and click Start Separation.")
        self.sep_model_status.setStyleSheet(f"""
            background: rgba(124,92,240,0.10); color: {COLOR_ACCENT_SOFT};
            border: 1px solid rgba(124,92,240,0.25);
            border-radius: 8px; padding: 8px; font-family: 'Inter';
        """)
        self._retry_model_btn.setVisible(False)
        if self.current_file:
            self.separate_btn.setEnabled(True)

    def _on_model_error(self, err):
        self._model_timeout_timer.stop()
        # Show only first 200 chars to not overflow UI
        short_err = str(err)[:200]
        self.model_status_lbl.setText(f"⚠ Model error — click Retry in Separate Audio tab")
        self.model_status_lbl.setStyleSheet(f"color: {COLOR_CORAL};")
        self.sep_model_status.setText(f"❌ Model failed to load:\n{short_err}\n\nClick 'Retry Model Load' below.")
        self.sep_model_status.setStyleSheet(f"""
            background: rgba(239,68,68,0.10);
            color: #EF4444;
            border: 1px solid rgba(239,68,68,0.35);
            border-radius: 8px; padding: 8px;
        """)
        self._retry_model_btn.setVisible(True)

    # ── File selection ────────────────────────────────────────────────────────
    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", "", "Audio Files (*.wav *.mp3 *.flac *.ogg)"
        )
        if path:
            self._file_selected(path)

    def _file_selected(self, path):
        self.current_file = path
        self.file_lbl.setText(f"  {os.path.basename(path)}")
        self.file_lbl.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
        if self.model:
            self.separate_btn.setEnabled(True)
        else:
            self.sep_model_status.setText("File selected. Waiting for AI model to finish loading…")
            self.sep_model_status.setStyleSheet(f"""
                background: rgba(124,92,240,0.09); color: {COLOR_ACCENT_SOFT};
                border: 1px solid rgba(124,92,240,0.22);
                border-radius: 8px; padding: 8px;
            """)

    def _poll_ready(self):
        """Every 500 ms — enable button as soon as both model and file are ready."""
        if self.model and self.current_file and not self.separate_btn.isEnabled():
            self.separate_btn.setEnabled(True)
            self.sep_model_status.setText("✓ Ready! Click Start Separation.")
            self.sep_model_status.setStyleSheet(f"""
                background: rgba(124,92,240,0.10); color: {COLOR_ACCENT_SOFT};
                border: 1px solid rgba(124,92,240,0.25);
                border-radius: 8px; padding: 8px;
            """)
            self._poll_timer.stop()

    # ── Credits helper ────────────────────────────────────────────────────────
    def _sync_credits(self):
        """Always read credits from DB so UI never shows stale values."""
        fresh = self.db.get_user(self.user['id'])
        if fresh:
            self.user['credits'] = fresh['credits']
            self.credits_lbl.setText(f"◈  {self.user['credits']} credits")
        return fresh

    def _refresh_home_stats(self):
        """Live-refresh the three stat cards on the Home page."""
        if not hasattr(self, '_home_stat_vals'):
            return
        fresh = self.db.get_user(self.user['id'])
        if fresh:
            self.user['credits'] = fresh['credits']
        hist = self.db.get_user_history(self.user['id'])
        updates = {
            "Songs Separated": str(len(hist)),
            "Credits Left":    str(self.user['credits']),
            "Credits Used":    str(sum(h['credits_used'] for h in hist)),
        }
        for label, value in updates.items():
            lbl_widget = self._home_stat_vals.get(label)
            if lbl_widget:
                lbl_widget.setText(value)

    # ── Separation ────────────────────────────────────────────────────────────
    def _start_separation(self):
        if not self.current_file or not self.model:
            return
        # Guard: block re-entry while a separation is already running
        if self.sep_thread is not None and self.sep_thread.isRunning():
            self.sep_status.setText("Separation already in progress…")
            self.sep_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            return

        # Determine stems & cost
        mode = self.mode_combo.currentIndex()
        if mode == 0:
            selected = list(range(4))
            cost = ALL_STEMS_COST
            label = "All 4 Stems"
        else:
            selected = [mode - 1]
            cost = SINGLE_STEM_COST
            label = STEM_NAMES[mode - 1].capitalize()

        # Always fetch fresh credits from DB — never rely on stale in-memory value
        fresh = self._sync_credits()
        if not fresh or fresh['credits'] < cost:
            have = fresh['credits'] if fresh else 0
            self.sep_status.setText(f"Insufficient credits! Need {cost}, have {have}.")
            self.sep_status.setStyleSheet(f"color: {COLOR_CORAL};")
            return

        if not self.db.deduct_credits(self.user['id'], cost):
            self.sep_status.setText("Could not deduct credits.")
            self.sep_status.setStyleSheet(f"color: {COLOR_CORAL};")
            return

        # Update sidebar badge immediately — user gets instant confirmation
        self.user['credits'] = fresh['credits'] - cost
        self.credits_lbl.setText(f"◈  {self.user['credits']} credits")

        self.sep_progress.setVisible(True)
        self.sep_progress.setValue(0)
        self._sep_wave.setVisible(True)
        self.separate_btn.setEnabled(False)
        # Show explicit deduction notice so user knows credits were charged
        self.sep_status.setText(
            f"✓ {cost} credit{'s' if cost > 1 else ''} deducted — starting separation…"
        )
        self.sep_status.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")

        self._sep_cost = cost
        self.sep_thread = SeparationThread(self.model, self.current_file, selected, cost)
        self.sep_thread.progress.connect(self._on_sep_progress)
        self.sep_thread.finished.connect(lambda r, p: self._on_sep_done(r, p, label, cost))
        self.sep_thread.error.connect(self._on_sep_error)
        self.sep_thread.start()

    def _on_sep_progress(self, pct, msg):
        self.sep_progress.setValue(pct)
        self.sep_status.setText(msg)
        self.sep_status.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")

    def _on_sep_done(self, results, output_paths, label, cost):
        self.sep_progress.setValue(100)
        self._sep_wave.setVisible(False)
        self.sep_status.setText("✓ Separation complete!")
        self.sep_status.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
        self.separate_btn.setEnabled(True)
        QTimer.singleShot(1200, lambda: self.sep_progress.setVisible(False))
        if self.sep_thread:
            self.sep_thread.deleteLater()
            self.sep_thread = None
        self._sync_credits()
        self.db.record_separation(
            self.user['id'], os.path.basename(self.current_file),
            label, cost, output_paths=output_paths
        )
        self._show_results(results, output_paths)

    def _on_sep_error(self, err):
        self.sep_progress.setVisible(False)
        self._sep_wave.setVisible(False)
        self.sep_status.setText(f"Error: {err}")
        self.sep_status.setStyleSheet(f"color: {COLOR_CORAL};")
        self.separate_btn.setEnabled(True)
        if self.sep_thread:
            self.sep_thread.deleteLater()
            self.sep_thread = None
        refund = getattr(self, '_sep_cost', 1)
        self.db.update_credits(self.user['id'], refund)
        self._sync_credits()

    def _show_results(self, results, output_paths):
        """Stop any playing audio, remove old widgets safely, then show new stems."""
        # Stop all QMediaPlayer instances BEFORE destroying their parent widget
        # — skipping this step causes a crash when separating a 2nd song.
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w:
                if hasattr(w, 'stop_all'):
                    try:
                        w.stop_all()
                    except Exception:
                        pass
                w.deleteLater()   # safe async deletion by Qt event loop
        try:
            from stem_player import StemResultsWidget
            self.results_layout.addWidget(StemResultsWidget(results, output_paths))
        except Exception as e:
            err_lbl = QLabel(f"⚠ Could not display results: {e}")
            err_lbl.setStyleSheet("color: #FF6B6B; font-size: 12px;")
            err_lbl.setWordWrap(True)
            self.results_layout.addWidget(err_lbl)

    # ── Load previous results (threaded) ──────────────────────────────────────
    def _load_previous_results(self):
        """Show song-picker dialog then load stems on a background thread."""
        from config import OUTPUT_DIR, STEM_NAMES
        from PyQt6.QtWidgets import QDialog, QListWidget, QDialogButtonBox

        groups = {}  # base_name -> {stem_name: path}
        try:
            files = sorted(os.listdir(OUTPUT_DIR))
        except Exception:
            files = []
        for fn in files:
            if not fn.endswith('.wav'):
                continue
            for stem in STEM_NAMES:
                suffix = f"_{stem}.wav"
                if fn.endswith(suffix):
                    base = fn[: -len(suffix)]
                    groups.setdefault(base, {})[stem] = os.path.join(OUTPUT_DIR, fn)
                    break

        if not groups:
            self.sep_status.setText("⚠ No previous results found in output folder.")
            self.sep_status.setStyleSheet(f"color: {COLOR_CORAL};")
            return

        # Always show song-picker dialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Choose a Previous Separation")
        dlg.setMinimumWidth(500)
        dlg.setStyleSheet(f"background:{COLOR_BG_DARK}; color:{COLOR_TEXT};")
        dv = QVBoxLayout(dlg)
        dv.setContentsMargins(18, 18, 18, 18)
        dv.setSpacing(12)

        hdr = QLabel("▤ Select a song to load its stems:")
        hdr.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
        dv.addWidget(hdr)

        lst = QListWidget()
        lst.setStyleSheet(f"""
            QListWidget {{
                background: {COLOR_BG_CARD}; color: {COLOR_TEXT};
                border: 1px solid {COLOR_BORDER}; border-radius: 8px;
                font-size: 12px; font-family: 'Inter'; padding: 4px;
            }}
            QListWidget::item {{ padding: 8px 6px; }}
            QListWidget::item:selected {{
                background: rgba(124,92,240,0.20); color: {COLOR_ACCENT_SOFT};
            }}
        """)
        for base, stems in groups.items():
            stem_names = ", ".join(stems.keys())
            lst.addItem(f"{base}  —  [{stem_names}]")
        lst.setCurrentRow(0)
        dv.addWidget(lst)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.setStyleSheet(f"""
            QPushButton {{
                background: {COLOR_ACCENT}; color: white;
                border-radius: 8px; padding: 6px 18px; border: none;
            }}
            QPushButton:hover {{ background: {COLOR_ACCENT_SOFT}; color: #12121C; }}
        """)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dv.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted or lst.currentRow() < 0:
            return

        base_name  = list(groups.keys())[lst.currentRow()]
        stem_paths = groups[base_name]

        # Show progress and load off the main thread
        self.sep_progress.setVisible(True)
        self.sep_progress.setValue(0)
        self.sep_status.setText("🔄 Loading stems…")
        self.sep_status.setStyleSheet(f"color: {COLOR_AMBER};")

        self.load_thread = LoadPreviousThread(stem_paths, base_name)
        self.load_thread.progress.connect(lambda p, m: (
            self.sep_progress.setValue(p),
            self.sep_status.setText(m)
        ))
        self.load_thread.finished.connect(self._on_load_previous_done)
        self.load_thread.error.connect(self._on_load_previous_error)
        self.load_thread.start()

    def _on_load_previous_done(self, results, output_paths, base_name):
        self.sep_progress.setVisible(False)
        self.sep_status.setText(f"✅ Loaded: {base_name}")
        self.sep_status.setStyleSheet("color: #4CAF50;")
        self._show_results(results, output_paths)

    def _on_load_previous_error(self, err):
        self.sep_progress.setVisible(False)
        self.sep_status.setText(f"❌ Load failed: {err}")
        self.sep_status.setStyleSheet(f"color: {COLOR_CORAL};")

    def _open_payment(self):
        from payment_window import PaymentWindow
        dlg = PaymentWindow(self.user, self.db, self)  # db must be 2nd arg
        dlg.credits_added.connect(self._on_credits_added)
        dlg.exec()
        self._sync_credits()

    def _on_credits_added(self, amount):
        """Called immediately when PaymentWindow emits credits_added signal."""
        self._sync_credits()

    def closeEvent(self, event):
        """Stop all timers and threads gracefully before closing."""
        # Stop the animated waveform timer
        if hasattr(self, '_sep_wave'):
            try:
                self._sep_wave.stop()
            except Exception:
                pass
        # Stop poll and timeout timers
        for attr in ('_poll_timer', '_model_timeout_timer'):
            t = getattr(self, attr, None)
            if t:
                try:
                    t.stop()
                except Exception:
                    pass
        # Terminate background threads if still running
        for attr in ('model_thread', 'sep_thread', 'load_thread'):
            t = getattr(self, attr, None)
            if t and t.isRunning():
                try:
                    t.quit()
                    t.wait(800)
                except Exception:
                    pass
        super().closeEvent(event)

    def _logout(self):
        self.controller.logout()


# ── History Card ──────────────────────────────────────────────────────────────

class _HistoryCard(QFrame):
    """One row in the history list with an expandable stem player."""

    def __init__(self, rec: dict, parent=None):
        super().__init__(parent)
        self.rec = rec
        self._stems_visible = False
        self._stem_widget = None

        self.setStyleSheet(f"""
            QFrame {{
                background: {COLOR_BG_CARD};
                border-radius: 12px;
                border: 1px solid {COLOR_BORDER};
            }}
        """)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # ── Top info row ──────────────────────────────────────────────────
        top = QWidget()
        top.setStyleSheet("background: transparent; border: none;")
        rl = QHBoxLayout(top)
        rl.setContentsMargins(16, 12, 16, 12)
        rl.setSpacing(10)

        fn = QLabel(f"🎵  {rec['filename']}")
        fn.setFont(QFont("Segoe UI", 11))
        fn.setStyleSheet(f"color: {COLOR_TEXT};")
        fn.setWordWrap(True)

        stype = QLabel(rec['separation_type'])
        stype.setFont(QFont("Segoe UI", 10))
        stype.setStyleSheet(f"color: {COLOR_AMBER};")
        stype.setFixedWidth(110)

        cr = QLabel(f"◈ {rec['credits_used']}")
        cr.setFont(QFont("Inter", 10))
        cr.setStyleSheet(f"color: {COLOR_ACCENT_SOFT};")
        cr.setFixedWidth(55)

        ts = QLabel(rec['timestamp'][:16])
        ts.setFont(QFont("Segoe UI", 9))
        ts.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        ts.setFixedWidth(115)

        # Play stems button — only shown when output paths are stored
        output_paths = rec.get('output_paths', {})
        valid_paths = {s: p for s, p in output_paths.items() if p and os.path.exists(p)}

        self._play_btn = QPushButton("▶  Play Stems")
        self._play_btn.setFixedHeight(30)
        self._play_btn.setFixedWidth(110)
        self._play_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._play_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(124,92,240,0.10);
                color: {COLOR_ACCENT_SOFT};
                border: 1px solid rgba(124,92,240,0.22);
                border-radius: 7px;
            }}
            QPushButton:hover {{ background: rgba(124,92,240,0.22); }}
        """)
        self._play_btn.setVisible(bool(valid_paths))
        self._play_btn.clicked.connect(self._toggle_stems)

        rl.addWidget(fn, 3)
        rl.addWidget(stype)
        rl.addWidget(cr)
        rl.addWidget(ts)
        rl.addWidget(self._play_btn)
        self._outer.addWidget(top)

        # Store valid paths for lazy loading
        self._valid_paths = valid_paths

    def _toggle_stems(self):
        if self._stems_visible:
            if self._stem_widget:
                self._stem_widget.setParent(None)
                self._stem_widget = None
            self._stems_visible = False
            self._play_btn.setText("▶  Play Stems")
        else:
            self._load_stems_async()

    def _load_stems_async(self):
        """Kick off a background thread to load stem WAV files, then render players."""
        if not self._valid_paths:
            return
        # Prevent double-clicks while loading
        self._play_btn.setEnabled(False)
        self._play_btn.setText("⏳ Loading…")

        self._load_thread = LoadPreviousThread(self._valid_paths, "")
        self._load_thread.finished.connect(self._on_stems_loaded)
        self._load_thread.error.connect(self._on_stems_error)
        self._load_thread.start()

    def _on_stems_loaded(self, results, output_paths, _base_name):
        self._play_btn.setEnabled(True)
        if not results:
            self._play_btn.setText("▶  Play Stems")
            return
        try:
            from stem_player import StemResultsWidget
            self._stem_widget = StemResultsWidget(results, output_paths)
            self._outer.addWidget(self._stem_widget)
            self._stems_visible = True
            self._play_btn.setText("⏹  Hide Stems")
        except Exception:
            self._play_btn.setText("▶  Play Stems")

    def _on_stems_error(self, err):
        self._play_btn.setEnabled(True)
        self._play_btn.setText("▶  Play Stems")


# ── Drop Zone ─────────────────────────────────────────────────────────────────

class _DropZone(QFrame):
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.setStyleSheet(f"""
            QFrame {{
                background: {COLOR_BG_CARD};
                border: 1px dashed rgba(124,92,240,0.35);
                border-radius: 14px;
            }}
            QFrame:hover {{
                border: 1px dashed {COLOR_ACCENT};
                background: rgba(124,92,240,0.06);
            }}
        """)
        l = QVBoxLayout(self)
        lbl = QLabel("◎  Drag & Drop Audio File Here")
        lbl.setFont(QFont("Inter", 13))
        lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("WAV • MP3 • FLAC • OGG")
        sub.setFont(QFont("Inter", 10))
        sub.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        l.addWidget(lbl)
        l.addWidget(sub)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self.setStyleSheet(f"""
                QFrame {{
                    background: rgba(124,92,240,0.10);
                    border: 1px solid {COLOR_ACCENT};
                    border-radius: 14px;
                }}
            """)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setStyleSheet(f"""
            QFrame {{
                background: {COLOR_BG_CARD};
                border: 1px dashed rgba(124,92,240,0.35);
                border-radius: 14px;
            }}
        """)

    def dropEvent(self, event: QDropEvent):
        self.setStyleSheet(f"""
            QFrame {{
                background: {COLOR_BG_CARD};
                border: 1px dashed rgba(124,92,240,0.35);
                border-radius: 14px;
            }}
        """)
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            ext = os.path.splitext(path)[1].lower()
            if ext in ('.wav', '.mp3', '.flac', '.ogg'):
                self.file_dropped.emit(path)
