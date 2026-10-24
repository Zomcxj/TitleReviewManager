import logging
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

logger = logging.getLogger(__name__)

DB_DIR = os.path.dirname(os.path.abspath(__file__))

# Support both PostgreSQL and SQLite via DATABASE_URL env
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(DB_DIR, 'title_service.db')}",
)

# Anchor relative-path SQLite files to the backend directory so they do not drift with the startup cwd
if DATABASE_URL.startswith("sqlite") and ":memory:" not in DATABASE_URL:
    _path = DATABASE_URL.split(":///", 1)[-1] if ":///" in DATABASE_URL else ""
    if _path and not os.path.isabs(_path):
        DATABASE_URL = f"sqlite:///{os.path.join(DB_DIR, _path)}"

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=_connect_args)


# SQLite does not enforce foreign key constraints by default, leaving dangling references
# after a parent record is deleted. Enable them via PRAGMA on every connection to align
# behavior with PostgreSQL.
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
