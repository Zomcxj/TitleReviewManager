from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

load_dotenv()

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
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
