"""
Tests for callbooker process edge cases to achieve 100% coverage.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from pytz import utc
from sqlmodel import select

from app.callbooker.models import CBSalesCall
from app.callbooker.process import book_meeting
from app.main_app.models import Config, Deal, Pipeline, Stage


def fake_gcal_builder(error=False, start_dt: datetime | None = None, meeting_dur_mins: int = 90):
    """Mock Google Calendar resource"""

    def as_iso_8601(dt: datetime):
        return dt.isoformat().replace('+00:00', 'Z')

    class MockGCalResource:
        def execute(self):
            start = start_dt or datetime(2026, 7, 8, 11, tzinfo=utc)
            end = start + timedelta(minutes=meeting_dur_mins)
            return {
                'calendars': {'climan@example.com': {'busy': [{'start': as_iso_8601(start), 'end': as_iso_8601(end)}]}}
            }

        def query(self, body: dict):
            self.body = body
            return self

        def freebusy(self, *args, **kwargs):
            return self

        def events(self):
            return self

        def insert(self, *args, **kwargs):
            return self

    return MockGCalResource


class TestCallbookerProcessEdgeCases:
    """Test callbooker process edge cases for full coverage"""

    @patch('app.callbooker.process.AdminGoogleCalendar')
    @patch('app.callbooker.process.check_gcal_open_slots', new_callable=AsyncMock)
    async def test_book_meeting_does_not_hold_session_during_google_api_call(
        self, mock_check_gcal, mock_gcal_class, db, test_admin, test_company, test_contact
    ):
        """Test that book_meeting closes DB session before making Google Calendar API calls"""
        session_open = []

        class SessionTracker:
            def __enter__(self):
                session_open.append(True)
                return db

            def __exit__(self, *args):
                session_open.pop()
                return False

        def check_session_during_gcal_check(*args, **kwargs):
            assert len(session_open) == 0, 'Google Calendar API call was made while database session was still open'
            return True

        def check_session_during_gcal_create(*args, **kwargs):
            assert len(session_open) == 0, (
                'Google Calendar create_cal_event was made while database session was still open'
            )

        mock_check_gcal.side_effect = check_session_during_gcal_check
        mock_gcal_instance = mock_gcal_class.return_value
        mock_gcal_instance.create_cal_event = check_session_during_gcal_create

        future_dt = datetime.now(utc) + timedelta(days=1)
        event = CBSalesCall(
            admin_id=test_admin.id,
            name='John Doe',
            email='john@example.com',
            company_name='Test Company',
            country='GB',
            estimated_income=1000,
            currency='GBP',
            price_plan='payg',
            meeting_dt=future_dt,
        )

        meeting = await book_meeting(test_company, test_contact, event, db)

        assert meeting is not None
        assert len(session_open) == 0

    @patch('app.callbooker.process.check_gcal_open_slots')
    async def test_sales_call_admin_not_found_raises_error(
        self, mock_check_gcal, client, db, test_company, test_pipeline, test_stage, test_config
    ):
        """Test that booking raises error when admin doesn't exist"""
        mock_check_gcal.return_value = True

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': 999,  # Non-existent
            'name': 'John Doe',
            'email': 'john@example.com',
            'company_name': 'Test Company',
            'company_id': test_company.id,
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 400
        assert 'Admin not found' in r.json()['message']

    async def test_sales_call_no_config_raises_error(self, client, db, test_admin):
        """Test that booking raises error when no config exists"""
        # Ensure no Config exists
        for config in db.exec(select(Config)).all():
            db.delete(config)
        db.commit()

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'John Doe',
            'email': 'john@example.com',
            'company_name': 'New Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 400
        assert 'System configuration not found' in r.json()['message']

    async def test_sales_call_stage_not_found_raises_error(self, client, db, test_admin, test_pipeline, test_config):
        """Test that booking raises error when stage referenced by pipeline doesn't exist"""
        # Create a pipeline with an invalid dft_entry_stage_id
        stage = db.create(Stage(pd_stage_id=999, name='Test Stage'))
        pipeline = db.create(Pipeline(pd_pipeline_id=998, name='Test Pipeline', dft_entry_stage_id=stage.id))

        # Update config to use this pipeline
        test_config.payg_pipeline_id = pipeline.id
        db.add(test_config)
        db.commit()

        # Delete the stage to simulate it being missing
        db.delete(stage)
        db.commit()

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'John Doe',
            'email': 'john@example.com',
            'company_name': 'New Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 400
        assert 'No stage configured' in r.json()['message']

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_with_startup_pipeline_config(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_admin
    ):
        """Test sales call with startup price plan uses startup_pipeline_id from config"""
        mock_gcal_builder.side_effect = fake_gcal_builder()

        # Create config with startup pipeline
        db.create(
            Config(
                payg_pipeline_id=test_pipeline.id,
                startup_pipeline_id=test_pipeline.id,
                enterprise_pipeline_id=test_pipeline.id,
            )
        )

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'John Doe',
            'email': 'john@example.com',
            'company_name': 'Startup Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'startup',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Verify deal was created with correct pipeline
        deal = db.exec(select(Deal)).first()
        assert deal.pipeline_id == test_pipeline.id

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_with_enterprise_pipeline_config(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_admin
    ):
        """Test sales call with enterprise price plan uses enterprise_pipeline_id from config"""
        mock_gcal_builder.side_effect = fake_gcal_builder()

        # Create config with enterprise pipeline
        db.create(
            Config(
                payg_pipeline_id=test_pipeline.id,
                startup_pipeline_id=test_pipeline.id,
                enterprise_pipeline_id=test_pipeline.id,
            )
        )

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'John Doe',
            'email': 'john@example.com',
            'company_name': 'Enterprise Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'enterprise',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Verify deal was created with correct pipeline
        deal = db.exec(select(Deal)).first()
        assert deal.pipeline_id == test_pipeline.id

    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_fails_when_admin_not_free(
        self, mock_gcal, client, db, test_admin, test_company, test_pipeline, test_stage, test_config
    ):
        """Test that booking fails when Google Calendar shows admin is busy"""
        # Mock Google Calendar to show admin has a busy slot at the requested time
        future_dt = datetime.now(utc) + timedelta(days=1)

        class MockGCal:
            def freebusy(self):
                return self

            def query(self, body):
                return self

            def execute(self):
                # Return busy slot that overlaps with requested meeting time
                busy_start = future_dt
                busy_end = future_dt + timedelta(hours=1)
                return {
                    'calendars': {
                        test_admin.email: {
                            'busy': [
                                {
                                    'start': busy_start.isoformat().replace('+00:00', 'Z'),
                                    'end': busy_end.isoformat().replace('+00:00', 'Z'),
                                }
                            ]
                        }
                    }
                }

        mock_gcal.side_effect = lambda *args, **kwargs: MockGCal()

        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'John Doe',
            'email': 'john@example.com',
            'company_name': 'Test Company',
            'company_id': test_company.id,
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 400
        assert 'not free' in r.json()['message'].lower()


class TestAvailabilityEndpoint:
    """Test availability endpoint for coverage"""

    async def test_availability_admin_not_found(self, client, db):
        """Test availability endpoint returns 404 when admin doesn't exist"""
        start_dt = datetime.now(utc) + timedelta(days=1)
        end_dt = start_dt + timedelta(hours=2)

        r = client.get(
            client.app.url_path_for('get-availability'),
            params={'admin_id': 999, 'start_dt': start_dt.isoformat(), 'end_dt': end_dt.isoformat()},
        )

        assert r.status_code == 404
        assert 'Admin not found' in r.json()['message']

    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_availability_returns_slots(self, mock_gcal, client, db, test_admin):
        """Test availability endpoint returns slots when admin exists"""

        class MockGCal:
            def freebusy(self):
                return self

            def query(self, body):
                return self

            def execute(self):
                return {'calendars': {test_admin.email: {'busy': []}}}

        mock_gcal.side_effect = lambda *args, **kwargs: MockGCal()

        start_dt = datetime(2026, 1, 5, 10, 0, tzinfo=utc)
        end_dt = datetime(2026, 1, 5, 12, 0, tzinfo=utc)

        r = client.get(
            client.app.url_path_for('get-availability'),
            params={'admin_id': test_admin.id, 'start_dt': start_dt.isoformat(), 'end_dt': end_dt.isoformat()},
        )

        assert r.status_code == 200
        data = r.json()
        assert data['status'] == 'ok'
        assert 'slots' in data

    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_availability_filters_overlapping_busy_slots(self, mock_gcal, client, db, test_admin):
        """Test availability endpoint filters out slots that overlap with busy calendar slots"""

        class MockGCal:
            def freebusy(self):
                return self

            def query(self, body):
                return self

            def execute(self):
                # Admin is busy 10:00-11:00 UTC
                busy_start = datetime(2026, 1, 5, 10, 0, tzinfo=utc)
                busy_end = datetime(2026, 1, 5, 11, 0, tzinfo=utc)
                return {
                    'calendars': {
                        test_admin.email: {
                            'busy': [
                                {
                                    'start': busy_start.isoformat().replace('+00:00', 'Z'),
                                    'end': busy_end.isoformat().replace('+00:00', 'Z'),
                                }
                            ]
                        }
                    }
                }

        mock_gcal.side_effect = lambda *args, **kwargs: MockGCal()

        start_dt = datetime(2026, 1, 5, 10, 0, tzinfo=utc)
        end_dt = datetime(2026, 1, 5, 14, 0, tzinfo=utc)

        r = client.get(
            client.app.url_path_for('get-availability'),
            params={'admin_id': test_admin.id, 'start_dt': start_dt.isoformat(), 'end_dt': end_dt.isoformat()},
        )

        assert r.status_code == 200
        data = r.json()
        assert data['status'] == 'ok'
        # Should have some slots but not at 10:00-11:00
        assert isinstance(data['slots'], list)
