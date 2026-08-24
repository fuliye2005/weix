"""Small, idempotent schema upgrades for the application's SQLite database."""

from sqlalchemy import inspect, text


_MESSAGE_COLUMNS: dict[str, str] = {
    "direction": "VARCHAR(16) NOT NULL DEFAULT 'inbound'",
    "status": "VARCHAR(32) NOT NULL DEFAULT 'received'",
    "reply_to_msg_id": "VARCHAR(128)",
    "attempt_id": "VARCHAR(64)",
    "send_method": "VARCHAR(32)",
    "reply_source": "VARCHAR(32)",
    "error_code": "VARCHAR(64)",
    "error_message": "TEXT",
    "sent_at": "DATETIME",
    "target_id": "VARCHAR(128)",
    "target_name": "VARCHAR(128)",
}

_MESSAGE_INDEXES: dict[str, tuple[str, bool]] = {
    "ix_messages_direction": ("direction", False),
    "ix_messages_status": ("status", False),
    "ix_messages_reply_to_msg_id": ("reply_to_msg_id", False),
    "ix_messages_attempt_id": ("attempt_id", True),
    "ix_messages_target_id": ("target_id", False),
}


def migrate_schema(connection) -> None:
    """Upgrade existing tables without deleting user data.

    SQLAlchemy's ``create_all`` does not add columns to an already existing
    table.  The application currently uses SQLite, so a short explicit
    ``ALTER TABLE`` migration is enough and remains safe to run on every
    startup.
    """
    inspector = inspect(connection)
    if "messages" not in inspector.get_table_names():
        return

    existing = {column["name"] for column in inspector.get_columns("messages")}
    for name, definition in _MESSAGE_COLUMNS.items():
        if name in existing:
            continue
        connection.execute(
            text(f'ALTER TABLE messages ADD COLUMN "{name}" {definition}')
        )

    existing_indexes = {
        index["name"] for index in inspect(connection).get_indexes("messages")
    }
    for index_name, (column_name, is_unique) in _MESSAGE_INDEXES.items():
        if index_name in existing_indexes:
            continue
        unique_sql = "UNIQUE " if is_unique else ""
        connection.execute(
            text(
                f'CREATE {unique_sql}INDEX "{index_name}" '
                f'ON messages ("{column_name}")'
            )
        )
