import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "hotel_booking.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _add_column_if_missing(conn, table, column, definition):
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db():
    conn = get_connection()
    c = conn.cursor()

    try:
        c.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc).lower():
            raise

    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','manager','guest')),
        email TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS hotels(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        location TEXT NOT NULL,
        description TEXT,
        image TEXT,
        manager_id INTEGER,
        rating REAL DEFAULT 4.5,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(manager_id) REFERENCES users(id) ON DELETE SET NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS rooms(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER NOT NULL,
        room_number TEXT NOT NULL,
        room_type TEXT NOT NULL,
        price REAL NOT NULL,
        available INTEGER DEFAULT 1,
        image TEXT,
        amenities TEXT,
        FOREIGN KEY(hotel_id) REFERENCES hotels(id) ON DELETE CASCADE,
        UNIQUE(hotel_id,room_number)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS bookings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guest_id INTEGER NOT NULL,
        room_id INTEGER NOT NULL,
        hotel_id INTEGER NOT NULL,
        check_in TEXT NOT NULL,
        check_out TEXT NOT NULL,
        status TEXT DEFAULT 'Booked',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(guest_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(room_id) REFERENCES rooms(id) ON DELETE CASCADE,
        FOREIGN KEY(hotel_id) REFERENCES hotels(id) ON DELETE CASCADE
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS cancellation_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL,
        guest_id INTEGER NOT NULL,
        hotel_id INTEGER NOT NULL,
        reason TEXT,
        status TEXT DEFAULT 'Pending',
        manager_note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TEXT,
        FOREIGN KEY(booking_id) REFERENCES bookings(id) ON DELETE CASCADE,
        FOREIGN KEY(guest_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(hotel_id) REFERENCES hotels(id) ON DELETE CASCADE
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS notifications(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    # Migrations for older databases.
    _add_column_if_missing(conn, "users", "email", "TEXT")
    _add_column_if_missing(conn, "users", "created_at", "TEXT")
    _add_column_if_missing(conn, "hotels", "image", "TEXT")
    _add_column_if_missing(conn, "hotels", "manager_id", "INTEGER")
    _add_column_if_missing(conn, "hotels", "rating", "REAL DEFAULT 4.5")
    _add_column_if_missing(conn, "hotels", "created_at", "TEXT")
    _add_column_if_missing(conn, "rooms", "image", "TEXT")
    _add_column_if_missing(conn, "rooms", "amenities", "TEXT")
    _add_column_if_missing(conn, "bookings", "created_at", "TEXT")

    for username, password, role, email in [
        ("admin", "admin123", "admin", os.getenv("DEMO_ADMIN_EMAIL")),
        ("manager", "manager123", "manager", os.getenv("DEMO_MANAGER_EMAIL")),
        ("guest", "guest123", "guest", os.getenv("DEMO_GUEST_EMAIL")),
    ]:
        c.execute(
            "INSERT OR IGNORE INTO users(username,password,role,email) VALUES(?,?,?,?)",
            (username, generate_password_hash(password), role, email)
        )

    c.execute("UPDATE hotels SET rating=4.5 WHERE rating IS NULL")
    c.execute("UPDATE hotels SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL")
    c.execute("UPDATE users SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL")
    c.execute("UPDATE bookings SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL")

    conn.commit()
    conn.close()


# Imported here only for environment lookup without making app.py responsible for it.
import os