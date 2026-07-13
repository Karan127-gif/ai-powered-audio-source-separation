"""
AI Stereo Multi-Stem Separator Pro
Desktop Application v2.0
Built with CustomTkinter for a premium dark-theme UI
"""

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import os
import sys
import numpy as np
import webbrowser
import shutil
from pathlib import Path
import time

# ── Matplotlib (headless, embedded) ────────────────────────────────────────────
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.patches as mpatches

# ── Audio ───────────────────────────────────────────────────────────────────────
import librosa
import librosa.display
import soundfile as sf
import torch

# ── Model ───────────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from model import MultiStemUNet

# ══════════════════════════════════════════════════════════════════════════════
#  CONSTANTS & THEME
# ══════════════════════════════════════════════════════════════════════════════
APP_NAME    = "AI Stereo Multi-Stem Separator Pro"
APP_VERSION = "2.0"
DEVICE      = torch.device("cuda" if torch.cuda.is_available() else "cpu")
OUTPUT_DIR  = Path(__file__).parent / "output_stems"
MODEL_PATHS = ["multistem_unet_best.pth", "multistem_unet.pth"]

STEM_CONFIG = [
    {"name": "Vocals",  "color": "#FF4B6E", "accent": "#FF8FA3", "emoji": "🎤"},
    {"name": "Drums",   "color": "#00D4FF", "accent": "#7EE8FF", "emoji": "🥁"},
    {"name": "Bass",    "color": "#FFD700", "accent": "#FFE97A", "emoji": "🎸"},
    {"name": "Other",   "color": "#ADFF2F", "accent": "#D4FF7E", "emoji": "🎹"},
]

# Theme colours
BG_DARK     = "#0A0A0F"
BG_MID      = "#12121A"
BG_CARD     = "#1A1A26"
BG_HOVER    = "#22223A"
ACCENT_PRI  = "#7C3AED"   # Purple
ACCENT_SEC  = "#06B6D4"   # Cyan
TEXT_PRI    = "#F1F5F9"
TEXT_SEC    = "#94A3B8"
TEXT_DIM    = "#475569"
BORDER      = "#2D2D45"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def load_model():
    m = MultiStemUNet(out_channels=4).to(DEVICE)
    for p in MODEL_PATHS:
        full = Path(__file__).parent / p
        if full.exists():
            m.load_state_dict(torch.load(str(full), map_location=DEVICE))
            m.eval()
            return m, p
    raise FileNotFoundError("No model weights found – place multistem_unet_best.pth in the project folder.")


def run_separation(audio_path, progress_cb, status_cb):
    """Core inference – runs in worker thread, returns dict of {stem: wav array}."""
    status_cb("Loading audio…")
    progress_cb(5)

    y, sr = librosa.load(audio_path, sr=22050, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    progress_cb(15)

    status_cb("Computing spectrograms…")
    stft_l = librosa.stft(y[0], n_fft=1024, hop_length=256)
    stft_r = librosa.stft(y[1], n_fft=1024, hop_length=256)
    phase_l, phase_r = np.angle(stft_l), np.angle(stft_r)
    in_l = (librosa.amplitude_to_db(np.abs(stft_l), ref=np.max) + 80) / 80
    in_r = (librosa.amplitude_to_db(np.abs(stft_r), ref=np.max) + 80) / 80
    combined_in = np.stack([in_l, in_r])
    progress_cb(30)

    status_cb("Running AI inference…")
    CHUNK_SIZE = 128
    all_stems  = []
    total_chunks = max(1, combined_in.shape[2] // CHUNK_SIZE + 1)

    with torch.no_grad():
        for idx, i in enumerate(range(0, combined_in.shape[2], CHUNK_SIZE)):
            chunk = combined_in[:, :, i:i + CHUNK_SIZE]
            pw = (16 - (chunk.shape[2] % 16)) % 16
            if pw > 0:
                chunk = np.pad(chunk, ((0, 0), (0, 0), (0, pw)))
            inp  = torch.from_numpy(chunk).float().unsqueeze(0).to(DEVICE)
            pred = model(inp).squeeze(0).cpu().numpy()
            if pw > 0:
                pred = pred[:, :, :, :-pw]
            all_stems.append(pred)
            pct = 30 + int(50 * (idx + 1) / total_chunks)
            progress_cb(pct)

    status_cb("Reconstructing stems…")
    full_stems = np.concatenate(all_stems, axis=3)
    results    = {}

    OUTPUT_DIR.mkdir(exist_ok=True)
    for i, cfg in enumerate(STEM_CONFIG):
        db_l   = (full_stems[i, 0] * 80) - 80
        db_r   = (full_stems[i, 1] * 80) - 80
        mag_l  = librosa.db_to_amplitude(db_l)
        mag_r  = librosa.db_to_amplitude(db_r)
        out_l  = librosa.istft(mag_l * np.exp(1j * phase_l), hop_length=256)
        out_r  = librosa.istft(mag_r * np.exp(1j * phase_r), hop_length=256)
        wav    = np.stack([out_l, out_r], axis=1)
        if np.max(np.abs(wav)) > 0:
            wav /= np.max(np.abs(wav))
        fname  = OUTPUT_DIR / f"output_{cfg['name'].lower()}.wav"
        sf.write(str(fname), wav, 22050)
        results[cfg['name']] = {"wav": wav, "path": str(fname), "sr": 22050}

    progress_cb(100)
    status_cb("Done ✓")
    return results


def make_waveform_fig(wav, sr, color, accent):
    """Returns a matplotlib Figure with a glowing waveform."""
    fig, ax = plt.subplots(figsize=(5.5, 1.6))
    fig.patch.set_facecolor(BG_CARD)
    ax.set_facecolor(BG_CARD)

    mono = librosa.to_mono(wav.T)
    t    = np.linspace(0, len(mono) / sr, len(mono))

    # Glow effect – draw multiple layers
    for alpha, lw in [(0.12, 6), (0.25, 3), (0.9, 1)]:
        ax.plot(t, mono, color=color, alpha=alpha, linewidth=lw)

    ax.set_xlim(0, t[-1])
    ax.set_ylim(-1.05, 1.05)
    ax.axis("off")
    fig.tight_layout(pad=0.1)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  CUSTOM WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

class GradientButton(ctk.CTkButton):
    """Reusable premium button."""
    def __init__(self, master, **kwargs):
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("font", ctk.CTkFont(family="Segoe UI", size=13, weight="bold"))
        super().__init__(master, **kwargs)


class StemCard(ctk.CTkFrame):
    """A card widget showing one separated stem."""
    def __init__(self, master, cfg, **kwargs):
        super().__init__(master, corner_radius=16, fg_color=BG_CARD,
                         border_width=1, border_color=BORDER, **kwargs)

        self.cfg      = cfg
        self.wav_path = None
        self._playing = False

        # ── Header ──────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(14, 4))

        dot = ctk.CTkLabel(hdr, text="●", text_color=cfg["color"],
                           font=ctk.CTkFont(size=16))
        dot.pack(side="left", padx=(0, 6))

        ctk.CTkLabel(hdr, text=f"{cfg['emoji']} {cfg['name']}",
                     text_color=TEXT_PRI,
                     font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold")
                     ).pack(side="left")

        # ── Waveform canvas placeholder ──────────────────────────────────────
        self.wave_frame = ctk.CTkFrame(self, fg_color=BG_MID, corner_radius=10,
                                       height=80)
        self.wave_frame.pack(fill="x", padx=16, pady=(4, 8))
        self.wave_frame.pack_propagate(False)

        self._placeholder_label = ctk.CTkLabel(
            self.wave_frame, text="Waveform will appear after separation",
            text_color=TEXT_DIM, font=ctk.CTkFont(size=11))
        self._placeholder_label.pack(expand=True)

        self._canvas_widget = None

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        self.btn_play = GradientButton(
            btn_row, text="▶  Play", width=110,
            fg_color=ACCENT_PRI, hover_color="#6D28D9",
            command=self._play, state="disabled")
        self.btn_play.pack(side="left", padx=(0, 8))

        self.btn_save = GradientButton(
            btn_row, text="💾  Save", width=110,
            fg_color="#1E293B", hover_color=BG_HOVER,
            border_width=1, border_color=BORDER,
            command=self._save, state="disabled")
        self.btn_save.pack(side="left")

    # ── Public API ───────────────────────────────────────────────────────────
    def update_stem(self, wav, sr, path):
        self.wav_path = path
        self._draw_waveform(wav, sr)
        self.btn_play.configure(state="normal")
        self.btn_save.configure(state="normal")

    def reset(self):
        self.wav_path = None
        if self._canvas_widget:
            self._canvas_widget.get_tk_widget().destroy()
            self._canvas_widget = None
        self._placeholder_label = ctk.CTkLabel(
            self.wave_frame, text="Waveform will appear after separation",
            text_color=TEXT_DIM, font=ctk.CTkFont(size=11))
        self._placeholder_label.pack(expand=True)
        self.btn_play.configure(state="disabled")
        self.btn_save.configure(state="disabled")

    # ── Private ──────────────────────────────────────────────────────────────
    def _draw_waveform(self, wav, sr):
        if self._placeholder_label:
            self._placeholder_label.destroy()
            self._placeholder_label = None
        if self._canvas_widget:
            self._canvas_widget.get_tk_widget().destroy()

        fig = make_waveform_fig(wav, sr, self.cfg["color"], self.cfg["accent"])
        canvas = FigureCanvasTkAgg(fig, master=self.wave_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas_widget = canvas
        plt.close(fig)

    def _play(self):
        if not self.wav_path:
            return
        try:
            os.startfile(self.wav_path)
        except Exception as e:
            messagebox.showerror("Playback Error", str(e))

    def _save(self):
        if not self.wav_path:
            return
        dest = filedialog.asksaveasfilename(
            defaultextension=".wav",
            filetypes=[("WAV Audio", "*.wav"), ("All Files", "*.*")],
            initialfile=f"{self.cfg['name']}.wav",
            title=f"Save {self.cfg['name']} stem",
        )
        if dest:
            shutil.copy2(self.wav_path, dest)
            messagebox.showinfo("Saved", f"{self.cfg['name']} saved to:\n{dest}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("1200x820")
        self.minsize(900, 680)
        self.configure(fg_color=BG_DARK)

        # Set icon
        ico = Path(__file__).parent / "app_icon.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

        self._audio_path  = None
        self._worker      = None
        self._results     = {}

        self._build_ui()
        self._load_model_async()

    # ── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        # ─── Top Bar ──────────────────────────────────────────────────────────
        topbar = ctk.CTkFrame(self, fg_color=BG_MID, corner_radius=0, height=60)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        ctk.CTkLabel(
            topbar,
            text=f"  🎵  {APP_NAME}",
            text_color=TEXT_PRI,
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
        ).pack(side="left", padx=20)

        # Hardware badge
        hw_text = f"⚡ {str(DEVICE).upper()}"
        hw_col  = "#10B981" if DEVICE.type == "cuda" else TEXT_DIM
        ctk.CTkLabel(topbar, text=hw_text, text_color=hw_col,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     fg_color=BG_CARD, corner_radius=8,
                     padx=10, pady=3).pack(side="right", padx=20)

        ctk.CTkLabel(topbar, text=f"v{APP_VERSION}", text_color=TEXT_DIM,
                     font=ctk.CTkFont(size=11)).pack(side="right", padx=4)

        # ─── Scrollable main area ─────────────────────────────────────────────
        main = ctk.CTkScrollableFrame(self, fg_color=BG_DARK, scrollbar_button_color=BORDER)
        main.pack(fill="both", expand=True, padx=0, pady=0)

        # ─── Upload section ───────────────────────────────────────────────────
        upload_card = ctk.CTkFrame(main, fg_color=BG_CARD, corner_radius=16,
                                   border_width=1, border_color=BORDER)
        upload_card.pack(fill="x", padx=24, pady=(20, 12))

        ctk.CTkLabel(upload_card, text="Upload Your Song",
                     text_color=TEXT_PRI,
                     font=ctk.CTkFont(family="Segoe UI", size=16, weight="bold")
                     ).pack(anchor="w", padx=20, pady=(16, 4))

        ctk.CTkLabel(upload_card, text="Supports WAV and MP3 formats",
                     text_color=TEXT_SEC, font=ctk.CTkFont(size=12)
                     ).pack(anchor="w", padx=20, pady=(0, 12))

        # Drop zone
        self.drop_zone = ctk.CTkFrame(
            upload_card, fg_color=BG_MID, corner_radius=12,
            border_width=2, border_color=BORDER, height=130)
        self.drop_zone.pack(fill="x", padx=20, pady=(0, 16))
        self.drop_zone.pack_propagate(False)

        self.drop_icon = ctk.CTkLabel(
            self.drop_zone,
            text="📂",
            font=ctk.CTkFont(size=36))
        self.drop_icon.pack(pady=(18, 4))

        self.drop_label = ctk.CTkLabel(
            self.drop_zone,
            text="Click to browse or drop an audio file here",
            text_color=TEXT_SEC,
            font=ctk.CTkFont(size=13))
        self.drop_label.pack()

        self.file_label = ctk.CTkLabel(
            self.drop_zone, text="", text_color=ACCENT_SEC,
            font=ctk.CTkFont(size=12, weight="bold"))
        self.file_label.pack(pady=(2, 0))

        # Make drop zone clickable
        for w in [self.drop_zone, self.drop_icon, self.drop_label, self.file_label]:
            w.bind("<Button-1>", lambda e: self._browse_file())
            w.bind("<Enter>", lambda e: self.drop_zone.configure(border_color=ACCENT_PRI))
            w.bind("<Leave>", lambda e: self.drop_zone.configure(border_color=BORDER))

        # Button row
        btn_row = ctk.CTkFrame(upload_card, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))

        self.btn_browse = GradientButton(
            btn_row, text="📁  Browse File", width=150,
            fg_color=BG_HOVER, hover_color="#2D2D52",
            border_width=1, border_color=BORDER,
            command=self._browse_file)
        self.btn_browse.pack(side="left", padx=(0, 12))

        self.btn_start = GradientButton(
            btn_row, text="🚀  Start AI Separation", width=220,
            fg_color=ACCENT_PRI, hover_color="#6D28D9",
            command=self._start_separation, state="disabled")
        self.btn_start.pack(side="left")

        self.btn_clear = GradientButton(
            btn_row, text="✕  Clear", width=100,
            fg_color="#1E293B", hover_color=BG_HOVER,
            border_width=1, border_color=BORDER,
            command=self._clear, state="disabled")
        self.btn_clear.pack(side="right")

        # ─── Progress bar ─────────────────────────────────────────────────────
        prog_card = ctk.CTkFrame(main, fg_color=BG_CARD, corner_radius=16,
                                 border_width=1, border_color=BORDER)
        prog_card.pack(fill="x", padx=24, pady=(0, 12))

        prog_inner = ctk.CTkFrame(prog_card, fg_color="transparent")
        prog_inner.pack(fill="x", padx=20, pady=14)

        self.status_label = ctk.CTkLabel(
            prog_inner, text="⏳ Load a model to begin…",
            text_color=TEXT_SEC, font=ctk.CTkFont(size=12))
        self.status_label.pack(anchor="w")

        self.progress_bar = ctk.CTkProgressBar(prog_inner, height=8,
                                               progress_color=ACCENT_PRI,
                                               fg_color=BG_MID, corner_radius=4)
        self.progress_bar.pack(fill="x", pady=(6, 0))
        self.progress_bar.set(0)

        # ─── Stem Cards (2×2 grid) ────────────────────────────────────────────
        stems_header = ctk.CTkFrame(main, fg_color="transparent")
        stems_header.pack(fill="x", padx=24, pady=(8, 4))

        ctk.CTkLabel(stems_header, text="Separated Stems",
                     text_color=TEXT_PRI,
                     font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold")
                     ).pack(side="left")

        self.btn_save_all = GradientButton(
            stems_header, text="💾  Save All Stems", width=160,
            fg_color=ACCENT_PRI, hover_color="#6D28D9",
            command=self._save_all, state="disabled")
        self.btn_save_all.pack(side="right")

        grid = ctk.CTkFrame(main, fg_color="transparent")
        grid.pack(fill="x", padx=24, pady=(0, 24))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        self._stem_cards = {}
        for i, cfg in enumerate(STEM_CONFIG):
            card = StemCard(grid, cfg)
            card.grid(row=i // 2, column=i % 2, padx=8, pady=8, sticky="nsew")
            self._stem_cards[cfg["name"]] = card

        # ─── Status bar ───────────────────────────────────────────────────────
        statusbar = ctk.CTkFrame(self, fg_color=BG_MID, corner_radius=0, height=28)
        statusbar.pack(side="bottom", fill="x")
        statusbar.pack_propagate(False)

        self.model_status_label = ctk.CTkLabel(
            statusbar, text="  ● Loading model…", text_color=TEXT_DIM,
            font=ctk.CTkFont(size=11))
        self.model_status_label.pack(side="left")

        ctk.CTkLabel(statusbar,
                     text=f"  AI Audio Separator  ·  v{APP_VERSION}  ·  by Your Name  ",
                     text_color=TEXT_DIM, font=ctk.CTkFont(size=11)
                     ).pack(side="right")

    # ── Model Loading ─────────────────────────────────────────────────────────

    def _load_model_async(self):
        def _worker():
            global model
            try:
                self._set_status("Loading AI model…")
                model, path = load_model()
                self.after(0, lambda: self._on_model_loaded(path))
            except Exception as e:
                self.after(0, lambda: self._on_model_error(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_model_loaded(self, path):
        hw = "GPU ⚡" if DEVICE.type == "cuda" else "CPU"
        self.model_status_label.configure(
            text=f"  ✓  Model loaded  ·  {path}  ·  Running on {hw}",
            text_color="#10B981")
        self._set_status("Ready – upload a song to begin.")
        self.btn_browse.configure(state="normal")

    def _on_model_error(self, err):
        self.model_status_label.configure(text=f"  ✗  {err}", text_color="#EF4444")
        self._set_status("Model failed to load. Check console for details.")

    # ── File Browsing ─────────────────────────────────────────────────────────

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("Audio Files", "*.wav *.mp3"), ("WAV", "*.wav"), ("MP3", "*.mp3")],
        )
        if path:
            self._set_audio(path)

    def _set_audio(self, path):
        self._audio_path = path
        fname = Path(path).name
        self.drop_label.configure(text="Selected file:")
        self.file_label.configure(text=f"🎵  {fname}")
        self.drop_zone.configure(border_color=ACCENT_SEC)
        self.btn_start.configure(state="normal")
        self.btn_clear.configure(state="normal")
        self._set_status(f"Ready to separate: {fname}")

    def _clear(self):
        self._audio_path = None
        self.drop_label.configure(text="Click to browse or drop an audio file here")
        self.file_label.configure(text="")
        self.drop_zone.configure(border_color=BORDER)
        self.btn_start.configure(state="disabled")
        self.btn_clear.configure(state="disabled")
        self.btn_save_all.configure(state="disabled")
        self.progress_bar.set(0)
        self._set_status("Cleared. Upload a new file.")
        for card in self._stem_cards.values():
            card.reset()

    # ── Separation ────────────────────────────────────────────────────────────

    def _start_separation(self):
        if not self._audio_path:
            return
        if self._worker and self._worker.is_alive():
            messagebox.showwarning("Busy", "A separation is already running. Please wait.")
            return

        self.btn_start.configure(state="disabled", text="⏳  Processing…")
        self.btn_browse.configure(state="disabled")
        self.btn_save_all.configure(state="disabled")
        self.progress_bar.set(0)

        for card in self._stem_cards.values():
            card.reset()

        def _worker():
            try:
                results = run_separation(
                    self._audio_path,
                    progress_cb=lambda v: self.after(0, lambda: self.progress_bar.set(v / 100)),
                    status_cb=lambda s: self.after(0, lambda: self._set_status(s)),
                )
                self.after(0, lambda: self._on_separation_done(results))
            except Exception as e:
                self.after(0, lambda: self._on_separation_error(str(e)))

        self._worker = threading.Thread(target=_worker, daemon=True)
        self._worker.start()

    def _on_separation_done(self, results):
        self._results = results
        for cfg in STEM_CONFIG:
            name   = cfg["name"]
            data   = results[name]
            card   = self._stem_cards[name]
            card.update_stem(data["wav"], data["sr"], data["path"])

        self.btn_start.configure(state="normal", text="🚀  Start AI Separation")
        self.btn_browse.configure(state="normal")
        self.btn_save_all.configure(state="normal")
        self._set_status(f"✓  Separation complete! {len(results)} stems saved to output_stems/")

    def _on_separation_error(self, err):
        self.btn_start.configure(state="normal", text="🚀  Start AI Separation")
        self.btn_browse.configure(state="normal")
        self._set_status(f"✗  Error: {err}")
        messagebox.showerror("Separation Failed", err)

    # ── Save All ──────────────────────────────────────────────────────────────

    def _save_all(self):
        if not self._results:
            return
        dest_dir = filedialog.askdirectory(title="Choose folder to save all stems")
        if not dest_dir:
            return
        for name, data in self._results.items():
            shutil.copy2(data["path"], Path(dest_dir) / f"{name}.wav")
        messagebox.showinfo("Saved", f"All {len(self._results)} stems saved to:\n{dest_dir}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, text):
        self.status_label.configure(text=f"  {text}")


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Ensure we can import model.py from the same directory
    os.chdir(Path(__file__).parent)
    app = App()
    app.mainloop()
