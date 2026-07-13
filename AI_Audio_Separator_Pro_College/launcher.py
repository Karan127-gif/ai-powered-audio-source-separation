"""
AI Audio Separator Pro — Self-Installing Launcher
--------------------------------------------------
PyInstaller-safe design:
  • When frozen (EXE): finds the SYSTEM Python, uses it for pip and main.py
  • When not frozen (dev): uses current interpreter directly
  • Checks packages via subprocess (importlib only sees the frozen bundle)
  • Single Tk window — no extra dialogs, errors shown inline
"""

import sys
import os
import subprocess
import shutil
import threading
import tkinter as tk
from tkinter import ttk

# ── Path helpers ──────────────────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    # Running as PyInstaller onefile EXE — executable dir is where user put it
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MAIN_SCRIPT = os.path.join(BASE_DIR, "main.py")

# Packages to verify (import names)
CHECK_IMPORTS = [
    "torch", "librosa", "soundfile",
    "numpy", "PyQt6", "matplotlib", "PIL", "bcrypt",
]


# ── Python finder ─────────────────────────────────────────────────────────────
def find_system_python():
    """
    Locate the system Python 3 interpreter.

    When running as a frozen EXE, sys.executable points to the EXE itself,
    NOT to Python. We must find the real Python to run pip and main.py.
    When running as a plain .py script, sys.executable is already correct.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable  # already the real Python

    self_exe = os.path.normcase(os.path.abspath(sys.executable))

    # Candidates to try in order
    candidates = ["python", "python3", "python3.12", "python3.11",
                  "python3.10", "python3.9"]

    for name in candidates:
        path = shutil.which(name)
        if not path:
            continue
        path_norm = os.path.normcase(os.path.abspath(path))
        if path_norm == self_exe:
            continue   # that's ourselves — skip
        try:
            r = subprocess.run(
                [path, "--version"],
                capture_output=True, text=True, timeout=8
            )
            out = (r.stdout + r.stderr).strip()
            if r.returncode == 0 and "Python 3" in out:
                return path
        except Exception:
            continue

    # Try the Windows 'py' launcher as a fallback
    try:
        r = subprocess.run(
            ["py", "-3", "-c", "import sys; print(sys.executable)"],
            capture_output=True, text=True, timeout=8
        )
        if r.returncode == 0:
            path = r.stdout.strip()
            if path and os.path.exists(path):
                return path
    except Exception:
        pass

    return None   # Python not found on PATH


def check_package(python_exe, import_name):
    """Return True if import_name can be imported by python_exe."""
    try:
        r = subprocess.run(
            [python_exe, "-c", f"import {import_name}"],
            capture_output=True, timeout=12
        )
        return r.returncode == 0
    except Exception:
        return False


def all_packages_ok(python_exe):
    return all(check_package(python_exe, n) for n in CHECK_IMPORTS)


# ── Single Setup Window ───────────────────────────────────────────────────────
class SetupWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("AI Audio Separator Pro — First-Time Setup")
        self.root.geometry("560x440")
        self.root.resizable(False, False)
        self.root.configure(bg="#0A0A14")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Centre on screen
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"560x440+{(sw-560)//2}+{(sh-440)//2}")

        icon_path = os.path.join(BASE_DIR, "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        self._build_ui()
        self._cancelled = False

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg="#13132A", pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🎵  AI Audio Separator Pro",
                 font=("Segoe UI", 15, "bold"),
                 fg="#A78BFA", bg="#13132A").pack()
        self.subtitle_var = tk.StringVar(
            value="First-time setup — installing packages, please wait…")
        tk.Label(hdr, textvariable=self.subtitle_var,
                 font=("Segoe UI", 9), fg="#6B6B9A", bg="#13132A").pack(pady=(2, 0))

        # Step checklist
        steps_frame = tk.Frame(self.root, bg="#0A0A14", padx=30, pady=14)
        steps_frame.pack(fill="x")
        self.step_vars = []
        steps = [
            ("1", "Checking Python installation"),
            ("2", "Installing PyTorch CPU  (~200 MB)"),
            ("3", "Installing librosa, PyQt6 & other packages"),
            ("4", "Verifying installation"),
        ]
        for num, label in steps:
            row = tk.Frame(steps_frame, bg="#0A0A14")
            row.pack(fill="x", pady=3)
            badge = tk.Label(row, text=f" {num} ", width=2,
                             font=("Segoe UI", 9, "bold"),
                             fg="#FFFFFF", bg="#2D2D50", relief="flat")
            badge.pack(side="left", padx=(0, 10))
            sv = tk.StringVar(value="⏳  " + label)
            lbl = tk.Label(row, textvariable=sv,
                           font=("Segoe UI", 10), fg="#7070A0", bg="#0A0A14",
                           anchor="w")
            lbl.pack(side="left", fill="x", expand=True)
            self.step_vars.append((sv, badge, lbl, label))

        # Progress bar
        pb_frame = tk.Frame(self.root, bg="#0A0A14", padx=30)
        pb_frame.pack(fill="x")
        style = ttk.Style()
        style.theme_use("default")
        style.configure("S.Horizontal.TProgressbar",
                        troughcolor="#1A1A30",
                        background="#7C3AED", thickness=8)
        self.progress = ttk.Progressbar(
            pb_frame, mode="indeterminate", length=500,
            style="S.Horizontal.TProgressbar")
        self.progress.pack(pady=8)
        self.progress.start(10)

        # Log console
        log_frame = tk.Frame(self.root, bg="#0A0A14", padx=30, pady=4)
        log_frame.pack(fill="both", expand=True)
        tk.Label(log_frame, text="Install log:",
                 font=("Segoe UI", 8), fg="#3A3A5A", bg="#0A0A14",
                 anchor="w").pack(fill="x")
        self.log_text = tk.Text(log_frame, height=8,
                                bg="#07070F", fg="#4A4A70",
                                font=("Consolas", 8), relief="flat",
                                wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_configure("ok",   foreground="#34D399")
        self.log_text.tag_configure("err",  foreground="#F87171")
        self.log_text.tag_configure("info", foreground="#A78BFA")
        self.log_text.tag_configure("plain",foreground="#4A4A70")

        # Status bar
        self.status_var = tk.StringVar(value="Starting…")
        tk.Label(self.root, textvariable=self.status_var,
                 font=("Segoe UI", 9, "italic"),
                 fg="#5A5A8A", bg="#0A0A14", pady=6).pack(fill="x")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def log(self, text, tag="plain"):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.root.update_idletasks()

    def set_status(self, text):
        self.status_var.set(text)
        self.root.update_idletasks()

    def mark_step(self, index, state):
        icons  = {"running":"▶  ","done":"✔  ","error":"✖  ","skip":"–  "}
        colors = {"running":"#A78BFA","done":"#34D399","error":"#F87171","skip":"#3A3A5A"}
        badges = {"running":"#5B21B6","done":"#065F46","error":"#7F1D1D","skip":"#1E1E3A"}
        sv, badge, lbl, label = self.step_vars[index]
        sv.set(icons.get(state, "") + label)
        lbl.configure(fg=colors.get(state, "#7070A0"))
        badge.configure(bg=badges.get(state, "#2D2D50"))
        self.root.update_idletasks()

    def show_error_inline(self, title, detail=""):
        self.progress.stop()
        self.subtitle_var.set(f"❌  {title}")
        self.log("", "plain")
        self.log(f"  ✖  {title}", "err")
        for line in (detail or "").strip().splitlines()[-10:]:
            self.log("     " + line.strip(), "err")
        self.log("", "plain")
        self.log("  Please check your internet connection and re-run the launcher.", "info")
        self.status_var.set("Setup failed — close this window and try again.")
        self._cancelled = True

    def finish_ok(self):
        self.progress.stop()
        self.subtitle_var.set("✔  Setup complete! Launching the app…")
        self.status_var.set("All packages installed. Starting AI Audio Separator Pro…")
        self.root.update_idletasks()

    def _on_close(self):
        self._cancelled = True
        self.root.destroy()
        sys.exit(0)


# ── No-Python error window ────────────────────────────────────────────────────
class NoPythonWindow:
    """Shown when Python 3 is not found on PATH at all."""
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Python Not Found")
        self.root.geometry("520x300")
        self.root.resizable(False, False)
        self.root.configure(bg="#0A0A14")

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"520x300+{(sw-520)//2}+{(sh-300)//2}")

        tk.Label(self.root, text="⚠  Python Not Installed",
                 font=("Segoe UI", 16, "bold"),
                 fg="#F87171", bg="#0A0A14").pack(pady=(30, 10))

        msg = (
            "Python 3.10 or newer is required to run this app.\n\n"
            "Please download and install Python from:\n"
            "https://www.python.org/downloads/\n\n"
            "⚠  IMPORTANT: check  \"Add Python to PATH\"  during installation.\n\n"
            "After installing Python, double-click the EXE again."
        )
        tk.Label(self.root, text=msg,
                 font=("Segoe UI", 10), fg="#C0C0D4", bg="#0A0A14",
                 justify="center", wraplength=460).pack(pady=10)

        btn = tk.Button(self.root, text="Open python.org/downloads",
                        font=("Segoe UI", 10, "bold"),
                        fg="white", bg="#7C3AED",
                        activebackground="#A78BFA", relief="flat",
                        padx=16, pady=8,
                        command=self._open_url)
        btn.pack(pady=10)

    def _open_url(self):
        import webbrowser
        webbrowser.open("https://www.python.org/downloads/")

    def show(self):
        self.root.mainloop()


# ── Install worker ────────────────────────────────────────────────────────────
def run_install(win: SetupWindow, python: str):
    # Step 0 — Python found (already confirmed)
    win.mark_step(0, "done")
    win.log(f"  ✔ Python found: {python}", "ok")

    # Step 1 — PyTorch CPU
    win.mark_step(1, "running")
    win.set_status("Downloading PyTorch CPU (~200 MB) — this may take several minutes…")
    win.log("→ Installing PyTorch CPU from pytorch.org/whl/cpu …", "info")

    res = subprocess.run(
        [python, "-m", "pip", "install",
         "torch", "torchaudio",
         "--index-url", "https://download.pytorch.org/whl/cpu",
         "-q", "--no-warn-script-location"],
        capture_output=True, text=True
    )
    if res.returncode != 0:
        win.mark_step(1, "error")
        win.mark_step(2, "skip")
        win.mark_step(3, "skip")
        win.show_error_inline("Failed to install PyTorch.",
                              res.stderr or res.stdout)
        return

    win.mark_step(1, "done")
    win.log("  ✔ PyTorch installed", "ok")

    # Step 2 — Other packages
    win.mark_step(2, "running")
    win.set_status("Installing librosa, PyQt6, matplotlib and other packages…")
    win.log("→ Installing librosa, soundfile, PyQt6, matplotlib, Pillow, bcrypt…", "info")

    others = ["librosa", "soundfile", "numpy", "matplotlib",
              "Pillow", "bcrypt", "PyQt6"]
    res = subprocess.run(
        [python, "-m", "pip", "install"] + others +
        ["-q", "--no-warn-script-location"],
        capture_output=True, text=True
    )
    if res.returncode != 0:
        win.mark_step(2, "error")
        win.mark_step(3, "skip")
        win.show_error_inline("Failed to install packages.",
                              res.stderr or res.stdout)
        return

    win.mark_step(2, "done")
    win.log("  ✔ All packages installed", "ok")

    # Step 3 — Verify
    win.mark_step(3, "running")
    win.set_status("Verifying installation…")
    win.log("→ Verifying imports…", "info")

    missing = [n for n in CHECK_IMPORTS if not check_package(python, n)]
    if missing:
        win.mark_step(3, "error")
        win.show_error_inline(
            f"Verification failed — missing: {', '.join(missing)}",
            "Try running the launcher again with a stable internet connection."
        )
        return

    win.mark_step(3, "done")
    win.log("  ✔ All imports verified", "ok")
    win.log("", "plain")
    win.log("  🎵  Ready! Launching AI Audio Separator Pro…", "info")

    win.root.after(1200, lambda: _finish_and_launch(win, python))


def _finish_and_launch(win, python):
    win.finish_ok()
    win.root.after(800, lambda: _do_launch(win, python))


def _do_launch(win, python):
    launch_main(python)
    win.root.destroy()


def launch_main(python):
    """Launch main.py using the given Python interpreter."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        subprocess.Popen(
            [python, MAIN_SCRIPT],
            cwd=BASE_DIR,
            creationflags=flags
        )
    except Exception as e:
        # Fallback: show error in a simple dialog
        root = tk.Tk()
        root.withdraw()
        tk.messagebox.showerror(
            "Launch Failed",
            f"Could not start main.py:\n{e}\n\n"
            f"Python: {python}\nScript: {MAIN_SCRIPT}"
        )
        root.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    # 1. Find Python
    python = find_system_python()

    if not python:
        # Python not installed — show instructions
        NoPythonWindow().show()
        return

    # 2. Check if all packages are already installed
    if all_packages_ok(python):
        # Nothing to install — launch directly (no GUI)
        launch_main(python)
        return

    # 3. Need to install — show the single setup window
    win = SetupWindow()
    win.mark_step(0, "running")
    win.set_status("Checking Python installation…")

    t = threading.Thread(target=run_install, args=(win, python), daemon=True)
    t.start()

    win.root.mainloop()


if __name__ == "__main__":
    main()
