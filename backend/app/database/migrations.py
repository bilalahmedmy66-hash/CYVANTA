# Idempotent SQLite compatibility migrations for CYVANTA.

from sqlalchemy import inspect, text


def ensure_ai_analysis_job_retry_column(engine) -> None:
    # Add next_retry_at to an existing SQLite AI job table, if needed.
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "ai_analysis_jobs" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("ai_analysis_jobs")}
    if "next_retry_at" in columns:
        return

    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE ai_analysis_jobs ADD COLUMN next_retry_at DATETIME")
        )
