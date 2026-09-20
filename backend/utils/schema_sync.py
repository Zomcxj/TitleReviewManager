"""
Schema 漂移检测（只读）

背景：此前这里是「启动时自动补表 / 补列 / 补索引」的 schema_sync。它有两个
问题：

1. 存在第二套 schema 权威。Alembic 与启动钩子都能改库结构，一旦两者不一致，
   排查时无法确定「这个列是谁加的」。
2. 它会掩盖迁移链的缺陷。实测发现初始迁移漏建了 applications.cycle_deadline
   索引，却因为启动时被自动补上而长期无人察觉。

现在 schema 权威统一到 Alembic 一条路径：改结构只能通过迁移。
本模块只做只读比对，把「库结构与 ORM 模型不一致」的情况记成告警日志，
不再执行任何 DDL。真正的结构变更由 `alembic upgrade head` 完成。

为什么不直接删除：
- 漂移信息对运维有诊断价值（例如有人手工改过库、或忘记跑迁移）。
- 检测结果同时暴露在 /api/health/detail，便于上线后排查。
"""
import logging

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# Alembic 自建的表，不属于业务模型，比对时忽略
_IGNORED_TABLES = {"alembic_version"}


def detect_drift(engine: Engine, base) -> dict:
    """只读比对 ORM 模型与实际库结构，返回差异摘要。

    返回值：
      {
        "missing_tables": [...],   模型有、库中没有的表
        "extra_tables": [...],     库中有、模型中没有的表（可能有人手工建表）
        "missing_columns": [...],  "table.column" 形式
        "extra_columns": [...],    库有、模型无（可能有人手工加列）
        "missing_indexes": [...],  "table.index" 形式
        "in_sync": bool,
      }

    本函数不执行任何写操作，只读。
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
        # 检测本身失败不应影响启动，记日志后返回「未知」状态
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
    """执行漂移检测并按严重程度记日志。返回检测摘要，供健康检查复用。"""
    drift = detect_drift(engine, base)
    if drift["in_sync"] is None:
        return drift

    if drift["in_sync"]:
        logger.info("schema 与 ORM 模型一致，无漂移")
        return drift

    # 缺表 / 缺列 / 缺索引 = 迁移没跑到位，需要人工执行 alembic upgrade head
    if drift["missing_tables"] or drift["missing_columns"] or drift["missing_indexes"]:
        logger.warning(
            "检测到 schema 漂移（库落后于模型）："
            f"缺表 {drift['missing_tables']}，"
            f"缺列 {drift['missing_columns']}，"
            f"缺索引 {drift['missing_indexes']}。"
            "请执行 `alembic upgrade head` 补齐 —— 启动钩子不再自动修改表结构。"
        )

    # 多出来的表/列通常是手工改动或历史残留，不会导致报错，但值得记录
    if drift["extra_tables"] or drift["extra_columns"]:
        logger.warning(
            "检测到库中存在模型未定义的结构（可能为手工改动）："
            f"多余表 {drift['extra_tables']}，多余列 {drift['extra_columns']}"
        )

    return drift
