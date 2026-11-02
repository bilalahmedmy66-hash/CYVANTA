import sqlite3
from pathlib import Path

DATABASE = Path(__file__).resolve().parents[1] / "cyvanta.db"

def main():
    connection = sqlite3.connect(DATABASE)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")

        existing_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(asset_authorizations)"
            ).fetchall()
        }

        if not existing_columns:
            raise RuntimeError(
                "asset_authorizations table does not exist. Migration stopped."
            )

        additions = {
            "suspended_by": (
                "ALTER TABLE asset_authorizations "
                "ADD COLUMN suspended_by VARCHAR(36) REFERENCES users(id)"
            ),
            "suspended_at": (
                "ALTER TABLE asset_authorizations "
                "ADD COLUMN suspended_at DATETIME"
            ),
            "suspension_reason": (
                "ALTER TABLE asset_authorizations "
                "ADD COLUMN suspension_reason VARCHAR(1000)"
            ),
        }

        for column, statement in additions.items():
            if column not in existing_columns:
                connection.execute(statement)
                print(f"Added column: {column}")
            else:
                print(f"Column already exists: {column}")

        connection.execute("""
            CREATE TABLE IF NOT EXISTS authorization_lifecycle_events (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                organization_id VARCHAR(36) NOT NULL,
                authorization_id VARCHAR(36) NOT NULL,
                event_type VARCHAR(50) NOT NULL,
                actor_id VARCHAR(36) NOT NULL,
                reason VARCHAR(1000) NOT NULL,
                details JSON NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY (organization_id) REFERENCES organizations(id),
                FOREIGN KEY (authorization_id) REFERENCES asset_authorizations(id),
                FOREIGN KEY (actor_id) REFERENCES users(id)
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            ix_authorization_lifecycle_events_organization_id
            ON authorization_lifecycle_events (organization_id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            ix_authorization_lifecycle_events_authorization_id
            ON authorization_lifecycle_events (authorization_id)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            ix_authorization_lifecycle_events_event_type
            ON authorization_lifecycle_events (event_type)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            ix_authorization_lifecycle_events_created_at
            ON authorization_lifecycle_events (created_at)
        """)


        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_authorization_lifecycle_update
            BEFORE UPDATE ON authorization_lifecycle_events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Authorization lifecycle events are append-only'
                );
            END
        """)

        connection.execute("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_authorization_lifecycle_delete
            BEFORE DELETE ON authorization_lifecycle_events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'Authorization lifecycle events are append-only'
                );
            END
        """)

        print("Append-only UPDATE and DELETE triggers ensured.")

        connection.commit()
        print("SQLite lifecycle migration committed.")

    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

if __name__ == "__main__":
    main()
