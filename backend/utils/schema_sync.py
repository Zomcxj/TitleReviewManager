"""
Schema drift detection (read-only)

Background: this used to be a schema_sync that "auto-created tables / columns /
indexes at startup". It had two problems:

1. A second schema source of truth. Both Alembic and the startup hook could alter
   the database structure; once they disagreed, there was no way to tell "who added
   this column" while debugging.
2. It masked flaws in the migration chain. Testing revealed the initial migration
   was missing the applications.cycle_deadline index, but because the startup hook
   silently added it, nobody noticed for a long time.

Now the schema source of truth is unified on Alembic: structure changes only via
migrations. This module performs a read-only comparison only, logging mismatches
between the database structure and the ORM models as warning logs. It executes no
DDL at all; real structure changes are done by `alembic upgrade head`.

Why not delete it outright:
- Drift information has diagnostic value for ops (e.g. someone hand-edited the DB,
  or a migration was forgotten).
- Detection results are also exposed at /api/health/detail for post-deploy debugging.
"""
import logging

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Tables created by Alembic itself, not part of the business models; ignored in comparisons
_IGNORED_TABLES = {"alembic_version"}


def detect_drift(engine: Engine, base) -> dict:
    """Read-only comparison of ORM models against the actual database structure; returns a diff summary.

    Returns:
      {
        "missing_tables": [...],   tables present in models but not in the DB
        "extra_tables": [...],     tables present in the DB but not in models (possibly hand-created)
        "missing_columns": [...],  as "table.column"
        "extra_columns": [...],    in the DB but not in models (possibly hand-added)
        "missing_indexes": [...],  as "table.index"
        "in_sync": bool,
      }

    This function performs no writes; read-only.
    """
    summary = {
        "missing_tables": [],
        "extra_tables": [],
        "missing_columns": [],
        "extra_columns": [],
        "missing_indexes": [],
        "in_sync": True,
    }

    try:
        inspector = inspect(engine)
        db_tables = set(inspector.get_table_names()) - _IGNORED_TABLES
        model_tables = set(base.metadata.tables.keys())
    except Exception as e:
        # Detection failures must not affect startup; log and return an "unknown" state
        logger.warning(f"schema 漂移检测无法执行: {e}")
        summary["in_sync"] = None
        return summary

    summary["missing_tables"] = sorted(model_tables - db_tables)
    summary["extra_tables"] = sorted(db_tables - model_tables)

    for table_name in sorted(model_tables & db_tables):
        table = base.metadata.tables[table_name]
        try:
            db_columns = {c["name"] for c in inspector.get_columns(table_name)}
        except Exception as e:
            logger.debug(f"读取 {table_name} 列信息失败: {e}")
            continue

        model_columns = {c.name for c in table.columns}
        summary["missing_columns"].extend(
            f"{table_name}.{c}" for c in sorted(model_columns - db_columns)
        )
        summary["extra_columns"].extend(
            f"{table_name}.{c}" for c in sorted(db_columns - model_columns)
        )

        try:
            db_indexes = {i["name"] for i in inspector.get_indexes(table_name)}
        except Exception as e:
            logger.debug(f"读取 {table_name} 索引信息失败: {e}")
            continue

        model_indexes = {i.name for i in table.indexes if i.name}
        summary["missing_indexes"].extend(
            f"{table_name}.{i}" for i in sorted(model_indexes - db_indexes)
        )

    summary["in_sync"] = not any(
        summary[k] for k in
        ("missing_tables", "extra_tables", "missing_columns", "extra_columns", "missing_indexes")
    )
    return summary


def log_drift(engine: Engine, base) -> dict:
    """Run drift detection and log by severity. Returns the summary, reused by the health check."""
    drift = detect_drift(engine, base)
    if drift["in_sync"] is None:
        return drift

    if drift["in_sync"]:
        logger.info("schema 与 ORM 模型一致，无漂移")
        return drift

    # Missing tables / columns / indexes = migrations not fully applied; alembic upgrade head must be run manually
    if drift["missing_tables"] or drift["missing_columns"] or drift["missing_indexes"]:
        logger.warning(
            "检测到 schema 漂移（库落后于模型）："
            f"缺表 {drift['missing_tables']}，"
            f"缺列 {drift['missing_columns']}，"
            f"缺索引 {drift['missing_indexes']}。"
            "请执行 `alembic upgrade head` 补齐 —— 启动钩子不再自动修改表结构。"
        )

    # Extra tables/columns are usually hand edits or historical leftovers; harmless but worth recording
    if drift["extra_tables"] or drift["extra_columns"]:
        logger.warning(
            "检测到库中存在模型未定义的结构（可能为手工改动）："
            f"多余表 {drift['extra_tables']}，多余列 {drift['extra_columns']}"
        )

    return drift
