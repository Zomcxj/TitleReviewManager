import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
import models
import auth

SQLALCHEMY_DATABASE_URL = "sqlite://"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(name="db")
def fixture_db():
    Base.metadata.create_all(bind=engine)
    # get_current_user 内部直接取 database.SessionLocal（非 Depends 注入），
    # 测试期间把它指向内存库，避免认证回查打到开发库
    import database
    original_session_local = database.SessionLocal
    database.SessionLocal = TestingSessionLocal
    yield TestingSessionLocal()
    database.SessionLocal = original_session_local
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(name="client")
def fixture_client(db):
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(name="test_user")
def fixture_test_user(db):
    user = models.User(
        username="testuser",
        password_hash=auth.hash_password("testpassword"),
        role="admin",
        real_name="Test User"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(name="test_salesman")
def fixture_test_salesman(db):
    user = models.User(
        username="testsalesman",
        password_hash=auth.hash_password("salespassword"),
        role="salesman",
        real_name="Test Salesman"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(name="test_reviewer")
def fixture_test_reviewer(db):
    user = models.User(
        username="testreviewer",
        password_hash=auth.hash_password("reviewpassword"),
        role="reviewer",
        real_name="Test Reviewer"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
