from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DB_DIR = os.path.dirname(os.path.abspath(__file__))

# Support both PostgreSQL and SQLite via DATABASE_URL env
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(DB_DIR, 'title_service.db')}",
)

# 相对路径的 SQLite 文件锚定到 backend 目录，避免随启动 cwd 漂移
if DATABASE_URL.startswith("sqlite") and ":memory:" not in DATABASE_URL:
    _path = DATABASE_URL.split(":///", 1)[-1] if ":///" in DATABASE_URL else ""
    if _path and not os.path.isabs(_path):
        DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, _path)}"

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=_connect_args)


# SQLite 默认不强制外键约束，会导致删除父记录后留下悬挂引用。
# 通过 PRAGMA 在每个连接上启用，行为与 PostgreSQL 对齐。
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        except Exception as e:
            logger.warning(f"启用 SQLite 外键约束失败: {e}")


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
