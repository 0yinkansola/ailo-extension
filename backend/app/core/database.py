"""
SQLite persistence layer for AILO user accounts.

Uses Python's built-in sqlite3 — no ORM dependency.
The database file lives at the backend root: ailo.db
"""

import json
import sqlite3
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent.parent / "ailo.db"

# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Schema init
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they do not already exist."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id          TEXT PRIMARY KEY,
                username         TEXT UNIQUE NOT NULL,
                email            TEXT UNIQUE NOT NULL,
                hashed_password  TEXT NOT NULL,
                target_language  TEXT NOT NULL DEFAULT 'fr',
                proficiency_level TEXT NOT NULL DEFAULT 'A2',
                interests        TEXT DEFAULT '[]',
                created_at       INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id          TEXT PRIMARY KEY,
                weights_json     TEXT NOT NULL DEFAULT '{}',
                beta_params_json TEXT NOT NULL DEFAULT '{}',
                history_json     TEXT NOT NULL DEFAULT '[]',
                updated_at       INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def db_create_user(
    user_id: str,
    username: str,
    email: str,
    hashed_password: str,
    target_language: str,
) -> sqlite3.Row | None:
    """Insert a new user row and return it, or None on duplicate email/username."""
    import time as _time

    created_at = int(_time.time())
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO users
                    (user_id, username, email, hashed_password, target_language,
                     proficiency_level, interests, created_at)
                VALUES (?, ?, ?, ?, ?, 'A2', '[]', ?)
                """,
                (user_id, username, email, hashed_password, target_language, created_at),
            )
            conn.commit()
        return db_get_user_by_id(user_id)
    except sqlite3.IntegrityError:
        return None


def db_get_user_by_email(email: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    return row


def db_get_user_by_id(user_id: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row


def db_get_preferences(user_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM user_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "weights":     json.loads(row["weights_json"]),
        "beta_params": json.loads(row["beta_params_json"]),
        "history":     json.loads(row["history_json"]),
        "updated_at":  row["updated_at"],
    }


def db_save_preferences(
    user_id: str,
    weights: dict,
    beta_params: dict,
    history: list,
) -> None:
    import time as _t
    now = int(_t.time())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_preferences
                (user_id, weights_json, beta_params_json, history_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                weights_json     = excluded.weights_json,
                beta_params_json = excluded.beta_params_json,
                history_json     = excluded.history_json,
                updated_at       = excluded.updated_at
            """,
            (
                user_id,
                json.dumps(weights),
                json.dumps(beta_params),
                json.dumps(history),
                now,
            ),
        )
        conn.commit()


def db_update_user(user_id: str, **fields) -> sqlite3.Row | None:
    """Update allowed fields (proficiency_level, target_language, interests).

    interests must be passed as a Python list; it will be JSON-serialised here.
    Returns the updated row, or None if user_id does not exist.
    """
    allowed = {"proficiency_level", "target_language", "interests"}
    updates: dict[str, object] = {}

    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "interests":
            # Serialize list to JSON string for storage
            if isinstance(value, list):
                updates[key] = json.dumps(value)
            else:
                updates[key] = value
        else:
            updates[key] = value

    if not updates:
        return db_get_user_by_id(user_id)

    set_clause = ", ".join(f"{col} = ?" for col in updates)
    values = list(updates.values()) + [user_id]

    with get_connection() as conn:
        conn.execute(
            f"UPDATE users SET {set_clause} WHERE user_id = ?",
            values,
        )
        conn.commit()

    return db_get_user_by_id(user_id)
