"""SQLite storage: users, settings and game-session summaries (never webcam frames)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS Users (
    user_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL UNIQUE,
    email      TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Settings (
    setting_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id              INTEGER NOT NULL UNIQUE REFERENCES Users(user_id) ON DELETE CASCADE,
    steering_sensitivity REAL NOT NULL DEFAULT 1.0,
    acceleration_gesture TEXT NOT NULL DEFAULT 'open_palm',
    brake_gesture        TEXT NOT NULL DEFAULT 'fist',
    dead_zone            REAL NOT NULL DEFAULT 0.05
);

CREATE TABLE IF NOT EXISTS Game_Sessions (
    session_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES Users(user_id) ON DELETE CASCADE,
    game_name        TEXT,
    session_duration REAL NOT NULL DEFAULT 0,
    steering_events  INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

SETTING_FIELDS = ("steering_sensitivity", "acceleration_gesture", "brake_gesture", "dead_zone")
DEFAULT_USERNAME = "default"


class Database:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.init()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------- users
    def create_user(self, username: str, email: Optional[str] = None) -> int:
        try:
            with self._connect() as conn:
                cur = conn.execute("INSERT INTO Users (username, email) VALUES (?, ?)",
                                   (username, email))
                return int(cur.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"User '{username}' already exists") from exc

    def get_user(self, user_id: int) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM Users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_name(self, username: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM Users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def get_or_create_default_user(self) -> int:
        user = self.get_user_by_name(DEFAULT_USERNAME)
        if user:
            return int(user["user_id"])
        return self.create_user(DEFAULT_USERNAME, "default@local")

    # ------------------------------------------------------------- settings
    def get_settings(self, user_id: int) -> Dict:
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO Settings (user_id) VALUES (?)", (user_id,))
            row = conn.execute("SELECT * FROM Settings WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row)

    def save_settings(self, user_id: int, **fields) -> Dict:
        unknown = set(fields) - set(SETTING_FIELDS)
        if unknown:
            raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
        self.get_settings(user_id)  # make sure the row exists
        if fields:
            assignments = ", ".join(f"{name} = ?" for name in fields)
            with self._connect() as conn:
                conn.execute(f"UPDATE Settings SET {assignments} WHERE user_id = ?",
                             (*fields.values(), user_id))
        return self.get_settings(user_id)

    # ------------------------------------------------------------- sessions
    def record_session(self, user_id: int, game_name: str, duration_seconds: float,
                       steering_events: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO Game_Sessions (user_id, game_name, session_duration, steering_events) "
                "VALUES (?, ?, ?, ?)",
                (user_id, game_name, round(float(duration_seconds), 2), int(steering_events)),
            )
            return int(cur.lastrowid)

    def list_sessions(self, user_id: int, limit: int = 20) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM Game_Sessions WHERE user_id = ? "
                "ORDER BY session_id DESC LIMIT ?", (user_id, limit)).fetchall()
        return [dict(r) for r in rows]
