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

        CREATE TABLE IF NOT EXISTS equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            serial_number TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'available',
            calibration_interval_days INTEGER NOT NULL DEFAULT 365,
            last_calibration_date DATE,
            next_calibration_date DATE,
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS equipment_calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            calibration_date DATE NOT NULL,
            calibration_result TEXT NOT NULL,
            calibration_value REAL,
            calibrated_by TEXT NOT NULL DEFAULT '',
            certificate_number TEXT NOT NULL DEFAULT '',
            next_calibration_date DATE,
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS measurement_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_id INTEGER NOT NULL,
            task_name TEXT NOT NULL,
            responsible_person TEXT NOT NULL DEFAULT '',
            measurement_date DATE,
            sampling_start_time TEXT,
            sampling_end_time TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            site_notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stage_id) REFERENCES stages(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS task_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            equipment_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES measurement_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE,
            UNIQUE(task_id, equipment_id)
        );

        CREATE TABLE IF NOT EXISTS task_execution_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            execution_date DATE,
            weather_condition TEXT NOT NULL DEFAULT '',
            ambient_noise_level REAL,
            temperature REAL,
            humidity REAL,
            site_photos_path TEXT NOT NULL DEFAULT '',
            environment_notes TEXT NOT NULL DEFAULT '',
            executor TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES measurement_tasks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS task_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            photo_path TEXT NOT NULL,
            photo_description TEXT NOT NULL DEFAULT '',
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES measurement_tasks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS measurement_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_id INTEGER NOT NULL,
            version_number TEXT NOT NULL,
            version_name TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            modification_description TEXT NOT NULL DEFAULT '',
            data_source TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by TEXT NOT NULL DEFAULT '',
            review_time TIMESTAMP,
            review_comment TEXT NOT NULL DEFAULT '',
            parent_version_id INTEGER,
            session_id INTEGER,
            conclusion_snapshot TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stage_id) REFERENCES stages(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_version_id) REFERENCES measurement_versions(id) ON DELETE SET NULL,
            FOREIGN KEY (session_id) REFERENCES measurement_sessions(id) ON DELETE SET NULL,
            UNIQUE(stage_id, version_number)
        );

        CREATE TABLE IF NOT EXISTS version_point_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL,
            point_id INTEGER,
            label TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            change_type TEXT NOT NULL DEFAULT 'unchanged',
            FOREIGN KEY (version_id) REFERENCES measurement_versions(id) ON DELETE CASCADE,
            FOREIGN KEY (point_id) REFERENCES measurement_points(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS version_acoustic_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL,
            point_label TEXT NOT NULL,
            sound_pressure REAL,
            reverberation_time REAL,
            speech_clarity REAL,
            notes TEXT NOT NULL DEFAULT '',
            change_type TEXT NOT NULL DEFAULT 'unchanged',
            FOREIGN KEY (version_id) REFERENCES measurement_versions(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS version_change_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL,
            change_category TEXT NOT NULL,
            change_detail TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (version_id) REFERENCES measurement_versions(id) ON DELETE CASCADE
        );
    """)

    cursor.execute("PRAGMA table_info(measurement_sessions)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'task_id' not in columns:
        cursor.execute("""
            ALTER TABLE measurement_sessions ADD COLUMN task_id INTEGER
            REFERENCES measurement_tasks(id) ON DELETE SET NULL
        """)

    def migrate_table(table_name, create_sql, expected_columns):
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_cols = [col[1] for col in cursor.fetchall()]
        expected_col_names = [c.split()[0] for c in expected_columns]
        if set(existing_cols) != set(expected_col_names) or not existing_cols:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            cursor.execute(create_sql)

    migrate_table("equipment", """
        CREATE TABLE equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            serial_number TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'available',
            calibration_interval_days INTEGER NOT NULL DEFAULT 365,
            last_calibration_date DATE,
            next_calibration_date DATE,
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """, [
        "id", "name", "type", "model", "serial_number", "status",
        "calibration_interval_days", "last_calibration_date", "next_calibration_date",
        "notes", "created_at"
    ])

    migrate_table("equipment_calibration", """
        CREATE TABLE equipment_calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_id INTEGER NOT NULL,
            calibration_date DATE NOT NULL,
            calibration_result TEXT NOT NULL,
            calibration_value REAL,
            calibrated_by TEXT NOT NULL DEFAULT '',
            certificate_number TEXT NOT NULL DEFAULT '',
            next_calibration_date DATE,
            notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE
        )
    """, [
        "id", "equipment_id", "calibration_date", "calibration_result",
        "calibration_value", "calibrated_by", "certificate_number",
        "next_calibration_date", "notes", "created_at"
    ])

    migrate_table("measurement_tasks", """
        CREATE TABLE measurement_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_id INTEGER NOT NULL,
            task_name TEXT NOT NULL,
            responsible_person TEXT NOT NULL DEFAULT '',
            measurement_date DATE,
            sampling_start_time TEXT,
            sampling_end_time TEXT,
            status TEXT NOT NULL DEFAULT 'planned',
            site_notes TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stage_id) REFERENCES stages(id) ON DELETE CASCADE
        )
    """, [
        "id", "stage_id", "task_name", "responsible_person", "measurement_date",
        "sampling_start_time", "sampling_end_time", "status", "site_notes", "created_at"
    ])

    migrate_table("task_equipment", """
        CREATE TABLE task_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            equipment_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES measurement_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (equipment_id) REFERENCES equipment(id) ON DELETE CASCADE,
            UNIQUE(task_id, equipment_id)
        )
    """, [
        "id", "task_id", "equipment_id", "created_at"
    ])

    migrate_table("task_execution_records", """
        CREATE TABLE task_execution_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            execution_date DATE,
            weather_condition TEXT NOT NULL DEFAULT '',
            ambient_noise_level REAL,
            temperature REAL,
            humidity REAL,
            site_photos_path TEXT NOT NULL DEFAULT '',
            environment_notes TEXT NOT NULL DEFAULT '',
            executor TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES measurement_tasks(id) ON DELETE CASCADE
        )
    """, [
        "id", "task_id", "execution_date", "weather_condition", "ambient_noise_level",
        "temperature", "humidity", "site_photos_path", "environment_notes",
        "executor", "created_at"
    ])

    migrate_table("task_photos", """
        CREATE TABLE task_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            photo_path TEXT NOT NULL,
            photo_description TEXT NOT NULL DEFAULT '',
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES measurement_tasks(id) ON DELETE CASCADE
        )
    """, [
        "id", "task_id", "photo_path", "photo_description", "uploaded_at"
    ])

    migrate_table("measurement_versions", """
        CREATE TABLE measurement_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_id INTEGER NOT NULL,
            version_number TEXT NOT NULL,
            version_name TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            modification_description TEXT NOT NULL DEFAULT '',
            data_source TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL DEFAULT 'pending',
            reviewed_by TEXT NOT NULL DEFAULT '',
            review_time TIMESTAMP,
            review_comment TEXT NOT NULL DEFAULT '',
            parent_version_id INTEGER,
            session_id INTEGER,
            conclusion_snapshot TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (stage_id) REFERENCES stages(id) ON DELETE CASCADE,
            FOREIGN KEY (parent_version_id) REFERENCES measurement_versions(id) ON DELETE SET NULL,
            FOREIGN KEY (session_id) REFERENCES measurement_sessions(id) ON DELETE SET NULL,
            UNIQUE(stage_id, version_number)
        )
    """, [
        "id", "stage_id", "version_number", "version_name", "created_by",
        "update_time", "modification_description", "data_source", "review_status",
        "reviewed_by", "review_time", "review_comment", "parent_version_id",
        "session_id", "conclusion_snapshot", "created_at"
    ])

    migrate_table("version_point_snapshots", """
        CREATE TABLE version_point_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL,
            point_id INTEGER,
            label TEXT NOT NULL,
            x REAL NOT NULL,
            y REAL NOT NULL,
            change_type TEXT NOT NULL DEFAULT 'unchanged',
            FOREIGN KEY (version_id) REFERENCES measurement_versions(id) ON DELETE CASCADE,
            FOREIGN KEY (point_id) REFERENCES measurement_points(id) ON DELETE SET NULL
        )
    """, [
        "id", "version_id", "point_id", "label", "x", "y", "change_type"
    ])

    migrate_table("version_acoustic_snapshots", """
        CREATE TABLE version_acoustic_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL,
            point_label TEXT NOT NULL,
            sound_pressure REAL,
            reverberation_time REAL,
            speech_clarity REAL,
            notes TEXT NOT NULL DEFAULT '',
            change_type TEXT NOT NULL DEFAULT 'unchanged',
            FOREIGN KEY (version_id) REFERENCES measurement_versions(id) ON DELETE CASCADE
        )
    """, [
        "id", "version_id", "point_label", "sound_pressure", "reverberation_time",
        "speech_clarity", "notes", "change_type"
    ])

    migrate_table("version_change_logs", """
        CREATE TABLE version_change_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id INTEGER NOT NULL,
            change_category TEXT NOT NULL,
            change_detail TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (version_id) REFERENCES measurement_versions(id) ON DELETE CASCADE
        )
    """, [
        "id", "version_id", "change_category", "change_detail", "old_value",
        "new_value", "created_at"
    ])

    conn.commit()
    conn.close()
