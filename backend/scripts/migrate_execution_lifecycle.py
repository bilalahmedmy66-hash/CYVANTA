import sqlite3
from pathlib import Path

DATABASE = Path(__file__).resolve().parents[1] / "cyvanta.db"


def main():
    connection = sqlite3.connect(DATABASE)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")

        required_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        required = {
            "execution_records",
            "organizations",
            "users",
        }

        missing = required - required_tables

        if missing:
            raise RuntimeError(
                f"Required tables are missing: {sorted(missing)}"
            )

        connection.execute("""
            CREATE TABLE IF NOT EXISTS execution_lifecycle_events (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                organization_id VARCHAR(36) NOT NULL,
                execution_id VARCHAR(36) NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                actor_id VARCHAR(36),
                from_status VARCHAR(30),
                to_status VARCHAR(30) NOT NULL,
                details JSON NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (execution_id) REFERENCES execution_records(id),
                FOREIGN KEY (actor_id) REFERENCES users(id)
            )
        """)

        indexes = {
            "ix_execution_lifecycle_events_organization_id":
                "organization_id",
            "ix_execution_lifecycle_events_execution_id":
                "execution_id",
            "ix_execution_lifecycle_events_event_type":
                "event_type",
            "ix_execution_lifecycle_events_created_at":
                "created_at",
        }

        for index_name, column in indexes.items():
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} "
                f"ON execution_lifecycle_events ({column})"
            )

        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_execution_lifecycle_update
            BEFORE UPDATE ON execution_lifecycle_events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Execution lifecycle events are append-only'
                );
            END
        """)

        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_execution_lifecycle_delete
            BEFORE DELETE ON execution_lifecycle_events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Execution lifecycle events are append-only'
                );
            END
        """)

        connection.commit()
        print("Execution lifecycle table, indexes and triggers ensured.")
        print("SQLite migration committed.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()
