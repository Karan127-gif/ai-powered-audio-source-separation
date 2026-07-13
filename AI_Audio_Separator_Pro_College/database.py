import sqlite3
import bcrypt
import os
import secrets
from datetime import datetime
from config import DATABASE_PATH, BCRYPT_ROUNDS, FREE_CREDITS_ON_REGISTER, DEFAULT_ADMIN_USERNAME, DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_EMAIL


class Database:
    def __init__(self):
        self.db_path = DATABASE_PATH
        self._init_db()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email TEXT,
                    role TEXT DEFAULT 'user',
                    credits INTEGER DEFAULT 5,
                    created_at TEXT DEFAULT (datetime('now')),
                    photo_path TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS payment_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    credits_purchased INTEGER NOT NULL,
                    payment_method TEXT,
                    transaction_id TEXT,
                    timestamp TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS separation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    filename TEXT,
                    separation_type TEXT,
                    credits_used INTEGER DEFAULT 1,
                    output_paths TEXT DEFAULT '',
                    timestamp TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );

                CREATE TABLE IF NOT EXISTS team_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    role TEXT,
                    bio TEXT,
                    photo_path TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    message TEXT,
                    timestamp TEXT DEFAULT (datetime('now'))
                );
            """)
            # Ensure admin exists
            row = conn.execute("SELECT id FROM users WHERE username=?", (DEFAULT_ADMIN_USERNAME,)).fetchone()
            if not row:
                pw_hash = bcrypt.hashpw(DEFAULT_ADMIN_PASSWORD.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()
                conn.execute("INSERT INTO users (username, password_hash, email, role, credits) VALUES (?,?,?,?,?)",
                             (DEFAULT_ADMIN_USERNAME, pw_hash, DEFAULT_ADMIN_EMAIL, 'admin', 9999))
            # Add output_paths column if missing (migration for existing DBs)
            try:
                conn.execute("ALTER TABLE separation_history ADD COLUMN output_paths TEXT DEFAULT ''")
            except Exception:
                pass  # column already exists
            # Default settings
            defaults = {
                'contact_email': DEFAULT_ADMIN_EMAIL,
                'contact_phone': '+91-9876543210',
                'app_name': 'AI Audio Separator Pro',
                'free_credits': str(FREE_CREDITS_ON_REGISTER),
            }
            for k, v in defaults.items():
                conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)", (k, v))

    # ── User management ───────────────────────────────────────────────────────
    def register_user(self, username, password, email=''):
        try:
            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()
            with self._get_conn() as conn:
                conn.execute("INSERT INTO users (username, password_hash, email, role, credits) VALUES (?,?,?,?,?)",
                             (username.strip(), pw_hash, email.strip(), 'user', FREE_CREDITS_ON_REGISTER))
            return True, "Registration successful!"
        except sqlite3.IntegrityError:
            return False, "Username already exists."
        except Exception as e:
            return False, str(e)

    def login(self, username, password):
        try:
            with self._get_conn() as conn:
                row = conn.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
            if not row:
                return None, "Invalid username or password."
            if bcrypt.checkpw(password.encode(), row['password_hash'].encode()):
                return dict(row), "Login successful."
            return None, "Invalid username or password."
        except Exception as e:
            return None, str(e)

    def get_user(self, user_id):
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_all_users(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM users WHERE role != 'admin' ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def update_credits(self, user_id, delta):
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET credits = credits + ? WHERE id=?", (delta, user_id))

    def set_credits(self, user_id, amount):
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET credits=? WHERE id=?", (amount, user_id))

    def deduct_credits(self, user_id, amount):
        with self._get_conn() as conn:
            row = conn.execute("SELECT credits FROM users WHERE id=?", (user_id,)).fetchone()
            if not row or row['credits'] < amount:
                return False
            conn.execute("UPDATE users SET credits=credits-? WHERE id=?", (amount, user_id))
        return True

    def delete_user(self, user_id):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))

    def update_user_photo(self, user_id, photo_path):
        with self._get_conn() as conn:
            conn.execute("UPDATE users SET photo_path=? WHERE id=?", (photo_path, user_id))

    def change_password(self, user_id, current_password, new_password):
        """Verify current password then update to new one. Returns (ok, message)."""
        try:
            with self._get_conn() as conn:
                row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                return False, "User not found."
            if not bcrypt.checkpw(current_password.encode(), row['password_hash'].encode()):
                return False, "Current password is incorrect."
            new_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()
            with self._get_conn() as conn:
                conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, user_id))
            return True, "Password updated successfully!"
        except Exception as e:
            return False, str(e)

    def update_email(self, user_id, new_email):
        """Update the user's email address."""
        try:
            with self._get_conn() as conn:
                conn.execute("UPDATE users SET email=? WHERE id=?", (new_email.strip(), user_id))
            return True, "Email updated successfully!"
        except Exception as e:
            return False, str(e)

    # ── Payment ───────────────────────────────────────────────────────────────
    def record_payment(self, user_id, amount, credits, method='Manual', txn_id=None):
        if not txn_id:
            txn_id = secrets.token_hex(8).upper()
        with self._get_conn() as conn:
            conn.execute("INSERT INTO payment_history (user_id, amount, credits_purchased, payment_method, transaction_id) VALUES (?,?,?,?,?)",
                         (user_id, amount, credits, method, txn_id))
        self.update_credits(user_id, credits)
        return txn_id

    def add_payment(self, user_id, amount, credits_purchased, payment_method='Manual', transaction_id=None):
        """Alias used by PaymentWindow — maps to record_payment."""
        return self.record_payment(
            user_id=user_id,
            amount=amount,
            credits=credits_purchased,
            method=payment_method,
            txn_id=transaction_id
        )

    def get_all_payments(self):
        with self._get_conn() as conn:
            rows = conn.execute("""SELECT ph.*, u.username FROM payment_history ph
                                   JOIN users u ON ph.user_id=u.id
                                   ORDER BY ph.timestamp DESC""").fetchall()
        return [dict(r) for r in rows]

    def get_user_payments(self, user_id):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM payment_history WHERE user_id=? ORDER BY timestamp DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

    # ── Separation history ────────────────────────────────────────────────────
    def record_separation(self, user_id, filename, sep_type, credits_used, output_paths=None):
        import json
        paths_json = json.dumps(output_paths or {})
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO separation_history (user_id, filename, separation_type, credits_used, output_paths) VALUES (?,?,?,?,?)",
                (user_id, filename, sep_type, credits_used, paths_json)
            )

    def get_user_history(self, user_id, limit=50):
        import json
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM separation_history WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
                                (user_id, limit)).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d['output_paths'] = json.loads(d.get('output_paths') or '{}')
            except Exception:
                d['output_paths'] = {}
            results.append(d)
        return results

    def get_all_separations(self):
        with self._get_conn() as conn:
            rows = conn.execute("""SELECT sh.*, u.username FROM separation_history sh
                                   JOIN users u ON sh.user_id=u.id
                                   ORDER BY sh.timestamp DESC""").fetchall()
        return [dict(r) for r in rows]

    # ── Team members ──────────────────────────────────────────────────────────
    def get_team_members(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM team_members ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def add_team_member(self, name, role, bio='', photo_path=''):
        with self._get_conn() as conn:
            conn.execute("INSERT INTO team_members (name, role, bio, photo_path) VALUES (?,?,?,?)",
                         (name, role, bio, photo_path))

    def update_team_member(self, member_id, name, role, bio='', photo_path=''):
        with self._get_conn() as conn:
            conn.execute("UPDATE team_members SET name=?, role=?, bio=?, photo_path=? WHERE id=?",
                         (name, role, bio, photo_path, member_id))

    def delete_team_member(self, member_id):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM team_members WHERE id=?", (member_id,))

    # ── Settings ──────────────────────────────────────────────────────────────
    def get_setting(self, key, default=''):
        with self._get_conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, key, value):
        with self._get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))

    def get_all_settings(self):
        with self._get_conn() as conn:
            rows = conn.execute("SELECT * FROM settings").fetchall()
        return {r['key']: r['value'] for r in rows}

    # ── Feedback ──────────────────────────────────────────────────────────────
    def save_feedback(self, user_id, message):
        with self._get_conn() as conn:
            conn.execute("INSERT INTO feedback (user_id, message) VALUES (?,?)", (user_id, message))

    def get_all_feedback(self):
        with self._get_conn() as conn:
            rows = conn.execute("""SELECT f.*, u.username FROM feedback f
                                   LEFT JOIN users u ON f.user_id=u.id
                                   ORDER BY f.timestamp DESC""").fetchall()
        return [dict(r) for r in rows]

    # ── Stats ─────────────────────────────────────────────────────────────────
    def get_stats(self):
        with self._get_conn() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0]
            total_revenue = conn.execute("SELECT COALESCE(SUM(amount),0) FROM payment_history").fetchone()[0]
            total_separations = conn.execute("SELECT COUNT(*) FROM separation_history").fetchone()[0]
            total_credits_sold = conn.execute("SELECT COALESCE(SUM(credits_purchased),0) FROM payment_history").fetchone()[0]
        return {
            'total_users': total_users,
            'total_revenue': total_revenue,
            'total_separations': total_separations,
            'total_credits_sold': total_credits_sold,
        }
