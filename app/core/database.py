from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel

from .config import settings


class DBSession(Session):
    """Custom SQLModel session class with additional methods"""

    def create(self, instance):
        """
        Add, commit and refresh an instance in the session.
        """
        self.add(instance)
        self.commit()
        self.refresh(instance)
        return instance


engine = create_engine(
    str(settings.database_url),
    pool_size=20,
    max_overflow=15,
    pool_pre_ping=True,
    pool_recycle=3600,
)
SessionLocal = sessionmaker(class_=DBSession, autocommit=False, autoflush=False, bind=engine)

SessionCls = SessionLocal  # So that we can override in tests


@contextmanager
def get_session():
    """
    Context manager to prevent connection leaks
    """
    db = SessionCls()
    try:
        yield db
    finally:
        db.close()


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_db():
    """
    FastAPI dependency for getting a database session.
    Used with Depends(get_db) in endpoint parameters.
    """
    db = SessionCls()
    try:
        yield db
    finally:
        db.close()
