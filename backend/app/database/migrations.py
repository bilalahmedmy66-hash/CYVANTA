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

# CYVANTA_ACTIVE_DEFENSE_MIGRATIONS_V1
ACTIVE_DEFENSE_MIGRATION_VERSION = "20261108_001_active_defense_audit_immutability"

ACTIVE_DEFENSE_APPEND_ONLY_TABLES = (
    "threat_event_lifecycle_events",
    "containment_action_events",
    "alert_delivery_events",
    "platform_emergency_stop_events",
    "platform_operator_events",
    "authorization_lifecycle_events",
    "execution_lifecycle_events",
)


def ensure_active_defense_migrations(engine):
    """Install versioned SQLite append-only protections; safe to rerun."""
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS cyvanta_schema_migrations (
                version VARCHAR(120) PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
        """))
        applied = connection.execute(
            text("SELECT 1 FROM cyvanta_schema_migrations WHERE version = :version"),
            {"version": ACTIVE_DEFENSE_MIGRATION_VERSION},
        ).first()
        if applied:
            return

        existing = set(inspect(connection).get_table_names())
        missing = sorted(set(ACTIVE_DEFENSE_APPEND_ONLY_TABLES) - existing)
        if missing:
            raise RuntimeError("Missing lifecycle tables: " + ", ".join(missing))

        for table_name in ACTIVE_DEFENSE_APPEND_ONLY_TABLES:
            connection.execute(text(f"""
                CREATE TRIGGER IF NOT EXISTS prevent_{table_name}_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, 'append-only audit history cannot be updated');
                END
            """))
            connection.execute(text(f"""
                CREATE TRIGGER IF NOT EXISTS prevent_{table_name}_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, 'append-only audit history cannot be deleted');
                END
            """))

        connection.execute(
            text("""
                INSERT INTO cyvanta_schema_migrations (version, applied_at)
                VALUES (:version, CURRENT_TIMESTAMP)
            """),
            {"version": ACTIVE_DEFENSE_MIGRATION_VERSION},
        )
# CYVANTA_SECURITY_SIGNALS_MIGRATION_V1

SECURITY_SIGNALS_MIGRATION_VERSION = (
    "20261109_001_security_signals_append_only"
)


def ensure_security_signals_migrations(engine):
    """
    Install append-only protections for trusted security signals.
    Safe to rerun on SQLite.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS cyvanta_schema_migrations (
                version VARCHAR(120) PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
        """))

        applied = connection.execute(
            text("""
                SELECT 1
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {"version": SECURITY_SIGNALS_MIGRATION_VERSION},
        ).first()

        if applied:
            return

        existing = set(inspect(connection).get_table_names())

        if "security_signals" not in existing:
            raise RuntimeError(
                "Missing security_signals table. "
                "Ensure SQLAlchemy models are registered before migration."
            )

        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_security_signals_update
            BEFORE UPDATE ON security_signals
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'security signals cannot be updated'
                );
            END
        """))

        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_security_signals_delete
            BEFORE DELETE ON security_signals
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'security signals cannot be deleted'
                );
            END
        """))

        connection.execute(
            text("""
                INSERT INTO cyvanta_schema_migrations
                    (version, applied_at)
                VALUES (:version, CURRENT_TIMESTAMP)
            """),
            {"version": SECURITY_SIGNALS_MIGRATION_VERSION},
        )

# CYVANTA_PLATFORM_DETECTION_MIGRATION_V1

PLATFORM_DETECTION_MIGRATION_VERSION = (
    "20261109_001_platform_detection_audit_immutability"
)


def ensure_platform_detection_migrations(engine):
    """
    Install append-only protections for platform detection finding events.
    The current finding projection remains mutable.
    Safe to rerun on SQLite.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS cyvanta_schema_migrations (
                version VARCHAR(120) PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
        """))

        applied = connection.execute(
            text("""
                SELECT 1
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {"version": PLATFORM_DETECTION_MIGRATION_VERSION},
        ).first()

        if applied:
            return

        existing = set(inspect(connection).get_table_names())

        required_tables = {
            "platform_detection_findings",
            "platform_detection_finding_events",
        }

        missing = sorted(required_tables - existing)

        if missing:
            raise RuntimeError(
                "Missing platform detection tables: "
                + ", ".join(missing)
            )

        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_platform_detection_finding_events_update
            BEFORE UPDATE ON platform_detection_finding_events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'platform detection finding history cannot be updated'
                );
            END
        """))

        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_platform_detection_finding_events_delete
            BEFORE DELETE ON platform_detection_finding_events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'platform detection finding history cannot be deleted'
                );
            END
        """))

        connection.execute(
            text("""
                INSERT INTO cyvanta_schema_migrations
                    (version, applied_at)
                VALUES (:version, CURRENT_TIMESTAMP)
            """),
            {"version": PLATFORM_DETECTION_MIGRATION_VERSION},
        )


# ==========================================
# CYVANTA SIMULATION DISPATCH MIGRATION V1
# ==========================================

SIMULATION_DISPATCH_MIGRATION_VERSION = (
    "20261112_001_simulation_dispatch_audit"
)


def ensure_simulation_dispatch_migrations(engine):
    """
    Install append-only protections for simulation dispatch events.
    Safe to rerun on SQLite.
    """

    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS cyvanta_schema_migrations (
                version VARCHAR(120) PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
        """))

        applied = connection.execute(
            text("""
                SELECT 1
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {"version": SIMULATION_DISPATCH_MIGRATION_VERSION},
        ).first()

        if applied:
            return

        existing = set(inspect(connection).get_table_names())

        required_tables = {
            "simulation_dispatches",
            "simulation_dispatch_events",
        }

        missing = sorted(required_tables - existing)

        if missing:
            raise RuntimeError(
                "Missing simulation dispatch tables: "
                + ", ".join(missing)
            )

        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_simulation_dispatch_events_update
            BEFORE UPDATE ON simulation_dispatch_events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'simulation dispatch history cannot be updated'
                );
            END
        """))

        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS
            prevent_simulation_dispatch_events_delete
            BEFORE DELETE ON simulation_dispatch_events
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'simulation dispatch history cannot be deleted'
                );
            END
        """))

        connection.execute(
            text("""
                INSERT INTO cyvanta_schema_migrations
                    (version, applied_at)
                VALUES (:version, CURRENT_TIMESTAMP)
            """),
            {"version": SIMULATION_DISPATCH_MIGRATION_VERSION},
        )

# ==========================================
# CYVANTA AUDIT LOG IMMUTABILITY MIGRATION V1
# ==========================================

AUDIT_LOG_MIGRATION_VERSION = (
    "20261118_001_audit_logs_immutability"
)


def ensure_audit_log_migrations(engine):
    """
    Protect audit_logs against UPDATE and DELETE.
    Safe to rerun on SQLite.
    """

    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS cyvanta_schema_migrations (
                version VARCHAR(120) PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
        """))

        applied = connection.execute(
            text("""
                SELECT 1
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {"version": AUDIT_LOG_MIGRATION_VERSION},
        ).first()

        if applied:
            return

        existing = set(inspect(connection).get_table_names())

        if "audit_logs" not in existing:
            raise RuntimeError("Missing audit_logs table")

        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS prevent_audit_logs_update
            BEFORE UPDATE ON audit_logs
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'append-only audit history cannot be updated'
                );
            END
        """))

        connection.execute(text("""
            CREATE TRIGGER IF NOT EXISTS prevent_audit_logs_delete
            BEFORE DELETE ON audit_logs
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'append-only audit history cannot be deleted'
                );
            END
        """))

        connection.execute(
            text("""
                INSERT INTO cyvanta_schema_migrations
                    (version, applied_at)
                VALUES (:version, CURRENT_TIMESTAMP)
            """),
            {"version": AUDIT_LOG_MIGRATION_VERSION},
        )

# CYVANTA_LOGIN_RATE_LIMIT_MIGRATION_V1

LOGIN_RATE_LIMIT_MIGRATION_VERSION = (
    "20261118_002_login_rate_limits"
)


def ensure_login_rate_limit_migrations(engine):
    """
    Create mutable login rate-limit buckets.
    Raw IP addresses and account identifiers are never stored.
    Safe to rerun on SQLite.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS cyvanta_schema_migrations (
                version VARCHAR(120) PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
        """))

        applied = connection.execute(
            text("""
                SELECT 1
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {"version": LOGIN_RATE_LIMIT_MIGRATION_VERSION},
        ).first()

        if applied:
            return

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS login_rate_limits (
                scope VARCHAR(30) NOT NULL,
                fingerprint VARCHAR(64) NOT NULL,
                window_started_at DATETIME NOT NULL,
                attempts INTEGER NOT NULL CHECK (attempts > 0),
                PRIMARY KEY (scope, fingerprint)
            )
        """))

        columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "login_rate_limits"
            )
        }

        required_columns = {
            "scope",
            "fingerprint",
            "window_started_at",
            "attempts",
        }

        if not required_columns.issubset(columns):
            raise RuntimeError(
                "login_rate_limits table has an invalid schema."
            )

        connection.execute(
            text("""
                INSERT INTO cyvanta_schema_migrations
                    (version, applied_at)
                VALUES (:version, CURRENT_TIMESTAMP)
            """),
            {"version": LOGIN_RATE_LIMIT_MIGRATION_VERSION},
        )


# CYVANTA_V2_AI_EXTERNAL_ANALYSIS_POLICY

AI_EXTERNAL_ANALYSIS_POLICY_MIGRATION_VERSION = (
    "20261126_001_ai_external_analysis_policy"
)


def ensure_ai_external_analysis_policy_migrations(engine):
    """Create organization-scoped external AI authorization; Restricted by default."""
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS cyvanta_schema_migrations (
                version VARCHAR(120) PRIMARY KEY,
                applied_at DATETIME NOT NULL
            )
        """))

        applied = connection.execute(
            text("""
                SELECT 1
                FROM cyvanta_schema_migrations
                WHERE version = :version
            """),
            {"version": AI_EXTERNAL_ANALYSIS_POLICY_MIGRATION_VERSION},
        ).first()

        if applied:
            return

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_external_analysis_policies (
                organization_id VARCHAR(36) PRIMARY KEY
                    REFERENCES organizations(id),
                external_analysis_enabled BOOLEAN NOT NULL DEFAULT 0,
                approved_by VARCHAR(36)
                    REFERENCES users(id),
                approved_at DATETIME
            )
        """))

        columns = {
            column["name"]
            for column in inspect(connection).get_columns(
                "ai_external_analysis_policies"
            )
        }
        required_columns = {
            "organization_id",
            "external_analysis_enabled",
            "approved_by",
            "approved_at",
        }
        if not required_columns.issubset(columns):
            raise RuntimeError(
                "ai_external_analysis_policies table has an invalid schema."
            )

        connection.execute(
            text("""
                INSERT INTO cyvanta_schema_migrations
                    (version, applied_at)
                VALUES (:version, CURRENT_TIMESTAMP)
            """),
            {"version": AI_EXTERNAL_ANALYSIS_POLICY_MIGRATION_VERSION},
        )
