import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "acoustics.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS stages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            location TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            plan_width REAL NOT NULL DEFAULT 20.0,
            plan_height REAL NOT NULL DEFAULT 15.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS measurement_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stage_id) REFERENCES stages(id) ON DELETE CASCADE,
            UNIQUE(stage_id, x, y)
        );

        CREATE TABLE IF NOT EXISTS measurement_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_id INTEGER NOT NULL,
            singer_position TEXT NOT NULL DEFAULT '舞台中央',
            audience_count INTEGER NOT NULL DEFAULT 0,
            door_window_state TEXT NOT NULL DEFAULT 'closed',
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stage_id) REFERENCES stages(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS acoustic_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            point_id INTEGER NOT NULL,
            sound_pressure REAL,
            reverberation_time REAL,
            speech_clarity REAL,
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES measurement_sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (point_id) REFERENCES measurement_points(id) ON DELETE CASCADE,
            UNIQUE(session_id, point_id)
        );

        CREATE TABLE IF NOT EXISTS conclusions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            has_abnormal_data INTEGER NOT NULL DEFAULT 0,
            is_confirmed INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stage_id) REFERENCES stages(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS heatmap_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            metric TEXT NOT NULL,
            is_stale INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES measurement_sessions(id) ON DELETE CASCADE,
            UNIQUE(session_id, metric)
        );
    """)

    conn.commit()
    conn.close()
