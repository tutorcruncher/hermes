import os
import tempfile
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, create_engine

from app.core import database
from app.core.database import DBSession
from app.main import app

# Import all models to ensure they're registered with SQLModel before creating tables

# Create test engine - using SQLite for now until PostgreSQL test DB is set up
# Use file-based SQLite to avoid in-memory connection issues
test_db_file = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
engine = create_engine(
    f'sqlite:///{test_db_file.name}',
    connect_args={'check_same_thread': False},
)
TestingSessionLocal = sessionmaker(class_=DBSession, autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def use_test_session_factory(monkeypatch):
    """Use test session factory for all tests"""
    monkeypatch.setattr(database, 'SessionCls', TestingSessionLocal)


@pytest.fixture(name='session')
def session_fixture() -> Generator[DBSession, None, None]:
    """Create a new database session for a test"""
    # Create all tables before starting the test
    SQLModel.metadata.create_all(bind=engine)

    with TestingSessionLocal() as session:
        yield session

    # Drop all tables after the test
    SQLModel.metadata.drop_all(bind=engine)


# Clean up temp file on exit
import atexit

atexit.register(lambda: os.unlink(test_db_file.name))


@pytest.fixture(name='client')
def client_fixture(session: DBSession):
    """Create a test client"""

    def get_session_override():
        return session

    # Override the get_db dependency
    from app.core.database import get_db

    app.dependency_overrides[get_db] = get_session_override
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(name='db')
def db_fixture(session: DBSession):
    """Alias for session fixture following tc-ai-backend pattern"""
    return session


# Factory fixtures using FactoryBoy
from tests.factories import AdminFactory, CompanyFactory, ContactFactory, PipelineFactory, StageFactory


@pytest.fixture
def test_admin(db: DBSession):
    """Create a test admin using factory"""
    return AdminFactory.create_with_db(db, username='test@example.com', tc2_admin_id=1, pd_owner_id=1)


@pytest.fixture
def test_stage(db: DBSession):
    """Create a test stage using factory"""
    return StageFactory.create_with_db(db, pd_stage_id=1)


@pytest.fixture
def test_pipeline(db: DBSession, test_stage):
    """Create a test pipeline using factory"""
    return PipelineFactory.create_with_db(db, pd_pipeline_id=1, dft_entry_stage_id=test_stage.id)


@pytest.fixture
def test_company(db: DBSession, test_admin):
    """Create a test company using factory"""
    return CompanyFactory.create_with_db(db, sales_person_id=test_admin.id)


@pytest.fixture
def test_contact(db: DBSession, test_company):
    """Create a test contact using factory"""
    return ContactFactory.create_with_db(db, company_id=test_company.id)


@pytest.fixture
def test_config(db: DBSession, test_pipeline):
    """Create a test config with pipeline settings"""
    from app.main_app.models import Config

    return db.create(
        Config(
            payg_pipeline_id=test_pipeline.id,
            startup_pipeline_id=test_pipeline.id,
            enterprise_pipeline_id=test_pipeline.id,
        )
    )
