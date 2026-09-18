"""
轻量 schema 同步（SQLite 友好）

Alembic 负责正式迁移，但为了让已有开发/部署库升级代码后直接可用，
启动时对比 ORM 模型与实际表结构，自动补齐缺失的表和列。
只做「加表 / 加列」，绝不删除或修改已有列，避免破坏数据。
"""
import logging
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _column_ddl(column) -> str:
    """根据 ORM 列生成 SQLite 的 ADD COLUMN 片段"""
    try:
        col_type = column.type.compile(dialect=_sqlite_dialect())
    except Exception:
        col_type = "TEXT"

    parts = [f'"{column.name}"', col_type]
    if not column.nullable:
        # SQLite 的 ADD COLUMN 不允许无默认值的 NOT NULL，给一个类型安全的默认值
        default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
        if isinstance(default, bool):
            parts.append(f"DEFAULT {1 if default else 0}")
        elif isinstance(default, (int, float)):
            parts.append(f"DEFAULT {default}")
        elif isinstance(default, str):
            parts.append(f"DEFAULT '{default}'")
        else:
            # 布尔列在模型里多为 default=False
            if "BOOL" in col_type.upper():
                parts.append("DEFAULT 0")
            elif any(t in col_type.upper() for t in ("INT", "NUMERIC", "FLOAT", "REAL")):
                parts.append("DEFAULT 0")
            else:
                parts.append("DEFAULT ''")
    return " ".join(parts)


def _sqlite_dialect():
    from sqlalchemy.dialects import sqlite
    return sqlite.dialect()


def sync_schema(engine: Engine, base) -> dict:
    """补齐缺失的表、列与索引，返回操作摘要"""
    summary = {"created_tables": [], "added_columns": [], "created_indexes": []}
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table in base.metadata.sorted_tables:
            if table.name not in existing_tables:
                table.create(bind=conn, checkfirst=True)
                summary["created_tables"].append(table.name)
                logger.info(f"已创建缺失表: {table.name}")
                continue

            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_cols:
                    continue
                ddl = _column_ddl(column)
                try:
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'))
                    summary["added_columns"].append(f"{table.name}.{column.name}")
                    logger.info(f"已补充缺失列: {table.name}.{column.name}")
                except Exception as e:
                    logger.warning(f"补充列失败 {table.name}.{column.name}: {e}")

        # 补齐缺失索引（性能关键：高频过滤字段无索引会导致全表扫描）
        for table in base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            try:
                existing_idx = {i["name"] for i in inspector.get_indexes(table.name)}
            except Exception:
                continue
            for index in table.indexes:
                if index.name in existing_idx:
                    continue
                try:
                    index.create(bind=conn, checkfirst=True)
                    summary["created_indexes"].append(f"{table.name}.{index.name}")
                    logger.info(f"已创建缺失索引: {table.name}.{index.name}")
                except Exception as e:
                    logger.warning(f"创建索引失败 {table.name}.{index.name}: {e}")

    return summary
