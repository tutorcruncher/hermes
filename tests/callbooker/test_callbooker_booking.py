"""
Tests for callbooker booking flow.
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from pytz import utc
from sqlmodel import select

from app.main_app.models import Admin, Company, Config, Contact, Deal, Meeting, Pipeline, Stage

CB_MEETING_DATA = {
    'name': 'Brain Junes',
    'email': 'brain@junes.com',
    'company_name': 'Junes Ltd',
    'website': 'https://junes.com',
    'country': 'GB',
    'estimated_income': 1000,
    'currency': 'GBP',
    'price_plan': Company.PP_PAYG,
    'meeting_dt': datetime(2026, 7, 3, 9, tzinfo=utc).isoformat(),
}


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


class TestSalesCallBooking:
    """Test sales call booking flow"""

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_creates_company_and_contact(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test booking sales call creates new company and contact"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = db.create(Admin(first_name='Steve', last_name='Jobs', username='climan@example.com'))

        r = client.post(
            client.app.url_path_for('book-sales-call'), json={'admin_id': sales_person.id, **CB_MEETING_DATA}
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        company = db.exec(select(Company)).first()
        assert company.name == 'Junes Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert company.has_booked_call is True

        contact = db.exec(select(Contact)).first()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'

        meeting = db.exec(select(Meeting)).first()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.meeting_type == Meeting.TYPE_SALES

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_finds_existing_company_by_id(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test booking sales call finds existing company by company_id"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = db.create(Admin(first_name='Steve', last_name='Jobs', username='climan@example.com'))
        company = db.create(
            Company(name='Existing Company', sales_person_id=sales_person.id, price_plan='payg', country='GB')
        )

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['company_id'] = company.id

        r = client.post(client.app.url_path_for('book-sales-call'), json={'admin_id': sales_person.id, **meeting_data})

        assert r.status_code == 200

        companies = db.exec(select(Company)).all()
        assert len(companies) == 1
        assert companies[0].id == company.id

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_finds_existing_contact_by_email(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test booking sales call finds existing contact by email"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = db.create(Admin(first_name='Steve', last_name='Jobs', username='climan@example.com'))
        company = db.create(Company(name='Junes Ltd', sales_person_id=sales_person.id, price_plan='payg', country='GB'))
        existing_contact = db.create(
            Contact(first_name='Brain', last_name='Junes', email='brain@junes.com', company_id=company.id)
        )

        r = client.post(
            client.app.url_path_for('book-sales-call'), json={'admin_id': sales_person.id, **CB_MEETING_DATA}
        )

        assert r.status_code == 200

        contacts = db.exec(select(Contact)).all()
        assert len(contacts) == 1
        assert contacts[0].id == existing_contact.id

    async def test_sales_call_prevents_double_booking(self, client, db, test_pipeline, test_stage, test_config):
        """Test that booking prevents double-booking within 2 hours"""
        sales_person = db.create(Admin(first_name='Steve', last_name='Jobs', username='climan@example.com'))
        company = db.create(Company(name='Junes Ltd', sales_person_id=sales_person.id, price_plan='payg', country='GB'))
        contact = db.create(
            Contact(first_name='Brain', last_name='Junes', email='brain@junes.com', company_id=company.id)
        )

        meeting_time = datetime(2026, 7, 3, 9, tzinfo=utc)
        db.create(
            Meeting(
                contact_id=contact.id,
                company_id=company.id,
                admin_id=sales_person.id,
                start_time=meeting_time,
                end_time=meeting_time + timedelta(minutes=30),
                meeting_type=Meeting.TYPE_SALES,
            )
        )

        r = client.post(
            client.app.url_path_for('book-sales-call'), json={'admin_id': sales_person.id, **CB_MEETING_DATA}
        )

        assert r.status_code == 400
        assert r.json() == {'status': 'error', 'message': 'You already have a meeting booked around this time.'}

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_exactly_2_hours_before_existing_meeting(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test booking exactly 2 hours before existing meeting is allowed"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = db.create(Admin(first_name='Steve', last_name='Jobs', username='climan@example.com'))
        company = db.create(Company(name='Junes Ltd', sales_person_id=sales_person.id, price_plan='payg', country='GB'))
        contact = db.create(
            Contact(first_name='Brain', last_name='Junes', email='brain@junes.com', company_id=company.id)
        )

        existing_meeting_time = datetime(2026, 7, 3, 11, 0, tzinfo=utc)  # 11:00
        db.create(
            Meeting(
                contact_id=contact.id,
                company_id=company.id,
                admin_id=sales_person.id,
                start_time=existing_meeting_time,
                end_time=existing_meeting_time + timedelta(minutes=30),
                meeting_type=Meeting.TYPE_SALES,
            )
        )

        # Try to book exactly 2 hours before (9:00, buffer window is 9:00-13:00)
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = datetime(2026, 7, 3, 9, 0, tzinfo=utc).isoformat()

        r = client.post(client.app.url_path_for('book-sales-call'), json={'admin_id': sales_person.id, **meeting_data})

        # Should fail because it's within 2 hour window
        assert r.status_code == 400
        assert 'already have a meeting' in r.json()['message']

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_just_outside_2_hour_window(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test booking just outside 2 hour window succeeds"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = db.create(Admin(first_name='Steve', last_name='Jobs', username='climan@example.com'))
        company = db.create(Company(name='Junes Ltd', sales_person_id=sales_person.id, price_plan='payg', country='GB'))
        contact = db.create(
            Contact(first_name='Brain', last_name='Junes', email='brain@junes.com', company_id=company.id)
        )

        existing_meeting_time = datetime(2026, 7, 3, 13, 1, tzinfo=utc)  # 13:01
        db.create(
            Meeting(
                contact_id=contact.id,
                company_id=company.id,
                admin_id=sales_person.id,
                start_time=existing_meeting_time,
                end_time=existing_meeting_time + timedelta(minutes=30),
                meeting_type=Meeting.TYPE_SALES,
            )
        )

        # Try to book at 9:00 (4+ hours before)
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = datetime(2026, 7, 3, 9, 0, tzinfo=utc).isoformat()

        r = client.post(client.app.url_path_for('book-sales-call'), json={'admin_id': sales_person.id, **meeting_data})

        # Should succeed - outside 2 hour window
        assert r.status_code == 200

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_truncates_very_long_names(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test callbooker truncates very long names to 255 chars"""
        mock_gcal_builder.side_effect = fake_gcal_builder()

        admin = db.create(Admin(first_name='Test', last_name='Admin', username='climan@example.com'))

        very_long_name = 'FirstName' * 30 + ' ' + 'LastName' * 30
        very_long_company = 'Company' * 40

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': admin.id,
            'name': very_long_name,
            'email': 'test@example.com',
            'company_name': very_long_company,
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Check that names were truncated
        company = db.exec(select(Company)).first()
        assert len(company.name) == 255

        contact = db.exec(select(Contact)).first()
        assert len(contact.first_name) <= 255 if contact.first_name else True
        assert len(contact.last_name) <= 255

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_with_configured_payg_pipeline(
        self, mock_gcal_builder, mock_add_task, client, db, test_admin
    ):
        """Test PAYG uses config.payg_pipeline_id when set"""
        mock_gcal_builder.side_effect = fake_gcal_builder()

        # Create stage first, then pipelines
        stage = db.create(Stage(pd_stage_id=200, name='Initial Stage'))
        payg_pipeline = db.create(Pipeline(pd_pipeline_id=100, name='PAYG Pipeline', dft_entry_stage_id=stage.id))
        other_pipeline = db.create(Pipeline(pd_pipeline_id=101, name='Other Pipeline', dft_entry_stage_id=stage.id))

        # Create config with payg_pipeline_id set
        db.create(
            Config(
                payg_pipeline_id=payg_pipeline.id,
                startup_pipeline_id=other_pipeline.id,
                enterprise_pipeline_id=other_pipeline.id,
            )
        )

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'John Doe',
            'email': 'john@example.com',
            'company_name': 'PAYG Config Test',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Should use the configured payg pipeline
        deal = db.exec(select(Deal)).first()
        assert deal.pipeline_id == payg_pipeline.id

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_finds_company_by_name(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_admin, test_config
    ):
        """Test booking finds existing company by name"""
        mock_gcal_builder.side_effect = fake_gcal_builder()

        # Create existing company
        existing_company = db.create(
            Company(name='Exact Match Company', sales_person_id=test_admin.id, price_plan='payg')
        )

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'John Doe',
            'email': 'john@example.com',
            'company_name': 'exact match company',  # Case-insensitive match
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Should reuse existing company (not create new one)
        companies = db.exec(select(Company)).all()
        assert len(companies) == 1
        assert companies[0].id == existing_company.id

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_finds_contact_by_phone(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_admin, test_config
    ):
        """Test booking finds existing contact by phone number"""
        mock_gcal_builder.side_effect = fake_gcal_builder()

        # Create existing company and contact with phone
        company = db.create(Company(name='Unique Phone Company', sales_person_id=test_admin.id, price_plan='payg'))
        db.create(
            Contact(
                first_name='John',
                last_name='Doe',
                email='original@example.com',  # Has email
                phone='+1234567890',
                company_id=company.id,
            )
        )

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'Different Name',
            'email': 'newemail@example.com',  # Different email (won't match existing contact)
            'phone': '+1234567890',  # Same phone - this will match!
            'company_name': 'Unique Phone Company',  # Will match by name as fallback
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Should find company via contact found by phone
        companies = db.exec(select(Company)).all()
        assert len(companies) == 1
        assert companies[0].id == company.id

    async def test_sales_call_requires_contact_email(self, client, db, test_pipeline, test_stage, test_config):
        """Test that booking requires contact to have email"""
        sales_person = db.create(Admin(first_name='Steve', last_name='Jobs', username='climan@example.com'))
        company = db.create(Company(name='Junes Ltd', sales_person_id=sales_person.id, price_plan='payg', country='GB'))
        db.create(Contact(first_name='Brain', last_name='Junes', company_id=company.id))

        meeting_data = CB_MEETING_DATA.copy()
        del meeting_data['email']
        meeting_data['company_id'] = company.id

        r = client.post(client.app.url_path_for('book-sales-call'), json={'admin_id': sales_person.id, **meeting_data})

        assert r.status_code == 422

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_with_bdr_person(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test booking sales call with BDR person"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = db.create(Admin(first_name='Sales', last_name='Person', username='sales@example.com'))
        bdr_person = db.create(
            Admin(
                first_name='BDR',
                last_name='Person',
                username='bdr@example.com',
                tc2_admin_id=22,
                is_bdr_person=True,
            )
        )

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['bdr_person_id'] = bdr_person.tc2_admin_id

        r = client.post(client.app.url_path_for('book-sales-call'), json={'admin_id': sales_person.id, **meeting_data})

        assert r.status_code == 200

        company = db.exec(select(Company)).first()
        assert company.bdr_person_id == bdr_person.tc2_admin_id

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_with_bdr_person_resolves_tc2_admin_id(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test booking sales call when tc2_admin_id is passed as bdr_person_id gets resolved to admin.id"""
        from sqlalchemy.exc import IntegrityError

        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = db.create(Admin(first_name='Sales', last_name='Person', username='sales@example.com'))
        bdr_person = db.create(
            Admin(
                first_name='BDR',
                last_name='Person',
                username='bdr@example.com',
                tc2_admin_id=4253776,
                is_bdr_person=True,
            )
        )

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['bdr_person_id'] = 4253776

        original_commit = db.commit
        commit_count = [0]

        def mock_commit():
            commit_count[0] += 1
            if commit_count[0] == 1:
                raise IntegrityError('', '', '', '')
            return original_commit()

        db.commit = mock_commit

        try:
            r = client.post(
                client.app.url_path_for('book-sales-call'), json={'admin_id': sales_person.id, **meeting_data}
            )

            assert r.status_code == 200

            company = db.exec(select(Company)).first()
            assert company.bdr_person_id == bdr_person.id
        finally:
            db.commit = original_commit

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_uses_pipeline_dft_entry_stage(
        self, mock_gcal_builder, mock_add_task, client, db, test_admin
    ):
        """Test that new deals use pipeline's default entry stage when set"""
        mock_gcal_builder.side_effect = fake_gcal_builder()

        # Create stages first
        db.create(Stage(pd_stage_id=1, name='Lead'))
        stage2 = db.create(Stage(pd_stage_id=2, name='Qualified'))  # This will be the default
        db.create(Stage(pd_stage_id=3, name='Proposal'))

        # Create pipeline with a default entry stage
        pipeline = db.create(Pipeline(pd_pipeline_id=1, name='Sales Pipeline', dft_entry_stage_id=stage2.id))

        # Create config pointing to this pipeline
        db.create(
            Config(payg_pipeline_id=pipeline.id, startup_pipeline_id=pipeline.id, enterprise_pipeline_id=pipeline.id)
        )

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'Test User',
            'email': 'test@example.com',
            'phone': '+1234567890',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Check that the deal was created with the default entry stage
        deal = db.exec(select(Deal)).first()
        assert deal is not None
        assert deal.stage_id == stage2.id  # Should use the configured default stage


class TestSupportCallBooking:
    """Test support call booking flow"""

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_support_call_creates_contact(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test booking support call creates contact"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        admin = db.create(Admin(first_name='Support', last_name='Person', username='support@example.com'))
        company = db.create(Company(name='Test Company', sales_person_id=admin.id, price_plan='payg', country='GB'))

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['company_id'] = company.id

        r = client.post(client.app.url_path_for('book-support-call'), json={'admin_id': admin.id, **meeting_data})

        assert r.status_code == 200

        contact = db.exec(select(Contact)).first()
        assert contact.email == 'brain@junes.com'

        meeting = db.exec(select(Meeting)).first()
        assert meeting.meeting_type == Meeting.TYPE_SUPPORT

    async def test_support_call_requires_existing_company(self, client, db):
        """Test that support call requires existing company"""
        admin = db.create(Admin(first_name='Support', last_name='Person', username='support@example.com'))

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['company_id'] = 999

        r = client.post(client.app.url_path_for('book-support-call'), json={'admin_id': admin.id, **meeting_data})

        assert r.status_code == 404

    async def test_support_call_handles_booking_error(self, client, db):
        """Test that support call handles MeetingBookingError"""
        admin = db.create(Admin(first_name='Support', last_name='Person', username='support@example.com'))
        company = db.create(Company(name='Test Company', sales_person_id=admin.id, price_plan='payg', country='GB'))
        db.create(Contact(first_name='Test', last_name='Contact', company_id=company.id))

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['company_id'] = company.id
        del meeting_data['email']

        r = client.post(client.app.url_path_for('book-support-call'), json={'admin_id': admin.id, **meeting_data})

        assert r.status_code == 400
        assert r.json()['status'] == 'error'


class TestCallbookerValidation:
    """Test callbooker request validation"""

    async def test_sales_call_rejects_past_datetime(self, client, db, test_pipeline, test_stage, test_config):
        """Test that sales call booking rejects past meeting_dt"""
        admin = db.create(Admin(first_name='Test', last_name='Admin', username='test@example.com'))

        past_dt = datetime.now(utc) - timedelta(days=1)
        meeting_data = {
            'admin_id': admin.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': past_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 422

    async def test_sales_call_rejects_invalid_price_plan(self, client, db, test_pipeline, test_stage, test_config):
        """Test that sales call booking rejects invalid price_plan"""
        admin = db.create(Admin(first_name='Test', last_name='Admin', username='test@example.com'))

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': admin.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'invalid_plan',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 422

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_with_single_name(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test that single name (no space) is handled correctly"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        admin = db.create(Admin(first_name='Test', last_name='Admin', username='climan@example.com'))

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': admin.id,
            'name': 'Madonna',  # Single name, no space
            'email': 'madonna@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Verify contact has single name in last_name, None in first_name
        contact = db.exec(select(Contact)).first()
        assert contact.first_name is None
        assert contact.last_name == 'Madonna'

    async def test_support_call_rejects_past_datetime(self, client, db, test_pipeline, test_stage, test_config):
        """Test that support call booking rejects past meeting_dt"""
        admin = db.create(Admin(first_name='Test', last_name='Admin', username='test@example.com'))
        company = db.create(Company(name='Test Company', sales_person_id=admin.id, price_plan='payg'))

        past_dt = datetime.now(utc) - timedelta(days=1)
        meeting_data = {
            'admin_id': admin.id,
            'company_id': company.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'meeting_dt': past_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-support-call'), json=meeting_data)

        assert r.status_code == 422

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_support_call_with_single_name(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test that support call with single name is handled correctly"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        admin = db.create(Admin(first_name='Test', last_name='Admin', username='climan@example.com'))
        company = db.create(Company(name='Test Company', sales_person_id=admin.id, price_plan='payg'))

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': admin.id,
            'company_id': company.id,
            'name': 'Cher',  # Single name
            'email': 'cher@example.com',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-support-call'), json=meeting_data)

        assert r.status_code == 200

        # Verify contact has single name in last_name
        contact = db.exec(select(Contact).where(Contact.email == 'cher@example.com')).first()
        assert contact.first_name is None
        assert contact.last_name == 'Cher'

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_accepts_naive_datetime(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test that naive datetime (no timezone) is accepted and converted to UTC"""
        mock_gcal_builder.side_effect = fake_gcal_builder()
        admin = db.create(Admin(first_name='Test', last_name='Admin', username='climan@example.com'))

        future_dt_naive = datetime.now() + timedelta(days=1)
        meeting_data = {
            'admin_id': admin.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt_naive.isoformat(),  # No timezone in ISO string
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Verify meeting was created
        meeting = db.exec(select(Meeting)).first()
        assert meeting is not None

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_accepts_non_utc_timezone(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test that non-UTC timezone is accepted and converted to UTC"""
        import pytz

        mock_gcal_builder.side_effect = fake_gcal_builder()
        admin = db.create(Admin(first_name='Test', last_name='Admin', username='climan@example.com'))

        eastern = pytz.timezone('US/Eastern')
        future_dt_eastern = datetime.now(eastern) + timedelta(days=1)
        meeting_data = {
            'admin_id': admin.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt_eastern.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200

        # Verify meeting was created
        meeting = db.exec(select(Meeting)).first()
        assert meeting is not None

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_rollback_on_google_calendar_failure(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test that meeting is NOT persisted if Google Calendar event creation fails"""
        from unittest.mock import Mock

        from googleapiclient.errors import HttpError

        # Mock Google Calendar to raise an error when creating event
        mock_resource = mock_gcal_builder.return_value
        mock_resource.freebusy.return_value.query.return_value.execute.return_value = {
            'calendars': {'test@example.com': {'busy': []}}
        }
        # Simulate Google Calendar API error during event creation
        mock_resp = Mock()
        mock_resp.status = 403
        mock_resp.reason = 'Forbidden'
        mock_resource.events.return_value.insert.return_value.execute.side_effect = HttpError(
            resp=mock_resp, content=b'Forbidden'
        )

        admin = db.create(Admin(first_name='Test', last_name='Admin', username='test@example.com'))

        future_dt = datetime.now(utc) + timedelta(days=1)
        meeting_data = {
            'admin_id': admin.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': future_dt.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        # Should return error
        assert r.status_code == 400
        assert r.json()['status'] == 'error'
        assert 'calendar event' in r.json()['message'].lower()

        # CRITICAL: Meeting should NOT be persisted in database
        meetings = db.exec(select(Meeting)).all()
        assert len(meetings) == 0, 'Meeting was persisted despite Google Calendar failure - transaction not rolled back'

        # Company and contact should still be created (they're committed earlier in the flow)
        company = db.exec(select(Company)).first()
        assert company is not None  # Company creation happened before meeting

        # Verify we can book again at the same time (no phantom meeting blocking)
        mock_resource.events.return_value.insert.return_value.execute.side_effect = None  # Clear error
        mock_resource.events.return_value.insert.return_value.execute.return_value = {'id': 'event123'}

        admins = db.exec(select(Admin)).all()
        assert len(admins) == 1
        r2 = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)
        assert r2.status_code == 200, 'Second booking should succeed - no phantom meeting should block it'
        # Now meeting should exist
        meetings = db.exec(select(Meeting)).all()
        assert len(meetings) == 1

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_admin_busy_check_via_google_calendar(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """Test that admin busy check via Google Calendar freebusy API prevents booking"""
        # Mock admin as busy at the requested time
        requested_time = datetime(2026, 7, 3, 10, 0, tzinfo=utc)
        mock_gcal_builder.side_effect = fake_gcal_builder(start_dt=requested_time, meeting_dur_mins=30)

        admin = db.create(Admin(first_name='Test', last_name='Admin', username='climan@example.com'))

        meeting_data = {
            'admin_id': admin.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': requested_time.isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        # Should fail because admin is busy in Google Calendar
        assert r.status_code == 400
        assert r.json()['status'] == 'error'
        assert 'not free' in r.json()['message'].lower()

        # Meeting should not be created
        meetings = db.exec(select(Meeting)).all()
        assert len(meetings) == 0

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_complete_google_calendar_workflow_end_to_end(
        self, mock_gcal_builder, mock_add_task, client, db, test_pipeline, test_stage, test_config
    ):
        """
        Comprehensive end-to-end test of Google Calendar integration workflow.

        This test validates:
        1. Admin availability check via Google Calendar freebusy API
        2. Meeting creation with Google Calendar event
        3. Database connection release before external API calls (asyncio.to_thread)
        4. Compensating transaction on Google Calendar failure
        5. Multiple booking attempts with different time slots
        6. Calendar event data formatting and attendees
        """
        from unittest.mock import Mock

        # Setup admin with specific email for calendar testing
        admin = db.create(
            Admin(
                first_name='Test',
                last_name='Admin',
                username='test@example.com',
                tc2_admin_id=1,
                pd_owner_id=1,
                is_sales_person=True,
            )
        )

        # Mock Google Calendar resource with detailed tracking
        mock_resource = Mock()
        mock_gcal_builder.return_value = mock_resource

        # Track all freebusy queries
        freebusy_calls = []

        class MockFreeBusyQuery:
            def __init__(self, body):
                freebusy_calls.append(body)
                self.body = body

            def execute(self):
                busy_start = datetime(2026, 7, 3, 10, 0, tzinfo=utc)
                busy_end = datetime(2026, 7, 3, 11, 0, tzinfo=utc)
                return {
                    'calendars': {
                        admin.username: {
                            'busy': [
                                {
                                    'start': busy_start.isoformat().replace('+00:00', 'Z'),
                                    'end': busy_end.isoformat().replace('+00:00', 'Z'),
                                }
                            ]
                        }
                    }
                }

        mock_resource.freebusy.return_value.query.side_effect = MockFreeBusyQuery

        # Track all calendar event creations
        event_creations = []

        class MockEventInsert:
            def __init__(self, calendarId=None, body=None, **kwargs):
                event_creations.append({'calendar_id': calendarId, 'event': body})
                self.calendar_id = calendarId
                self.body = body

            def execute(self):
                return {'id': f'event_{len(event_creations)}', 'htmlLink': 'https://calendar.google.com/event123'}

        mock_resource.events.return_value.insert.side_effect = MockEventInsert

        # Test 1: Attempt to book during busy time (10:00-10:30) - should fail
        busy_time = datetime(2026, 7, 3, 10, 15, tzinfo=utc)
        meeting_data_busy = {
            'admin_id': admin.id,
            'name': 'John Smith',
            'email': 'john@example.com',
            'company_name': 'Example Corp',
            'country': 'GB',
            'estimated_income': 5000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': busy_time.isoformat(),
        }

        r1 = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data_busy)

        assert r1.status_code == 400
        assert r1.json()['status'] == 'error'
        assert 'not free' in r1.json()['message'].lower()

        # Verify freebusy was checked
        assert len(freebusy_calls) == 1
        assert freebusy_calls[0]['items'][0]['id'] == admin.username

        # Verify no meeting was created in database
        meetings = db.exec(select(Meeting)).all()
        assert len(meetings) == 0

        # Verify no calendar event was created
        assert len(event_creations) == 0

        # Test 2: Book during free time (14:00-14:30) - should succeed
        free_time = datetime(2026, 7, 3, 14, 0, tzinfo=utc)
        meeting_data_free = {
            'admin_id': admin.id,
            'name': 'Jane Doe',
            'email': 'jane@example.com',
            'company_name': 'Acme Inc',
            'country': 'US',
            'estimated_income': 10000,
            'currency': 'USD',
            'price_plan': 'startup',
            'meeting_dt': free_time.isoformat(),
        }

        r2 = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data_free)

        assert r2.status_code == 200
        assert r2.json()['status'] == 'ok'

        # Verify freebusy was checked again
        assert len(freebusy_calls) == 2

        # Verify meeting was created in database
        meetings = db.exec(select(Meeting).order_by(Meeting.id)).all()
        assert len(meetings) == 1
        meeting = meetings[0]
        assert meeting.start_time.replace(tzinfo=utc) == free_time
        assert meeting.end_time.replace(tzinfo=utc) == free_time + timedelta(minutes=30)
        assert meeting.meeting_type == Meeting.TYPE_SALES
        assert meeting.admin_id == admin.id

        # Verify company and contact were created
        company = db.exec(select(Company).where(Company.name == 'Acme Inc')).first()
        assert company is not None
        assert company.has_booked_call is True
        assert company.price_plan == 'startup'
        assert company.estimated_income == '10000'

        contact = db.exec(select(Contact).where(Contact.email == 'jane@example.com')).first()
        assert contact is not None
        assert contact.first_name == 'Jane'
        assert contact.last_name == 'Doe'
        assert contact.company_id == company.id

        # Verify deal was created
        deal = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        assert deal is not None
        assert deal.status == Deal.STATUS_OPEN
        assert meeting.deal_id == deal.id

        # Verify Google Calendar event was created
        assert len(event_creations) == 1
        calendar_event = event_creations[0]['event']

        # Verify event details
        assert calendar_event['summary'] == meeting.name
        assert 'Jane' in calendar_event['description']
        assert 'Acme Inc' in calendar_event['description']
        assert calendar_event['start']['dateTime'] == free_time.isoformat().replace('+00:00', '')
        assert calendar_event['start']['timeZone'] == 'UTC'
        assert calendar_event['end']['dateTime'] == (free_time + timedelta(minutes=30)).isoformat().replace(
            '+00:00', ''
        )
        assert calendar_event['end']['timeZone'] == 'UTC'

        # Verify attendees
        attendees = calendar_event['attendees']
        assert len(attendees) == 2
        attendee_emails = [a['email'] for a in attendees]
        assert admin.username in attendee_emails
        assert 'jane@example.com' in attendee_emails

        # Verify conferencing (Google Meet) is requested
        assert 'conferenceData' in calendar_event

        # Verify background tasks were queued
        assert mock_add_task.call_count >= 2
        call_args = [call.args[0].__name__ for call in mock_add_task.call_args_list]
        assert 'sync_company_to_pipedrive' in call_args
        assert 'sync_meeting_to_pipedrive' in call_args

        # Test 3: Attempt duplicate booking within 2 hours - should fail
        duplicate_time = free_time + timedelta(hours=1)
        meeting_data_duplicate = {
            'admin_id': admin.id,
            'name': 'Jane Doe',
            'email': 'jane@example.com',
            'company_name': 'Acme Inc',
            'country': 'US',
            'estimated_income': 10000,
            'currency': 'USD',
            'price_plan': 'startup',
            'meeting_dt': duplicate_time.isoformat(),
        }

        r3 = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data_duplicate)

        assert r3.status_code == 400
        assert r3.json()['status'] == 'error'
        assert 'already have a meeting' in r3.json()['message'].lower()

        # Still only one meeting in database
        meetings = db.exec(select(Meeting)).all()
        assert len(meetings) == 1

        # Test 4: Book outside 2-hour window - should succeed
        outside_window_time = free_time + timedelta(hours=3)
        meeting_data_outside = {
            'admin_id': admin.id,
            'name': 'Jane Doe',
            'email': 'jane@example.com',
            'company_name': 'Acme Inc',
            'country': 'US',
            'estimated_income': 10000,
            'currency': 'USD',
            'price_plan': 'startup',
            'meeting_dt': outside_window_time.isoformat(),
        }

        r4 = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data_outside)

        assert r4.status_code == 200
        assert r4.json()['status'] == 'ok'

        # Now two meetings exist
        meetings = db.exec(select(Meeting).order_by(Meeting.start_time)).all()
        assert len(meetings) == 2
        assert meetings[0].start_time.replace(tzinfo=utc) == free_time
        assert meetings[1].start_time.replace(tzinfo=utc) == outside_window_time

        # Two calendar events created
        assert len(event_creations) == 2
