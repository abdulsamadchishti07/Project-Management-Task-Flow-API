import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app import model, utils, oauth2

# In-memory SQLite database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Register now() function in SQLite for PostgreSQL server_default compatibility
@event.listens_for(engine, "connect")
def register_sqlite_functions(dbapi_connection, connection_record):
    dbapi_connection.create_function("now", 0, lambda: datetime.now(timezone.utc).isoformat())


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session):
    user = model.Users(
        email="owner@test.com",
        name="Workspace Owner",
        password=utils.hash("password123"),
        active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_viewer_user(db_session):
    user = model.Users(
        email="viewer@test.com",
        name="Viewer User",
        password=utils.hash("password123"),
        active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def test_member_user(db_session):
    user = model.Users(
        email="member@test.com",
        name="Member User",
        password=utils.hash("password123"),
        active=True
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user):
    token = oauth2.create_access_token(data={"sub": str(test_user.id), "ver": test_user.token_version or 1})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def viewer_headers(test_viewer_user):
    token = oauth2.create_access_token(data={"sub": str(test_viewer_user.id), "ver": test_viewer_user.token_version or 1})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def member_headers(test_member_user):
    token = oauth2.create_access_token(data={"sub": str(test_member_user.id), "ver": test_member_user.token_version or 1})
    return {"Authorization": f"Bearer {token}"}
