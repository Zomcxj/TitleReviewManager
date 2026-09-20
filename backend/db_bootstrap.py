"""数据库启动引导：让 Alembic 安全接管已存在的库。

解决的问题
----------
容器启动命令是 `alembic upgrade head && uvicorn ...`。但项目历史上还有一条
建库路径：本地 start.bat / start.sh 不跑迁移，而是由应用启动钩子调用
create_all 建表。这样建出的库**有业务表但没有 alembic_version 记录**。

一旦这种库搬到 Docker 部署，`alembic upgrade head` 会从初始迁移开始重放，
在建表时撞上已存在的表并以 `table already exists` 失败，**容器直接起不来**。

实测复现（修复前）：
    sqlite3.OperationalError: table system_configs already exists
    → alembic 退出码 1 → CMD 中的 && 短路 → uvicorn 不启动

处理策略
--------
按库的实际状态分三种情况，只做必要动作：

1. 库里有 alembic_version 记录 —— 正常库，直接 upgrade head。
2. 无 alembic_version 但已有业务表 —— create_all 建出的库。先 stamp head
   （把现有结构认作已达 head），再 upgrade head（通常无操作）。
3. 空库 —— 直接 upgrade head，由迁移链建出全部表。

情况 2 的 stamp 之所以安全：本项目的启动钩子此前一直在做「自动补表/补列/
补索引」，因此这类库的结构始终被维持在接近模型定义的状态；且迁移链经核对
与 ORM 模型完全一致（列 100% 匹配）。stamp 之后会立即做一次漂移检测，
若仍存在差异会打印醒目告警，不会静默放过。
"""
import logging
import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect, text

logger = logging.getLogger(__name__)

# 判断「已有业务表」时忽略的表
_NON_BUSINESS_TABLES = {"alembic_version"}


def _get_url() -> str:
    from database import DATABASE_URL
    return str(DATABASE_URL)


def _inspect_state(engine) -> tuple[bool, bool]:
    """返回 (是否有 alembic_version 表, 是否有业务表)"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    has_version = "alembic_version" in tables
    has_business = bool(tables - _NON_BUSINESS_TABLES)
    return has_version, has_business


def _run_alembic(*args: str) -> int:
    """在当前工作目录执行 alembic 子命令，返回退出码"""
    cmd = [sys.executable, "-m", "alembic", *args]
    logger.info(f"执行: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
    return proc.returncode


def _read_version(engine) -> str | None:
    """读取当前 alembic 版本号"""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
            return row[0] if row else None
    except Exception:
        return None


def repair(engine) -> dict:
    """补齐漂移检测发现的缺失列与索引（只增不删，需显式调用）。

    为什么需要它：情况 2（create_all 建出的历史库）走 stamp head，等于把现有结构
    认作已是最新。若该库是老版本代码建的、又缺了后来加的列/索引，迁移不会补
    —— 旧代码靠启动钩子自动补，钩子移除后这个缺口就没人管了。

    这里只做「加列 / 加索引」，不删不改任何既有结构，且必须显式传 --repair 才执行，
    保持「schema 变更只能来自迁移」的原则：这是人工确认后的补救，不是启动时的静默 DDL。
    """
    import models  # noqa: F401  确保模型已注册到 Base.metadata
    from database import Base
    from utils.schema_sync import detect_drift

    drift = detect_drift(engine, Base)
    if drift.get("in_sync") is not False:
        return {"repaired": [], "failed": [], "drift": drift}

    repaired: list[str] = []
    failed: list[str] = []

    with engine.begin() as conn:
        # 补列：SQLite 支持 ADD COLUMN；带 NOT NULL 且无默认值的列无法安全添加，跳过并记录
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

        # 补索引：从模型定义里取对应的 Index 对象重建
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

    # 补完再检一次，给出确定结论
    after = detect_drift(engine, Base)
    return {"repaired": repaired, "failed": failed, "drift_after": after}


def main(repair_drift: bool = False) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    url = _get_url()
    # 日志里不回显连接串中的密码
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
            # create_all 建出的库：先认领现有结构，再补跑迁移
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

    # 迁移完成后做一次只读漂移检测，把结果明确打出来
    engine = create_engine(url)
    try:
        import models  # noqa: F401  确保模型已注册到 Base.metadata
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
