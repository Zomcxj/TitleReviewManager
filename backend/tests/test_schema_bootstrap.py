"""数据库启动引导与 schema 漂移检测测试。

覆盖三类库状态下的启动路径，以及只读漂移检测的判定逻辑。

这些测试直接针对一个已确认的上线阻断缺陷：
create_all 建出的库（本地 start 脚本路径）缺少 alembic_version 记录，
直接执行 `alembic upgrade head` 会因 "table already exists" 失败，
导致容器启动命令 `alembic upgrade head && uvicorn ...` 短路、服务起不来。
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
    """把 DATABASE_URL 指向临时库，避免碰到开发库 title_service.db"""
    db_file = tmp_path / "boot_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("JWT_SECRET_KEY", "boot-test")
    monkeypatch.setenv("SCHEDULER_ENABLED", "0")
    yield


def _run_bootstrap(db_path, tmp_path, repair=False):
    """在子进程中执行 db_bootstrap.py（模拟容器启动命令的前半段）"""
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
    """场景一：全新空库 —— 迁移链负责建出全部表"""

    def test_creates_all_tables_from_scratch(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        result = _run_bootstrap(db_path, tmp_path)
        assert result.returncode == 0, f"引导失败:\n{result.stdout}\n{result.stderr}"

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        # 迁移链建出业务表，并记录版本
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
    """场景二：create_all 建出的库（有业务表、无版本记录）

    这是修复前会导致容器启动失败的关键场景。
    """

    def _make_legacy_db(self, db_path):
        """用 create_all 建表，模拟本地 start 脚本初始化出的库"""
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

        # 前置条件：库里有业务表但没有版本记录（这正是缺陷触发条件）
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            tables = set(inspect(engine).get_table_names())
            assert "users" in tables
            assert "alembic_version" not in tables, "前置条件不成立：不该有版本记录"
        finally:
            engine.dispose()

        # 修复前这里会因 table already exists 失败
        result = _run_bootstrap(db_path, tmp_path)
        assert result.returncode == 0, (
            f"create_all 建出的库应能被接管，实际失败:\n{result.stdout}\n{result.stderr}"
        )
        # logging.StreamHandler 默认写 stderr，两处都查以免日志配置变化导致误判
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
        """接管过程绝不能丢数据"""
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
        """已接管的库再跑一次引导应正常（幂等）"""
        db_path = tmp_path / "legacy_twice.db"
        self._make_legacy_db(db_path)

        first = _run_bootstrap(db_path, tmp_path)
        assert first.returncode == 0
        second = _run_bootstrap(db_path, tmp_path)
        assert second.returncode == 0, f"重复引导失败:\n{second.stdout}\n{second.stderr}"


class TestBootstrapNormalDatabase:
    """场景三：已有版本记录的正常库"""

    def test_upgrade_head_is_noop(self, tmp_path):
        db_path = tmp_path / "normal.db"
        assert _run_bootstrap(db_path, tmp_path).returncode == 0
        # 再跑一次应无差异地成功
        again = _run_bootstrap(db_path, tmp_path)
        assert again.returncode == 0


class TestDriftDetection:
    """只读漂移检测：不执行任何 DDL，只报告差异"""

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
        """回归：初始迁移曾漏建 cycle_deadline 索引，靠启动钩子补上。

        该索引现已补进迁移链，从零迁移就应存在。
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
            # 选无索引的列：SQLite 不允许删除带索引的列
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
        """核心保证：检测不得修改库结构"""
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
        """alembic_version 是 Alembic 自建表，不应被报成多余表"""
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
    """`--repair` 显式补齐缺失的列与索引。

    背景：历史库走 stamp head，等于把现有结构认作已是最新。若它是老版本代码
    建的、又缺了后来新增的列/索引，迁移链不会补 —— 旧代码靠启动钩子自动补，
    钩子移除后这个缺口就没人管了。--repair 是人工确认后的补救通道。

    两条关键约束：
    1. 默认（不带 --repair）必须保持只读，不能变成启动时的静默 DDL；
    2. --repair 只增不删，不碰任何既有结构。
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
        """缺失索引在 --repair 后应被补齐"""
        db_path = tmp_path / "repair_index.db"
        self._make_legacy_db(db_path)
        assert _run_bootstrap(db_path, tmp_path).returncode == 0

        # 制造缺口：删掉迁移链负责建的索引
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
        """不带 --repair 时必须只报差异、不动结构（防止静默 DDL 回归）"""
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
        """结构一致时 --repair 不应产生任何改动"""
        db_path = tmp_path / "already_synced.db"
        assert _run_bootstrap(db_path, tmp_path).returncode == 0

        result = _run_bootstrap(db_path, tmp_path, repair=True)
        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
        assert "schema 与 ORM 模型一致" in (result.stdout + result.stderr)

    def test_repair_does_not_drop_extra_tables(self, tmp_path):
        """--repair 只增不删：多余的表不应被删除"""
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
        """--repair 不得破坏既有数据"""
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
    """启动钩子不再执行 DDL"""

    def test_startup_hook_does_not_create_tables(self, tmp_path, monkeypatch):
        """删除一张表后启动应用，启动钩子不应把表建回来"""
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

        # 重新加载 main 模块，然后执行 lifespan 的启动段
        import asyncio
        import importlib

        import main as main_module
        importlib.reload(main_module)

        async def _run_startup():
            async with main_module.lifespan(main_module.app):
                pass  # 只执行启动段；退出时同时验证 stop_scheduler 不报错

        asyncio.run(_run_startup())

        engine = create_engine(f"sqlite:///{db_path}")
        try:
            tables = set(inspect(engine).get_table_names())
        finally:
            engine.dispose()

        assert "notifications" not in tables, (
            "启动钩子重建了表 —— schema 权威没有归一到 Alembic"
        )
