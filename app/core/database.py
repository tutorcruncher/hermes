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


engine = create_engine(str(settings.database_url))
SessionLocal = sessionmaker(class_=DBSession, autocommit=False, autoflush=False, bind=engine)

SessionCls = SessionLocal  # So that we can override in tests


def get_session() -> DBSession:
    return SessionCls()


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()
