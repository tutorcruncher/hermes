"""
FactoryBoy factories for test data creation.
"""

import factory

from app.core.database import DBSession
from app.main_app.models import Admin, Company, Contact, Deal, Meeting, Pipeline, Stage


class SQLModelFactory(factory.Factory):
    """Base factory class for SQLModel objects with database integration"""

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        """
        Create and save the object to the database.
        This requires a db session to be available in the context.
        """
        db = cls._get_db_session()

        obj = model_class(*args, **kwargs)

        db.add(obj)
        db.commit()
        db.refresh(obj)

        return obj

    @classmethod
    def _get_db_session(cls):
        """Get the database session from the current test context"""
        raise NotImplementedError('Database session not available. Use create_with_db() method.')

    @classmethod
    def create_with_db(cls, db: DBSession, **kwargs):
        """Create an object with the provided database session"""
        original_method = cls._get_db_session

        def get_db_session():
            return db

        cls._get_db_session = get_db_session

        try:
            return cls.create(**kwargs)
        finally:
            cls._get_db_session = original_method


class AdminFactory(SQLModelFactory):
    """Factory for Admin model"""

    class Meta:
        model = Admin

    first_name = 'Test'
    last_name = 'Admin'
    username = factory.Sequence(lambda n: f'admin{n}@example.com')
    tc2_admin_id = factory.Sequence(lambda n: n)
    pd_owner_id = factory.Sequence(lambda n: n)
    is_sales_person = True


class PipelineFactory(SQLModelFactory):
    """Factory for Pipeline model"""

    class Meta:
        model = Pipeline

    pd_pipeline_id = factory.Sequence(lambda n: n)
    name = factory.Sequence(lambda n: f'Pipeline {n}')


class StageFactory(SQLModelFactory):
    """Factory for Stage model"""

    class Meta:
        model = Stage

    pd_stage_id = factory.Sequence(lambda n: n)
    name = factory.Sequence(lambda n: f'Stage {n}')


class CompanyFactory(SQLModelFactory):
    """Factory for Company model"""

    class Meta:
        model = Company

    name = factory.Sequence(lambda n: f'Company {n}')
    price_plan = 'payg'
    country = 'GB'


class ContactFactory(SQLModelFactory):
    """Factory for Contact model"""

    class Meta:
        model = Contact

    first_name = 'Test'
    last_name = factory.Sequence(lambda n: f'Contact{n}')
    email = factory.Sequence(lambda n: f'contact{n}@example.com')


class DealFactory(SQLModelFactory):
    """Factory for Deal model"""

    class Meta:
        model = Deal

    name = factory.Sequence(lambda n: f'Deal {n}')
    status = Deal.STATUS_OPEN


class MeetingFactory(SQLModelFactory):
    """Factory for Meeting model"""

    class Meta:
        model = Meeting

    meeting_type = Meeting.TYPE_SALES
    status = Meeting.STATUS_PLANNED
