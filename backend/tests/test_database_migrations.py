from sqlalchemy import create_engine, inspect, text

from app.db.migrations import migrate_schema


def test_messages_migration_adds_new_log_columns_to_existing_table():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE messages ("
                "id INTEGER PRIMARY KEY, "
                "msg_id VARCHAR(64), "
                "content TEXT"
                ")"
            )
        )

        migrate_schema(connection)
        columns = {
            column["name"]: column for column in inspect(connection).get_columns("messages")
        }

        assert "direction" in columns
        assert "status" in columns
        assert "reply_to_msg_id" in columns
        assert "attempt_id" in columns
        assert "error_message" in columns
        assert "error_stage" in columns
        assert "target_id" in columns

        row = connection.execute(
            text("SELECT direction, status FROM messages")
        ).fetchone()
        assert row is None

        migrate_schema(connection)
        index_names = {
            index["name"] for index in inspect(connection).get_indexes("messages")
        }
        assert "ix_messages_direction" in index_names
        assert "ix_messages_status" in index_names
