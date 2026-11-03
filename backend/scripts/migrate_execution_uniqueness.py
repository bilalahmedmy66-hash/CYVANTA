import sqlite3
from pathlib import Path

DATABASE = Path(__file__).resolve().parents[1] / "cyvanta.db"


def main():
    connection = sqlite3.connect(DATABASE)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")

        existing_table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'execution_records'
            """
        ).fetchone()

        if existing_table is None:
            raise RuntimeError(
                "execution_records table does not exist. Migration stopped."
            )

        duplicates = connection.execute(
            """
            SELECT action_request_id, COUNT(*)
            FROM execution_records
            GROUP BY action_request_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()

        if duplicates:
            raise RuntimeError(
                f"Duplicate execution records found. Migration stopped: {duplicates}"
            )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            uq_execution_action_request
            ON execution_records (action_request_id)
            """
        )

        index = connection.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'index'
              AND name = 'uq_execution_action_request'
            """
        ).fetchone()

        if index is None or "UNIQUE INDEX" not in index[0].upper():
            raise RuntimeError(
                "Unique execution index verification failed."
            )

        connection.commit()
        print("Unique execution index successfully created or already exists.")
        print("Migration committed.")

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    main()