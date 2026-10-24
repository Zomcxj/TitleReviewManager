"""Database bootstrap and schema drift detection tests.

Covers startup paths for three database states, plus the judgment logic of
the read-only drift detection.

These tests target a confirmed release-blocking defect: a database created
by create_all (the local start script path) lacks the alembic_version record,
so running `alembic upgrade head` directly fails with "table already exists",
short-circuiting the container start command `alembic upgrade head && uvicorn ...`
and preventing the service from starting.
"""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.usefixtures("_isolated_env")


@pytest.fixture(name="_isolated_env")
def fixture_isolated_env(tmp_path, monkeypatch):
    """Point DATABASE_URL at a temp database to keep away from the dev database title_service.db"""
    db_file = tmp_path / "boot_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("JWT_SECRET_KEY", "boot-test")
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    yield


def _run_bootstrap(db_path, tmp_path, repair=False):
    """Run db_bootstrap.py in a subprocess (simulating the first half of the container start command)"""
    env = dict(os.environ)
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["JWT_SECRET_KEY"] = "boot-test"
    env["SCHEDULER_ENABLED"] = "0"
    cmd = [sys.executable, "db_bootstrap.py"]
    if repair:
        cmd.append("--repair")
    return subprocess.run(
        cmd,
        capture_output=True, text=True, env=env, cwd=BACKEND_DIR,
    )


class TestBootstrapEmptyDatabase:
    """Scenario 1: brand-new empty database — the migration chain creates all tables"""

    def test_creates_all_tables_from_scratch(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        result = _run_bootstrap(db_path, tmp_path)
        assert result.returncode == 0, f"引导失败:\n{result.stdout}\n{result.stderr}"

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        # The migration chain creates the business tables and records the version
        assert "alembic_version" in tables
        for expected in ("users", "customers", "applications", "materials",
                         "reviews", "system_configs", "login_attempts"):
            assert expected in tables, f"缺少表 {expected}"

    def test_records_alembic_version(self, tmp_path):
        db_path = tmp_path / "fresh_version.db"
        _run_bootstrap(db_path, tmp_path)

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        finally:
            engine.dispose()

        assert row is not None, "引导后应写入 alembic 版本记录"
        assert row[0], "版本号不应为空"


class TestBootstrapLegacyDatabase:
    """Scenario 2: a database created by create_all (has business tables, no version record)

    This is the key scenario that broke container startup before the fix.
    """

    def _make_legacy_db(self, db_path):
        """Create tables with create_all, simulating a database initialized by the local start script"""
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            import models  # noqa: F401
            from database import Base
            Base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()

    def test_bootstrap_succeeds_on_create_all_database(self, tmp_path):
        db_path = tmp_path / "legacy.db"
        self._make_legacy_db(db_path)

        # Precondition: the database has business tables but no version record (exactly the defect trigger)
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            tables = set(inspect(engine).get_table_names())
            assert "users" in tables
            assert "alembic_version" not in tables, "前置条件不成立：不该有版本记录"
        finally:
            engine.dispose()

        # Before the fix this failed with table already exists
        result = _run_bootstrap(db_path, tmp_path)
        assert result.returncode == 0, (
            f"create_all 建出的库应能被接管，实际失败:\n{result.stdout}\n{result.stderr}"
        )
        # logging.StreamHandler writes to stderr by default; check both to avoid misjudging if log config changes
        combined = (result.stdout + result.stderr).lower()
        assert "stamp" in combined or "接管" in combined, (
            f"未走接管路径，输出:\n{result.stdout}\n{result.stderr}"
        )

    def test_takes_over_and_records_version(self, tmp_path):
        db_path = tmp_path / "legacy_takeover.db"
        self._make_legacy_db(db_path)
        _run_bootstrap(db_path, tmp_path)

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.connect() as conn:
                row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
        finally:
            engine.dispose()

        assert row is not None and row[0], "接管后应写入 alembic 版本记录"

    def test_data_preserved_after_takeover(self, tmp_path):
        """The takeover must never lose data"""
        db_path = tmp_path / "legacy_data.db"
        self._make_legacy_db(db_path)

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO users (username, password_hash, role, is_deleted, "
                    "token_version, must_change_password, created_at) "
                    "VALUES ('legacyuser', 'x', 'admin', 0, 0, 0, '2026-01-01 00:00:00')"
                ))
        finally:
            engine.dispose()

        _run_bootstrap(db_path, tmp_path)

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.connect() as conn:
                row = conn.execute(text(
                    "SELECT username FROM users WHERE username='legacyuser'"
                )).fetchone()
        finally:
            engine.dispose()

        assert row is not None, "接管后原有数据丢失"

    def test_second_run_is_idempotent(self, tmp_path):
        """Re-running bootstrap on an already-taken-over database should succeed (idempotent)"""
        db_path = tmp_path / "legacy_twice.db"
        self._make_legacy_db(db_path)

        first = _run_bootstrap(db_path, tmp_path)
        assert first.returncode == 0
        second = _run_bootstrap(db_path, tmp_path)
        assert second.returncode == 0, f"重复引导失败:\n{second.stdout}\n{second.stderr}"


class TestBootstrapNormalDatabase:
    """Scenario 3: a normal database that already has a version record"""

    def test_upgrade_head_is_noop(self, tmp_path):
        db_path = tmp_path / "normal.db"
        assert _run_bootstrap(db_path, tmp_path).returncode == 0
        # Running again should succeed with no changes
        again = _run_bootstrap(db_path, tmp_path)
        assert again.returncode == 0


class TestDriftDetection:
    """Read-only drift detection: executes no DDL, only reports differences"""

    def _fresh_engine(self, tmp_path):
        db_path = tmp_path / "drift.db"
        assert _run_bootstrap(db_path, tmp_path).returncode == 0
        return create_engine(f"sqlite:///{db_path}")

    def test_in_sync_after_migration(self, tmp_path):
        from utils.schema_sync import detect_drift
        engine = self._fresh_engine(tmp_path)
        try:
            import models  # noqa: F401
            from database import Base
            drift = detect_drift(engine, Base)
        finally:
            engine.dispose()

        assert drift["in_sync"] is True, f"迁移后不应有漂移: {drift}"
        assert drift["missing_tables"] == []
        assert drift["missing_columns"] == []
        assert drift["missing_indexes"] == []

    def test_cycle_deadline_index_present_after_migration(self, tmp_path):
        """Regression: the initial migration missed the cycle_deadline index; a startup hook patched it.

        The index is now part of the migration chain, so a from-scratch migration should have it.
        """
        engine = self._fresh_engine(tmp_path)
        try:
            indexes = {i["name"] for i in inspect(engine).get_indexes("applications")}
        finally:
            engine.dispose()

        assert "ix_applications_cycle_deadline" in indexes

    def test_detects_missing_table(self, tmp_path):
        from utils.schema_sync import detect_drift
        engine = self._fresh_engine(tmp_path)
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE notifications"))

            import models  # noqa: F401
            from database import Base
            drift = detect_drift(engine, Base)
        finally:
            engine.dispose()

        assert drift["in_sync"] is False
        assert "notifications" in drift["missing_tables"]

    def test_detects_missing_column(self, tmp_path):
        from utils.schema_sync import detect_drift
        engine = self._fresh_engine(tmp_path)
        try:
            import models  # noqa: F401
            from database import Base
            # Pick a column without indexes: SQLite does not allow dropping indexed columns
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE applications DROP COLUMN institution_name"))
            drift = detect_drift(engine, Base)
        finally:
            engine.dispose()

        assert drift["in_sync"] is False
        assert "applications.institution_name" in drift["missing_columns"]

    def test_detects_extra_table(self, tmp_path):
        from utils.schema_sync import detect_drift
        engine = self._fresh_engine(tmp_path)
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE manual_junk (id INTEGER PRIMARY KEY)"))

            import models  # noqa: F401
            from database import Base
            drift = detect_drift(engine, Base)
        finally:
            engine.dispose()

        assert drift["in_sync"] is False
        assert "manual_junk" in drift["extra_tables"]

    def test_detection_is_read_only(self, tmp_path):
        """Core guarantee: detection must not modify the database structure"""
        from utils.schema_sync import detect_drift
        engine = self._fresh_engine(tmp_path)
        try:
            import models  # noqa: F401
            from database import Base
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE notifications"))

            before = set(inspect(engine).get_table_names())
            detect_drift(engine, Base)
            after = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        assert before == after, "漂移检测修改了库结构（应严格只读）"
        assert "notifications" not in after, "检测不应把缺的表补回来"

    def test_alembic_version_table_ignored(self, tmp_path):
        """alembic_version is Alembic's own table and must not be reported as an extra table"""
        from utils.schema_sync import detect_drift
        engine = self._fresh_engine(tmp_path)
        try:
            import models  # noqa: F401
            from database import Base
            drift = detect_drift(engine, Base)
        finally:
            engine.dispose()

        assert "alembic_version" not in drift["extra_tables"]


class TestRepairMissingStructure:
    """`--repair` explicitly fills in missing columns and indexes.

    Background: legacy databases go through stamp head, which declares the
    existing structure already up to date. If it was built by older code and
    lacks columns/indexes added later, the migration chain will not add them —
    old code relied on a startup hook to fill them in automatically, and once
    that hook was removed nobody covered the gap. --repair is the remediation
    channel after human confirmation.

    Two key constraints:
    1. By default (without --repair) it must stay read-only and never become silent DDL at startup;
    2. --repair only adds, never drops, and touches no existing structure.
    """

    def _make_legacy_db(self, db_path):
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            import models  # noqa: F401
            from database import Base
            Base.metadata.create_all(bind=engine)
        finally:
            engine.dispose()

    def _index_exists(self, db_path, index_name):
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
                    {"n": index_name},
                ).fetchall()
            return bool(rows)
        finally:
            engine.dispose()

    def test_repair_creates_missing_index(self, tmp_path):
        """A missing index should be filled in after --repair"""
        db_path = tmp_path / "repair_index.db"
        self._make_legacy_db(db_path)
        assert _run_bootstrap(db_path, tmp_path).returncode == 0

        # Create the gap: drop the index the migration chain is responsible for
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP INDEX ix_applications_cycle_deadline"))
        finally:
            engine.dispose()
        assert not self._index_exists(db_path, "ix_applications_cycle_deadline")

        result = _run_bootstrap(db_path, tmp_path, repair=True)
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

        assert self._index_exists(db_path, "ix_applications_cycle_deadline"), (
            "--repair 未补齐缺失的索引"
        )

    def test_plain_run_does_not_repair(self, tmp_path):
        """Without --repair it must only report differences and never touch structure (guards against silent-DDL regression)"""
        db_path = tmp_path / "no_repair.db"
        self._make_legacy_db(db_path)
        assert _run_bootstrap(db_path, tmp_path).returncode == 0

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP INDEX ix_applications_cycle_deadline"))
        finally:
            engine.dispose()

        result = _run_bootstrap(db_path, tmp_path)
        assert result.returncode == 0

        combined = result.stdout + result.stderr
        assert "结构差异" in combined, "应把差异打印出来，不能静默"
        assert not self._index_exists(db_path, "ix_applications_cycle_deadline"), (
            "未指定 --repair 却修改了结构 —— 又变回启动时静默 DDL 了"
        )

    def test_repair_when_in_sync_is_noop(self, tmp_path):
        """With structure in sync, --repair should make no changes"""
        db_path = tmp_path / "already_synced.db"
        assert _run_bootstrap(db_path, tmp_path).returncode == 0

        result = _run_bootstrap(db_path, tmp_path, repair=True)
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert "schema 与 ORM 模型一致" in (result.stdout + result.stderr)

    def test_repair_does_not_drop_extra_tables(self, tmp_path):
        """--repair only adds, never drops: extra tables must not be deleted"""
        db_path = tmp_path / "extra_table.db"
        assert _run_bootstrap(db_path, tmp_path).returncode == 0

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE TABLE manual_junk (id INTEGER PRIMARY KEY)"))
        finally:
            engine.dispose()

        assert _run_bootstrap(db_path, tmp_path, repair=True).returncode == 0

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        assert "manual_junk" in tables, "--repair 删除了多余的表（应只增不删）"

    def test_repair_preserves_existing_data(self, tmp_path):
        """--repair must not damage existing data"""
        db_path = tmp_path / "repair_data.db"
        assert _run_bootstrap(db_path, tmp_path).returncode == 0

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO users (username, password_hash, role, real_name, "
                    "is_deleted, must_change_password, token_version, created_at) "
                    "VALUES ('repair_probe', 'x', 'admin', '探针', 0, 0, 0, '2026-01-01 00:00:00')"
                ))
                conn.execute(text("DROP INDEX ix_applications_cycle_deadline"))
        finally:
            engine.dispose()

        assert _run_bootstrap(db_path, tmp_path, repair=True).returncode == 0

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.connect() as conn:
                n = conn.execute(
                    text("SELECT COUNT(*) FROM users WHERE username='repair_probe'")
                ).scalar()
        finally:
            engine.dispose()

        assert n == 1, "--repair 过程中丢失了既有数据"


class TestStartupHookIsReadOnly:
    """The startup hook no longer executes DDL"""

    def test_startup_hook_does_not_create_tables(self, tmp_path, monkeypatch):
        """After dropping a table and starting the app, the startup hook must not recreate it"""
        db_path = tmp_path / "startup.db"
        assert _run_bootstrap(db_path, tmp_path).returncode == 0

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE notifications"))
        finally:
            engine.dispose()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("SCHEDULER_ENABLED", "0")

        # Reload the main module, then run the startup part of lifespan
        import asyncio
        import importlib

        import main as main_module
        importlib.reload(main_module)

        async def _run_startup():
            async with main_module.lifespan(main_module.app):
                pass  # Only run the startup part; exiting also verifies stop_scheduler does not error

        asyncio.run(_run_startup())

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        assert "notifications" not in tables, (
            "启动钩子重建了表 —— schema 权威没有归一到 Alembic"
        )
