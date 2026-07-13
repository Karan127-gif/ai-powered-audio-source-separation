import sys
import signal
import traceback
import logging
import json
import os

# ── Pre-load PyTorch DLLs on the MAIN thread ────────────────────────────────
# Windows requires that C10.dll / torch_python.dll are first initialised on
# the main thread. If we let the background ModelLoaderThread do the first
# `import torch`, we get WinError 1114 ("DLL initialization routine failed").
# Importing here — before QApplication is created — guarantees the DLLs are
# already resident in the process when the worker thread calls torch.load().
try:
    import torch as _torch  # noqa: F401
except Exception:
    pass  # If torch is missing the thread will report the error gracefully

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QIcon
from config import APP_NAME, LOG_PATH, DATA_DIR, ICON_PATH


def setup_logging():
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.ERROR,
        format='%(asctime)s %(levelname)s %(message)s'
    )


def global_exception_handler(exc_type, exc_value, exc_tb):
    # Don't show dialog for KeyboardInterrupt / SystemExit — just quit cleanly
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        QApplication.quit()
        return
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logging.error(msg)
    try:
        dlg = QMessageBox()
        dlg.setWindowTitle("Unexpected Error")
        dlg.setText(f"An unexpected error occurred:\n\n{exc_value}\n\nDetails have been logged.")
        dlg.setIcon(QMessageBox.Icon.Critical)
        dlg.exec()
    except Exception:
        pass


# ── Session helpers (auto-login) ───────────────────────────────────────────────
SESSION_FILE = os.path.join(DATA_DIR, 'session.json')


def save_session(user_id: int):
    """Persist the logged-in user ID so the app can auto-login next launch."""
    try:
        with open(SESSION_FILE, 'w') as f:
            json.dump({'user_id': user_id}, f)
    except Exception:
        pass


def load_session():
    """Return saved user_id, or None if no session exists."""
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
            return data.get('user_id')
    except Exception:
        return None


def clear_session():
    """Delete session file on logout."""
    try:
        if os.path.exists(SESSION_FILE):
            os.remove(SESSION_FILE)
    except Exception:
        pass


class AppController:
    """Manages transitions between windows."""

    def __init__(self):
        self.landing = None
        self.auth_window = None
        self.user_dashboard = None
        self.admin_dashboard = None
        self.current_user = None

    def show_landing(self):
        from landing_page import LandingPage
        if self.auth_window:
            self.auth_window.hide()
        if self.user_dashboard:
            self.user_dashboard.hide()
        if self.admin_dashboard:
            self.admin_dashboard.hide()
        if not self.landing:
            self.landing = LandingPage(self)
        self.landing.showMaximized()

    def show_auth(self):
        from auth_window import AuthWindow
        if self.landing:
            self.landing.hide()
        if not self.auth_window:
            self.auth_window = AuthWindow(self)
        self.auth_window.showMaximized()

    def on_login_success(self, user):
        self.current_user = user
        # Persist session so next launch auto-logs in
        save_session(user['id'])
        if self.auth_window:
            self.auth_window.hide()
        if user['role'] == 'admin':
            self.show_admin_dashboard()
        else:
            self.show_user_dashboard()

    def show_user_dashboard(self):
        from user_dashboard import UserDashboard
        if not self.user_dashboard or self.user_dashboard.user['id'] != self.current_user['id']:
            if self.user_dashboard:
                self.user_dashboard.close()
            self.user_dashboard = UserDashboard(self.current_user, self)
        self.user_dashboard.showMaximized()

    def show_admin_dashboard(self):
        from admin_dashboard import AdminDashboard
        if not self.admin_dashboard:
            self.admin_dashboard = AdminDashboard(self.current_user, self)
        self.admin_dashboard.showMaximized()

    def logout(self):
        self.current_user = None
        # Clear saved session so next launch shows login screen
        clear_session()
        if self.user_dashboard:
            self.user_dashboard.close()
            self.user_dashboard = None
        if self.admin_dashboard:
            self.admin_dashboard.close()
            self.admin_dashboard = None
        self.show_landing()


def main():
    setup_logging()
    sys.excepthook = global_exception_handler

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion("2.1.0")

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    app.setStyle("Fusion")

    # Set application-wide window icon (works in EXE too via resource_path)
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))
    # Install a SIGINT handler so that Ctrl+C on the terminal triggers a clean
    # app.quit() instead of raising KeyboardInterrupt inside a Qt paint event
    # (which is what caused the crash logged in app_error.log).
    def _sigint_handler(*args):
        app.quit()

    signal.signal(signal.SIGINT, _sigint_handler)

    # Allow Python to process signals every 500 ms even when Qt event loop is running
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)  # wake Python interpreter regularly

    controller = AppController()

    # ── Auto-login: restore previous session if available ─────────────────────
    saved_uid = load_session()
    if saved_uid:
        from database import Database
        db = Database()
        user = db.get_user(saved_uid)
        if user:
            controller.on_login_success(user)
        else:
            clear_session()          # session refers to a deleted account
            controller.show_landing()
    else:
        controller.show_landing()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
