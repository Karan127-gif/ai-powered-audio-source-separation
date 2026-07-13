"""
stem_player.py — Aurum AI Design System
Stem result cards with per-stem accent colors, waveform visualization,
seek slider, volume control, and download.
"""
import os
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QFrame, QFileDialog, QSizePolicy
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient, QBrush
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from config import (COLOR_BG_DARK, COLOR_BG_CARD, COLOR_BG_SURFACE,
                    COLOR_BORDER, COLOR_TEXT, COLOR_TEXT_MUTED,
                    COLOR_ACCENT, SAMPLE_RATE)

# ── Per-stem Aurum AI accent colors ──────────────────────────────────────────
STEM_PALETTE = {
    "vocals": {"hex": "#7C5CF0", "rgb": (124, 92, 240),  "glow": "#7C5CF033"},  # purple
    "drums":  {"hex": "#F97316", "rgb": (249, 115,  22),  "glow": "#F9731633"},  # orange
    "bass":   {"hex": "#3B82F6", "rgb": ( 59, 130, 246),  "glow": "#3B82F633"},  # blue
    "other":  {"hex": "#10B981", "rgb": ( 16, 185, 129),  "glow": "#10B98133"},  # teal
}
STEM_ICONS = {"vocals": "🎤", "drums": "🥁", "bass": "🎸", "other": "🎹"}

FONT_BODY   = "Inter, Segoe UI, sans-serif"
FONT_MONO   = "JetBrains Mono, Consolas, monospace"


# ── Waveform widget ───────────────────────────────────────────────────────────
class WaveformWidget(QWidget):
    """Renders a high-fidelity stem waveform using the Aurum AI visual style."""

    def __init__(self, audio_data: np.ndarray, color_rgb=(124, 92, 240), parent=None):
        super().__init__(parent)
        data = audio_data.mean(axis=0) if audio_data.ndim > 1 else audio_data
        self.audio_data = data
        self.color_rgb  = color_rgb
        self.setMinimumHeight(80)
        self.setMaximumHeight(90)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._peaks = self._compute_peaks(512)

    def _compute_peaks(self, n=512):
        data  = self.audio_data
        chunk = max(1, len(data) // n)
        peaks = []
        for i in range(n):
            seg = data[i * chunk: (i + 1) * chunk]
            peaks.append(float(np.abs(seg).max()) if len(seg) else 0.0)
        mx = max(peaks) if peaks else 1.0
        return [p / mx for p in peaks] if mx > 0 else peaks

    def paintEvent(self, event):
        try:
            super().paintEvent(event)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h  = self.width(), self.height()
            mid   = h / 2
            r, g, b = self.color_rgb

            # Background with subtle glow tint
            painter.fillRect(0, 0, w, h, QColor(r, g, b, 12))

            # Centre line
            painter.setPen(QPen(QColor(r, g, b, 30), 1))
            painter.drawLine(0, int(mid), w, int(mid))

            # Waveform bars with gradient alpha
            n = len(self._peaks)
            bar_w = max(1, w / n)
            for i, peak in enumerate(self._peaks):
                x     = int(i * bar_w)
                bar_h = max(2, int(peak * mid * 0.88))
                alpha = int(80 + 175 * peak)

                # Gradient: brighter at top, fades to dark
                grad = QLinearGradient(x, int(mid - bar_h), x, int(mid + bar_h))
                grad.setColorAt(0.0, QColor(r, g, b, alpha))
                grad.setColorAt(0.5, QColor(r, g, b, alpha))
                grad.setColorAt(1.0, QColor(r, g, b, alpha // 3))
                painter.fillRect(x, int(mid - bar_h), max(1, int(bar_w - 0.5)),
                                 bar_h * 2, QBrush(grad))
            painter.end()
        except Exception:
            pass


# ── Single stem card ──────────────────────────────────────────────────────────
class StemCard(QFrame):
    """Aurum AI styled stem card: waveform + transport controls + volume."""

    def __init__(self, stem_name: str, audio_data: np.ndarray,
                 output_path: str, parent=None):
        super().__init__(parent)
        self.stem_name   = stem_name
        self.output_path = output_path
        self.audio_mono  = (audio_data.mean(axis=0)
                            if audio_data.ndim > 1 else audio_data)

        pal = STEM_PALETTE.get(stem_name, STEM_PALETTE["other"])
        self.hex_color = pal["hex"]
        self.rgb_color = pal["rgb"]
        self.glow      = pal["glow"]
        r, g, b        = self.rgb_color

        self.player    = QMediaPlayer()
        self.audio_out = QAudioOutput()
        self.player.setAudioOutput(self.audio_out)
        self.audio_out.setVolume(0.85)
        self.player.setSource(QUrl.fromLocalFile(os.path.abspath(output_path)))
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.positionChanged.connect(self._on_position)
        self._seeking = False

        self.setStyleSheet(f"""
            QFrame {{
                background: {COLOR_BG_CARD};
                border-radius: 16px;
                border: 1px solid {self.hex_color}44;
            }}
            QFrame:hover {{
                border: 1px solid {self.hex_color}99;
                background: #1E1E30;
            }}
        """)
        self._build_ui()

    def _build_ui(self):
        r, g, b = self.rgb_color
        layout  = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # ── Header row ────────────────────────────────────────────────────────
        header = QHBoxLayout()

        # Coloured dot + stem name
        dot = QLabel("●")
        dot.setFont(QFont("Inter", 10))
        dot.setStyleSheet(f"color: {self.hex_color};")
        header.addWidget(dot)

        name_lbl = QLabel(f"{STEM_ICONS.get(self.stem_name,'🎵')}  "
                          f"{self.stem_name.capitalize()}")
        name_lbl.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {self.hex_color};")
        header.addWidget(name_lbl)
        header.addStretch()

        # Duration badge
        dur_s = len(self.audio_mono) / SAMPLE_RATE
        dur_lbl = QLabel(f"{int(dur_s//60)}:{int(dur_s%60):02d}")
        dur_lbl.setFont(QFont("JetBrains Mono", 10))
        dur_lbl.setStyleSheet(f"""
            color: {self.hex_color};
            background: rgba({r},{g},{b},0.12);
            border: 1px solid rgba({r},{g},{b},0.3);
            border-radius: 6px; padding: 2px 8px;
        """)
        header.addWidget(dur_lbl)
        layout.addLayout(header)

        # ── Waveform ──────────────────────────────────────────────────────────
        wf = WaveformWidget(self.audio_mono, self.rgb_color)
        wf.setStyleSheet(f"border-radius: 8px; border: 1px solid rgba({r},{g},{b},0.15);")
        layout.addWidget(wf)

        # ── Seek slider ───────────────────────────────────────────────────────
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setFixedHeight(16)
        self.seek_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 3px; background: {COLOR_BORDER}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {self.hex_color}; width: 12px; height: 12px;
                margin: -5px 0; border-radius: 6px;
                border: 2px solid {COLOR_BG_DARK};
            }}
            QSlider::sub-page:horizontal {{
                background: {self.hex_color}; border-radius: 2px;
            }}
        """)
        self.seek_slider.sliderPressed.connect(lambda: setattr(self, '_seeking', True))
        self.seek_slider.sliderReleased.connect(self._seek_end)
        self.seek_slider.valueChanged.connect(self._seek_drag)
        layout.addWidget(self.seek_slider)

        # ── Controls row ──────────────────────────────────────────────────────
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)

        self.play_btn = QPushButton("▶  Play")
        self.play_btn.setFixedHeight(36)
        self.play_btn.setFixedWidth(110)
        self.play_btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self.play_btn.setStyleSheet(f"""
            QPushButton {{
                background: {self.hex_color};
                color: white; border-radius: 9px; border: none;
            }}
            QPushButton:hover {{
                background: rgba({r},{g},{b}, 0.80);
            }}
        """)
        self.play_btn.clicked.connect(self._toggle_play)
        ctrl.addWidget(self.play_btn)

        # Time display
        self.time_lbl = QLabel("0:00")
        self.time_lbl.setFont(QFont("JetBrains Mono", 10))
        self.time_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; min-width: 38px;")
        ctrl.addWidget(self.time_lbl)

        ctrl.addStretch()

        # Volume slider
        vol_icon = QLabel("🔊")
        vol_icon.setFont(QFont("Inter", 10))
        ctrl.addWidget(vol_icon)

        vol_slider = QSlider(Qt.Orientation.Horizontal)
        vol_slider.setRange(0, 100)
        vol_slider.setValue(85)
        vol_slider.setFixedWidth(80)
        vol_slider.setFixedHeight(16)
        vol_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 3px; background: {COLOR_BORDER}; border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {COLOR_TEXT_MUTED}; width: 10px; height: 10px;
                margin: -4px 0; border-radius: 5px;
            }}
            QSlider::sub-page:horizontal {{
                background: {COLOR_TEXT_MUTED}; border-radius: 2px;
            }}
        """)
        vol_slider.valueChanged.connect(
            lambda v: self.audio_out.setVolume(v / 100))
        ctrl.addWidget(vol_slider)

        layout.addLayout(ctrl)

        # ── Download button ───────────────────────────────────────────────────
        dl_btn = QPushButton(
            f"⬇  Export  {self.stem_name.capitalize()}.wav")
        dl_btn.setFixedHeight(36)
        dl_btn.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        dl_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba({r},{g},{b}, 0.10);
                color: {self.hex_color};
                border: 1px solid rgba({r},{g},{b}, 0.35);
                border-radius: 9px;
            }}
            QPushButton:hover {{
                background: rgba({r},{g},{b}, 0.22);
                border: 1px solid {self.hex_color};
            }}
        """)
        dl_btn.clicked.connect(self._download)
        layout.addWidget(dl_btn)

    # ── Playback callbacks ────────────────────────────────────────────────────
    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setText("⏸  Pause" if playing else "▶  Play")

    def _on_position(self, pos_ms):
        if not self._seeking:
            dur = self.player.duration()
            if dur > 0:
                self.seek_slider.setValue(int(pos_ms * 1000 / dur))
            s = pos_ms // 1000
            self.time_lbl.setText(f"{s // 60}:{s % 60:02d}")

    def _seek_end(self):
        dur = self.player.duration()
        if dur > 0:
            self.player.setPosition(int(self.seek_slider.value() * dur / 1000))
        self._seeking = False

    def _seek_drag(self, value):
        if self._seeking:
            dur = self.player.duration()
            if dur > 0:
                self.player.setPosition(int(value * dur / 1000))

    def _download(self):
        dest, _ = QFileDialog.getSaveFileName(
            self, f"Export {self.stem_name.capitalize()}",
            f"{self.stem_name}.wav", "WAV Files (*.wav)"
        )
        if dest:
            import shutil
            shutil.copy2(self.output_path, dest)

    def stop(self):
        try:
            self.player.stop()
        except Exception:
            pass


# ── Results container ─────────────────────────────────────────────────────────
class StemResultsWidget(QWidget):
    """Holds all StemCards in a vertical list with Aurum AI heading."""

    def __init__(self, results: dict, output_paths: dict, parent=None):
        super().__init__(parent)
        self.stem_cards: list[StemCard] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 4)
        layout.setSpacing(14)

        # Heading
        heading = QLabel("🎚  Separated Stems")
        heading.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        heading.setStyleSheet(f"color: {COLOR_ACCENT};")
        layout.addWidget(heading)

        # Sub-heading with AI chip style
        sub = QLabel("✦ AI-Separated  ·  Wiener-filtered  ·  HPSS-guided")
        sub.setFont(QFont("Inter", 10))
        sub.setStyleSheet(f"""
            color: {COLOR_TEXT_MUTED};
            background: rgba(124,92,240,0.08);
            border: 1px solid rgba(124,92,240,0.20);
            border-radius: 6px; padding: 4px 10px;
        """)
        sub.setFixedHeight(26)
        layout.addWidget(sub)

        # Stem cards
        for stem_name, audio_data in results.items():
            path = output_paths.get(stem_name, '')
            if path and os.path.exists(path):
                card = StemCard(stem_name, audio_data, path)
                self.stem_cards.append(card)
                layout.addWidget(card)

        if not self.stem_cards:
            empty = QLabel("⚠  No stem files found.")
            empty.setFont(QFont("Inter", 12))
            empty.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            layout.addWidget(empty)

    def stop_all(self):
        for card in self.stem_cards:
            card.stop()
