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
