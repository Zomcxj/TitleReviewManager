"""Database bootstrap: let Alembic safely take over an existing database.

Problem
-------
The container start command is `alembic upgrade head && uvicorn ...`. But the project
historically had a second path for creating the database: local start.bat / start.sh do
not run migrations; instead the app startup hook called create_all to build tables. A
database built that way **has business tables but no alembic_version record**.

Once such a database is moved to Docker deployment, `alembic upgrade head` replays from
the initial migration, hits already-existing tables while creating them, and fails with
`table already exists` — **the container never comes up**.

Reproduced in practice (before the fix):
    sqlite3.OperationalError: table system_configs already exists
    → alembic exits with code 1 → the && in CMD short-circuits → uvicorn never starts

Strategy
--------
Three cases based on the database's actual state, doing only what is necessary:

1. alembic_version record present — a normal database, run upgrade head directly.
2. No alembic_version but business tables exist — a create_all-built database. First
   stamp head (accept the existing structure as already at head), then upgrade head
   (usually a no-op).
3. Empty database — run upgrade head directly; the migration chain creates all tables.

The stamp in case 2 is safe because: this project's startup hook had always been doing
"auto table/column/index completion", so such databases were kept close to the model
definitions; and the migration chain was verified to match the ORM models exactly
(100% column match). Right after stamping, a drift check runs — if differences remain,
a prominent warning is printed, never silently ignored.
"""
import logging
import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text

logger = logging.getLogger(__name__)

# Tables ignored when detecting "business tables already present"
_NON_BUSINESS_TABLES = {"alembic_version"}


def _get_url() -> str:
    from database import DATABASE_URL
    return str(DATABASE_URL)


def _inspect_state(engine) -> tuple[bool, bool]:
    """Return (whether the alembic_version table exists, whether business tables exist)"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    has_version = "alembic_version" in tables
    has_business = bool(tables - _NON_BUSINESS_TABLES)
    return has_version, has_business


def _run_alembic(*args: str) -> int:
    """Run an alembic subcommand in the current working directory, returning its exit code"""
    cmd = [sys.executable, "-m", "alembic", *args]
    logger.info(f"执行: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
    return proc.returncode


def _read_version(engine) -> str | None:
    """Read the current alembic version number"""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            return row[0] if row else None
    except Exception:
        return None


def repair(engine) -> dict:
    """Add missing columns and indexes found by drift detection (add-only, must be invoked explicitly).

    Why it exists: case 2 (a legacy create_all-built database) goes through stamp head, which
    accepts the existing structure as already up to date. If that database was built by older
    code and lacks columns/indexes added later, migrations will not add them — old code relied
    on the startup hook to auto-complete, and once the hook was removed nobody filled that gap.

    This only "adds columns / adds indexes"; it deletes or alters no existing structure, and only
    runs when --repair is passed explicitly, preserving the principle that "schema changes come
    only from migrations": this is remediation after manual confirmation, not silent DDL at startup.
    """
    import models  # noqa: F401  ensure models are registered in Base.metadata
    from database import Base
    from utils.schema_sync import detect_drift

    drift = detect_drift(engine, Base)
    if drift.get("in_sync") is not False:
        return {"repaired": [], "failed": [], "drift": drift}

    repaired: list[str] = []
    failed: list[str] = []

    with engine.begin() as conn:
        # Add columns: SQLite supports ADD COLUMN; NOT NULL columns without a default cannot be added safely — skip and record
        for item in drift.get("missing_columns", []):
            table_name, column_name = item.split(".", 1)
            table = Base.metadata.tables.get(table_name)
            if table is None or column_name not in table.columns:
                failed.append(f"{item}（模型定义中未找到）")
                continue
            column = table.columns[column_name]
            ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column.type.compile(engine.dialect)}'
            if not column.nullable:
                if column.default is None and column.server_default is None:
                    failed.append(f"{item}（NOT NULL 且无默认值，需人工处理）")
                    continue
                ddl += " NOT NULL"
            try:
                conn.execute(text(ddl))
                repaired.append(item)
            except Exception as e:
                failed.append(f"{item}（{e}）")

        # Add indexes: rebuild from the corresponding Index objects in the model definitions
        for item in drift.get("missing_indexes", []):
            table_name, index_name = item.split(".", 1)
            table = Base.metadata.tables.get(table_name)
            target = None
            if table is not None:
                for idx in table.indexes:
                    if idx.name == index_name:
                        target = idx
                        break
            if target is None:
                failed.append(f"{item}（模型定义中未找到）")
                continue
            try:
                target.create(conn)
                repaired.append(item)
            except Exception as e:
                failed.append(f"{item}（{e}）")

    # Re-check once more after the additions to give a definitive verdict
    after = detect_drift(engine, Base)
    return {"repaired": repaired, "failed": failed, "drift_after": after}


def main(repair_drift: bool = False) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    url = _get_url()
    # Do not echo the connection string's password into logs
    safe_url = url
    if "@" in url and "://" in url:
        head, tail = url.split("://", 1)
        if "@" in tail:
            safe_url = f"{head}://***@{tail.split('@', 1)[1]}"
    logger.info(f"数据库启动引导开始（{safe_url}）")

    engine = create_engine(url)
    try:
        has_version, has_business = _inspect_state(engine)

        if has_version:
            current = _read_version(engine)
            logger.info(f"检测到 alembic 版本记录（当前 {current}），直接执行迁移")
            code = _run_alembic("upgrade", "head")
            if code != 0:
                logger.error("迁移执行失败，启动中止")
                return code
        elif has_business:
            # create_all-built database: claim the existing structure first, then run catch-up migrations
            logger.warning(
                "检测到已有业务表但缺少 alembic 版本记录 —— "
                "这是 create_all 建出的库（本地 start 脚本路径）。"
                "将先把现有结构标记为最新版本（stamp head），再执行迁移补齐差异。"
            )
            code = _run_alembic("stamp", "head")
            if code != 0:
                logger.error("stamp head 失败，启动中止")
                return code
            code = _run_alembic("upgrade", "head")
            if code != 0:
                logger.error("迁移执行失败，启动中止")
                return code
            logger.info("已接管该库，后续结构变更统一由 Alembic 管理")
        else:
            logger.info("空库，执行迁移链建出全部表")
            code = _run_alembic("upgrade", "head")
            if code != 0:
                logger.error("迁移执行失败，启动中止")
                return code
    finally:
        engine.dispose()

    # After migrations, run a read-only drift check and report the result explicitly
    engine = create_engine(url)
    try:
        import models  # noqa: F401  ensure models are registered in Base.metadata
        from database import Base
        from utils.schema_sync import detect_drift

        drift = detect_drift(engine, Base)
        if drift["in_sync"]:
            logger.info("迁移完成，schema 与 ORM 模型一致")
        elif drift["in_sync"] is None:
            logger.warning("迁移完成，但漂移检测未能执行")
        else:
            logger.warning(
                "迁移完成，但仍检测到结构差异："
                f"缺表 {drift['missing_tables']}，缺列 {drift['missing_columns']}，"
                f"缺索引 {drift['missing_indexes']}，多余表 {drift['extra_tables']}，"
                f"多余列 {drift['extra_columns']}。"
            )
            if repair_drift:
                logger.warning("已指定 --repair，尝试补齐缺失的列与索引（只增不删）")
                result = repair(engine)
                for item in result.get("repaired", []):
                    logger.info(f"  已补齐: {item}")
                for item in result.get("failed", []):
                    logger.error(f"  补齐失败: {item}")
                after = result.get("drift_after") or {}
                if after.get("in_sync"):
                    logger.info("补齐完成，schema 与 ORM 模型一致")
                else:
                    logger.error(
                        "补齐后仍有差异，请人工核对："
                        f"缺列 {after.get('missing_columns')}，缺索引 {after.get('missing_indexes')}"
                    )
            else:
                logger.warning(
                    "说明该库存在迁移链未覆盖的历史改动。"
                    "确认无误后可执行 `python db_bootstrap.py --repair` 补齐缺失的列与索引。"
                )
    finally:
        engine.dispose()

    return 0


if __name__ == "__main__":
    _repair = "--repair" in sys.argv
    sys.exit(main(repair_drift=_repair))
