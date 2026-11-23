import sqlite3
from typing import Optional


_CREATE_ACTIVITY_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS activity_logs (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id  INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
    event_type     TEXT NOT NULL,
    resource_type  TEXT,
    resource_id    INTEGER,
    outcome        TEXT NOT NULL CHECK(outcome IN ('SUCCESS', 'DENIED')),
    status_code    INTEGER,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
)
"""


def record_activity(
    connection: sqlite3.Connection,
    *,
    event_type: str,
    outcome: str,
    actor_user_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    status_code: Optional[int] = None,
) -> None:
    connection.execute(_CREATE_ACTIVITY_LOGS_TABLE)
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_activity_actor_time
           ON activity_logs(actor_user_id, created_at)"""
    )
    connection.execute(
        """INSERT INTO activity_logs
           (actor_user_id, event_type, resource_type, resource_id, outcome, status_code)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (actor_user_id, event_type, resource_type, resource_id, outcome, status_code),
    )


def record_activity_to_db(
    database_path: str,
    *,
    event_type: str,
    outcome: str,
    actor_user_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    status_code: Optional[int] = None,
) -> None:
    connection = sqlite3.connect(database_path)
    try:
        record_activity(
            connection,
            event_type=event_type,
            outcome=outcome,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            status_code=status_code,
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        raise
    finally:
        connection.close()
