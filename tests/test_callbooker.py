import re
from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import urlencode

from httpx import HTTPError
from pytz import utc

from app.models import Admin, Company, Contact, Meeting
from app.utils import settings, sign_args
from tests._common import HermesTestCase

CB_MEETING_DATA = {
    'name': 'Brain Junes',
    'timezone': 'Europe/Kiev',
    'email': 'brain@junes.com',
    'company_name': 'Junes Ltd',
    'website': 'https://junes.com',
    'country': 'GB',
    'estimated_income': 1000,
    'currency': 'GBP',
    'price_plan': Company.PP_PAYG,
    'meeting_dt': int(datetime(2026, 7, 3, 9, tzinfo=utc).timestamp()),
}


def _as_iso_8601(dt: datetime):
    return dt.isoformat().replace('+00:00', 'Z')


def fake_gcal_builder(error=False, start_dt: datetime = None, meeting_dur_mins: int = 90):
    class MockGCalResource:
        def execute(self):
            start = start_dt or datetime(2026, 7, 8, 11, tzinfo=utc)
            end = start + timedelta(minutes=meeting_dur_mins)
            return {
                'calendars': {
                    'climan@example.com': {'busy': [{'start': _as_iso_8601(start), 'end': _as_iso_8601(end)}]}
                }
            }

        def query(self, body: dict):
            self.body = body
            return self

        def freebusy(self, *args, **kwargs):
            return self

        def events(self):
            return self

        def insert(self, *args, **kwargs):
            if error:
                raise HTTPError('error')
            return self

    return MockGCalResource


class MeetingBookingTestCase(HermesTestCase):
    """
    A TestCase for testing when a company and contact need to be created when creating a meeting, and for testing when
    the admin is free for the meeting.

    We disable the tasks as we don't want to do any of the testing of Pipedrive here.
    """

    def setUp(self):
        self.url = '/callbooker/sales/book/'

    async def test_dt_validate_check_ts(self):
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data.update(meeting_dt=123, admin_id=1)
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 422
        detail = r.json()['detail']
        assert detail == [
            {
                'type': 'value_error',
                'loc': ['body', 'meeting_dt'],
                'msg': 'Value error, meeting_dt must be in the future',
                'input': 123,
                'ctx': {'error': {}},
            },
        ]

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_dt_validate_check_no_tz(self, mock_gcal_builder, mock_add_task):
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_support_person=True,
        )
        meeting_data.update(meeting_dt='2026-01-03T07:08', admin_id=admin.id)
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()
        meeting = await Meeting.get()
        assert meeting.start_time == datetime(2026, 1, 3, 7, 8, tzinfo=utc)
        assert mock_add_task.call_count == 1

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_dt_validate_check_utc(self, mock_gcal_builder, mock_add_task):
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        meeting_data.update(meeting_dt='2026-01-03T07:08:00+00:00', admin_id=admin.id)
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()
        meeting = await Meeting.get()
        assert meeting.start_time == datetime(2026, 1, 3, 7, 8, tzinfo=utc)

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_dt_validate_check_toronto(self, mock_gcal_builder, mock_add_task):
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        meeting_data.update(meeting_dt='2026-01-03T02:08:00-05:00', admin_id=admin.id)
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()
        meeting = await Meeting.get()
        assert meeting.start_time == datetime(2026, 1, 3, 7, 8, tzinfo=utc)

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_1(self, mock_gcal_builder, mock_add_task):
        """
        Book a new meeting
        Company doesn't exist so create
        Contact doesn't exist so create
        Create with admin
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        r = await self.client.post(self.url, json={'admin_id': sales_person.id, **CB_MEETING_DATA})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert not company.tc2_cligency_id
        assert company.name == 'Junes Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert company.estimated_income == '1000'
        assert not company.support_person
        assert not company.bdr_person
        assert company.has_booked_call
        assert await company.sales_person == sales_person

        contact = await Contact.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_2(self, mock_gcal_builder, mock_add_task):
        """
        Book a new meeting
        Company exists - match by company_id
        Contact doesn't exist so create
        """
        meeting_data = CB_MEETING_DATA.copy()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        company = await Company.create(
            name='Julies Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        meeting_data.update(company_id=company.id, admin_id=sales_person.id)
        mock_gcal_builder.side_effect = fake_gcal_builder()

        assert await Company.all().count() == 1
        assert await Contact.all().count() == 0

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.support_person
        assert company.has_booked_call
        assert await company.sales_person == sales_person
        assert not company.bdr_person

        contact = await Contact.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_3(self, mock_gcal_builder, mock_add_task):
        """
        Book a new meeting
        Company exists - match by cligency_id
        Contact exists - match by email
        """
        meeting_data = CB_MEETING_DATA.copy()
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        meeting_data.update(tc2_cligency_id=10, admin_id=sales_person.id)
        company = await Company.create(
            tc2_cligency_id=10, name='Julies Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        await Contact.create(first_name='B', last_name='J', email='brain@junes.com', company_id=company.id)

        assert await Company.all().count() == 1
        assert await Contact.all().count() == 1

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.tc2_cligency_id == 10
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.support_person
        assert not company.bdr_person
        assert company.has_booked_call
        assert await company.sales_person == sales_person

        contact = await Contact.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'J'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_4(self, mock_gcal_builder, mock_add_task):
        """
        Book a new meeting
        Company exists - match by company_id
        Contact exists - match by last name
        No admins linked
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        company = await Company.create(
            tc2_cligency_id=10, name='Julies Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data.update(company_id=company.id, admin_id=sales_person.id)
        await Contact.create(first_name='B', last_name='Junes', email='b@junes.com', company_id=company.id)

        assert await Company.all().count() == 1
        assert await Contact.all().count() == 1

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.tc2_cligency_id == 10
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.support_person
        assert not company.bdr_person
        assert company.has_booked_call
        assert await company.sales_person == sales_person

        contact = await Contact.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'Junes'
        assert contact.email == 'b@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_5(self, mock_gcal_builder, mock_add_task):
        """
        Book a new meeting
        Company exists - match by phone
        Contact exists - match by phone
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        await Contact.create(
            first_name='B', last_name='Junes', email='b@junes.com', company_id=company.id, phone='1234567'
        )

        assert await Company.all().count() == 1
        assert await Contact.all().count() == 1

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data.update(admin_id=sales_person.id, phone='1234567')
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert not company.tc2_cligency_id
        assert company.name == 'Junes Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.support_person
        assert not company.bdr_person
        assert company.has_booked_call
        contact = await Contact.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'Junes'
        assert contact.email == 'b@junes.com'
        assert contact.phone == '1234567'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_6(self, mock_gcal_builder, mock_add_task):
        """
        Book a new meeting
        Company exists - match by name
        Contact exists - match by last name
        No admins linked
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        await Contact.create(first_name='B', last_name='Junes', email='b@junes.com', company_id=company.id)

        assert await Company.all().count() == 1
        assert await Contact.all().count() == 1

        r = await self.client.post(self.url, json={'admin_id': sales_person.id, **CB_MEETING_DATA})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert not company.tc2_cligency_id
        assert company.name == 'Junes Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.support_person
        assert not company.bdr_person
        assert company.has_booked_call
        contact = await Contact.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'Junes'
        assert contact.email == 'b@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_7(self, mock_gcal_builder, mock_add_task):
        """
        Book a new meeting
        Company doesn't exist but checking cligency_id
        Contact doesn't exist so create
        No admins linked
        """
        meeting_data = CB_MEETING_DATA.copy()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        meeting_data.update(tc2_cligency_id=10, admin_id=sales_person.id)
        mock_gcal_builder.side_effect = fake_gcal_builder()
        company = await Company.create(
            name='Julies Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        await Contact.create(first_name='B', last_name='J', email='brain@junes.com', company_id=company.id)

        assert await Company.all().count() == 1
        assert await Contact.all().count() == 1

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert not company.tc2_cligency_id
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.support_person
        assert not company.bdr_person
        assert company.has_booked_call
        contact = await Contact.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'J'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_8(self, mock_gcal_builder, mock_add_task):
        """
        Book a new meeting
        Company doesn't exist but checking cligency_id
        Contact doesn't exist so create
        We've got a BDR added this time.
        """
        meeting_data = CB_MEETING_DATA.copy()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        bdr_person = await Admin.create(
            first_name='Brian', last_name='Jacques', username='bdr@example.com', is_bdr_person=True, tc2_admin_id=22
        )
        meeting_data.update(admin_id=sales_person.id, bdr_person_id=bdr_person.tc2_admin_id)
        mock_gcal_builder.side_effect = fake_gcal_builder()

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert not company.tc2_cligency_id
        assert company.name == 'Junes Ltd'
        assert company.has_booked_call
        assert (await company.bdr_person) == bdr_person
        assert (await company.sales_person) == sales_person

        contact = await Contact.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES

    async def test_meeting_already_exists(self):
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        contact = await Contact.create(first_name='B', last_name='Junes', email='b@junes.com', company_id=company.id)
        await Meeting.create(
            contact=contact,
            start_time=datetime(2026, 7, 3, 7, 30, tzinfo=utc),
            admin=sales_person,
            meeting_type=Meeting.TYPE_SUPPORT,
        )

        r = await self.client.post(self.url, json={'admin_id': sales_person.id, **CB_MEETING_DATA})
        assert r.status_code == 400
        assert r.json() == {'message': 'You already have a meeting booked around this time.', 'status': 'error'}

    async def test_contact_without_email(self):
        """Test that a contact without an email address cannot book a meeting"""
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        # Create a contact with only a phone number, no email
        await Contact.create(first_name='Brain', last_name='Junes', phone='3475154177', company_id=company.id)

        meeting_data = CB_MEETING_DATA.copy()
        # Remove email and use phone instead
        meeting_data.pop('email')
        meeting_data.update(phone='3475154177', company_id=company.id, admin_id=sales_person.id)

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 400
        assert r.json() == {'message': 'Contact must have an email address to book a meeting.', 'status': 'error'}

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_error_creating_gcal_event(self, mock_gcal_builder, mock_add_task):
        meeting_data = CB_MEETING_DATA.copy()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        meeting_data.update(tc2_cligency_id=10, admin_id=sales_person.id)
        mock_gcal_builder.side_effect = fake_gcal_builder()
        company = await Company.create(
            name='Julies Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        await Contact.create(first_name='B', last_name='J', email='brain@junes.com', company_id=company.id)

        assert await Company.all().count() == 1
        assert await Contact.all().count() == 1

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert not company.tc2_cligency_id
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.support_person
        assert not company.bdr_person
        assert company.has_booked_call
        contact = await Contact.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'J'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_admin_busy_start(self, mock_gcal_builder, mock_add_task):
        """
        The admin is busy from 11 - 12.30. Try booking a meeting at that starts at 12.30 and ends at 1.
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()

        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data.update(meeting_dt=int(datetime(2026, 7, 8, 12, 30, tzinfo=utc).timestamp()), admin_id=admin.id)

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        r = await self.client.post(self.url, json=meeting_data)
        assert r.json() == {'status': 'error', 'message': 'Admin is not free at this time.'}

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_admin_busy_during(self, mock_gcal_builder, mock_add_task):
        """
        The admin is busy from 11 - 12.30. Try booking a meeting at that starts at 11.15 and ends at 11.45.
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data.update(meeting_dt=int(datetime(2026, 7, 8, 11, 15, tzinfo=utc).timestamp()), admin_id=admin.id)

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 400, r.json()
        assert r.json() == {'status': 'error', 'message': 'Admin is not free at this time.'}

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_admin_busy_end(self, mock_gcal_builder, mock_add_task):
        """
        The admin is busy from 11 - 12.30. Try booking a meeting at that starts at 10.30 and ends at 11.
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data.update(meeting_dt=int(datetime(2026, 7, 8, 10, 45, tzinfo=utc).timestamp()), admin_id=admin.id)

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 400
        assert r.json() == {'status': 'error', 'message': 'Admin is not free at this time.'}

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_support_call_book_create_contact(self, mock_gcal_builder, mock_add_task):
        """
        Book a new SUPPORT meeting
        Company exists
        Contact doesn't exist so create
        Create with client manager
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        company = await Company.create(name='Julies Ltd', country='GB', sales_person=admin)
        meeting_data.update(company_id=company.id, admin_id=admin.id)
        assert await Contact.all().count() == 0
        r = await self.client.post('/callbooker/support/book/', json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'Julies Ltd'

        contact = await Contact.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == admin
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SUPPORT

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_support_call_book_contact_exists_no_email(self, mock_gcal_builder, mock_add_task):
        """
        Book a new SUPPORT meeting
        Company exists
        Contact exists no email
        Create with client manager
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        company = await Company.create(name='Julies Ltd', country='GB', sales_person=admin)

        contact = await Contact.create(first_name='B', last_name='Junes', company_id=company.id)

        meeting_data.update(company_id=company.id, admin_id=admin.id)
        r = await self.client.post('/callbooker/support/book/', json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'Julies Ltd'

        contact = await Contact.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == admin
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SUPPORT

    @mock.patch('fastapi.BackgroundTasks.add_task')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_bdr(self, mock_gcal_builder, mock_add_task):
        """
        Book a new meeting
        Company doesn't exist so create
        Contact doesn't exist so create
        Create with admin
        Create with bdr
        Create with utm_campaign
        Create with utm_source
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_support_person=True
        )
        bdr_person = await Admin.create(
            first_name='Michael', last_name='Bay', username='brdperson@example.com', is_bdr_person=True, tc2_admin_id=22
        )

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        r = await self.client.post(
            self.url,
            json={
                'admin_id': sales_person.id,
                'bdr_person_id': bdr_person.tc2_admin_id,
                'utm_campaign': 'test_campaign',
                'utm_source': 'test_source',
                **CB_MEETING_DATA,
            },
        )
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert not company.tc2_cligency_id
        assert company.name == 'Junes Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert company.estimated_income == '1000'
        assert not company.support_person
        assert await company.bdr_person == bdr_person
        assert await company.sales_person == sales_person
        assert company.utm_campaign == 'test_campaign'
        assert company.utm_source == 'test_source'

        contact = await Contact.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meeting.get()
        assert meeting.status == Meeting.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meeting.TYPE_SALES


@mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
class AdminAvailabilityTestCase(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.url = '/callbooker/availability/'

    async def test_admin_slots_standard_simple_london(self, mock_gcal_builder):
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        mock_gcal_builder.side_effect = fake_gcal_builder()
        start = datetime(2026, 7, 7, 2, tzinfo=utc)
        end = datetime(2026, 7, 9, 23, tzinfo=utc)
        r = await self.client.get(
            self.url, params={'admin_id': admin.id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()}
        )
        slots = r.json()['slots']
        slots_7th = [s for s in slots if s[0].startswith('2026-07-07')]
        slots_8th = [s for s in slots if s[0].startswith('2026-07-08')]
        slots_9th = [s for s in slots if s[0].startswith('2026-07-09')]

        assert len(slots_7th) == 10  # There should be 10 slots in the full day
        assert len(slots_8th) == 7  # There is a busy section on the 3rd so less slots
        assert len(slots_9th) == 10  # There should be 10 slots in the full day

        assert slots_8th == [
            ['2026-07-08T09:00:00+00:00', '2026-07-08T09:30:00+00:00'],
            ['2026-07-08T09:45:00+00:00', '2026-07-08T10:15:00+00:00'],
            ['2026-07-08T12:45:00+00:00', '2026-07-08T13:15:00+00:00'],
            ['2026-07-08T13:30:00+00:00', '2026-07-08T14:00:00+00:00'],
            ['2026-07-08T14:15:00+00:00', '2026-07-08T14:45:00+00:00'],
            ['2026-07-08T15:00:00+00:00', '2026-07-08T15:30:00+00:00'],
            ['2026-07-08T15:45:00+00:00', '2026-07-08T16:15:00+00:00'],
        ]

    async def test_admin_slots_toronto(self, mock_gcal_builder):
        """
        Testing when the admin is in the Toronto timezone
        """
        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            timezone='America/Toronto',
        )
        mock_gcal_builder.side_effect = fake_gcal_builder()
        start = datetime(2026, 7, 7, 2, tzinfo=utc)
        end = datetime(2026, 7, 9, 23, tzinfo=utc)
        r = await self.client.get(
            self.url, params={'admin_id': admin.id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()}
        )
        slots = r.json()['slots']
        slots_7th = [s for s in slots if s[0].startswith('2026-07-07')]
        slots_8th = [s for s in slots if s[0].startswith('2026-07-08')]
        slots_9th = [s for s in slots if s[0].startswith('2026-07-09')]

        assert len(slots_7th) == 10  # There should be 10 slots in the full day
        assert len(slots_8th) == 10  # Since the busy period is outside of the Admin's working hours, there are still 10
        assert len(slots_9th) == 10  # There should be 10 slots in the full day

        assert slots_8th == [
            ['2026-07-08T14:00:00+00:00', '2026-07-08T14:30:00+00:00'],
            ['2026-07-08T14:45:00+00:00', '2026-07-08T15:15:00+00:00'],
            ['2026-07-08T15:30:00+00:00', '2026-07-08T16:00:00+00:00'],
            ['2026-07-08T16:15:00+00:00', '2026-07-08T16:45:00+00:00'],
            ['2026-07-08T17:00:00+00:00', '2026-07-08T17:30:00+00:00'],
            ['2026-07-08T17:45:00+00:00', '2026-07-08T18:15:00+00:00'],
            ['2026-07-08T18:30:00+00:00', '2026-07-08T19:00:00+00:00'],
            ['2026-07-08T19:15:00+00:00', '2026-07-08T19:45:00+00:00'],
            ['2026-07-08T20:00:00+00:00', '2026-07-08T20:30:00+00:00'],
            ['2026-07-08T20:45:00+00:00', '2026-07-08T21:15:00+00:00'],
        ]

    @mock.patch('app.callbooker._availability.is_weekday')
    async def test_admin_slots_over_DST_change(self, mock_weekday, mock_gcal_builder):
        """
        Testing when we're looking at the admin's slots over a DST change
        """
        mock_weekday.return_value = False  # Need this to not be on a weekend to test
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        mock_gcal_builder.side_effect = fake_gcal_builder()
        start = datetime(2026, 3, 28, 2, tzinfo=utc)
        end = datetime(2026, 3, 30, 23, tzinfo=utc)
        r = await self.client.get(
            self.url, params={'admin_id': admin.id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()}
        )
        slots = r.json()['slots']
        slots_28th = [s for s in slots if s[0].startswith('2026-03-28')]
        slots_29th = [s for s in slots if s[0].startswith('2026-03-29')]
        slots_30th = [s for s in slots if s[0].startswith('2026-03-30')]

        assert len(slots_28th) == 10  # There should be 10 slots in the full day
        assert len(slots_29th) == 10
        assert len(slots_30th) == 10

        assert slots_28th[0] == ['2026-03-28T10:00:00+00:00', '2026-03-28T10:30:00+00:00']
        assert slots_28th[-1] == ['2026-03-28T16:45:00+00:00', '2026-03-28T17:15:00+00:00']

        assert slots_29th[0] == ['2026-03-29T09:00:00+00:00', '2026-03-29T09:30:00+00:00']
        assert slots_29th[-1] == ['2026-03-29T15:45:00+00:00', '2026-03-29T16:15:00+00:00']

        assert slots_30th[0] == ['2026-03-30T09:00:00+00:00', '2026-03-30T09:30:00+00:00']
        assert slots_30th[-1] == ['2026-03-30T15:45:00+00:00', '2026-03-30T16:15:00+00:00']

    async def test_admin_no_available_slots(self, mock_gcal_builder):
        """
        Testing when the admin has no slots
        """
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        mock_gcal_builder.side_effect = fake_gcal_builder()
        start = datetime(2026, 7, 8, 11, tzinfo=utc)
        end = datetime(2026, 7, 8, 12, tzinfo=utc)
        r = await self.client.get(
            self.url, params={'admin_id': admin.id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()}
        )
        assert r.json() == {'slots': [], 'status': 'ok'}

    async def test_slot_directly_after_busy_no_buffer(self, mock_gcal_builder):
        """
        Testing when the slot is directly after a busy period
        """
        self.config.meeting_buffer_mins = 0
        await self.config.save()
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        mock_gcal_builder.side_effect = fake_gcal_builder()
        start = datetime(2026, 7, 7, 2, tzinfo=utc)
        end = datetime(2026, 7, 9, 23, tzinfo=utc)
        r = await self.client.get(
            self.url, params={'admin_id': admin.id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()}
        )
        slots = r.json()['slots']
        slots_7th = [s for s in slots if s[0].startswith('2026-07-07')]
        slots_8th = [s for s in slots if s[0].startswith('2026-07-08')]
        slots_9th = [s for s in slots if s[0].startswith('2026-07-09')]

        assert len(slots_7th) == 15  # There should be 10 slots in the full day
        assert len(slots_8th) == 10  # There is a busy section on the 3rd so less slots
        assert len(slots_9th) == 15  # There should be 10 slots in the full day

        assert slots_8th == [
            ['2026-07-08T09:00:00+00:00', '2026-07-08T09:30:00+00:00'],
            ['2026-07-08T09:30:00+00:00', '2026-07-08T10:00:00+00:00'],
            ['2026-07-08T10:00:00+00:00', '2026-07-08T10:30:00+00:00'],
            ['2026-07-08T13:00:00+00:00', '2026-07-08T13:30:00+00:00'],
            ['2026-07-08T13:30:00+00:00', '2026-07-08T14:00:00+00:00'],
            ['2026-07-08T14:00:00+00:00', '2026-07-08T14:30:00+00:00'],
            ['2026-07-08T14:30:00+00:00', '2026-07-08T15:00:00+00:00'],
            ['2026-07-08T15:00:00+00:00', '2026-07-08T15:30:00+00:00'],
            ['2026-07-08T15:30:00+00:00', '2026-07-08T16:00:00+00:00'],
            ['2026-07-08T16:00:00+00:00', '2026-07-08T16:30:00+00:00'],
        ]

    async def test_admin_slots_short_meeting_starts_11(self, mock_gcal_builder):
        self.config.meeting_dur_mins = 30
        self.config.meeting_buffer_mins = 0
        await self.config.save()
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        mock_gcal_builder.side_effect = fake_gcal_builder(meeting_dur_mins=30)
        start = datetime(2026, 7, 8, 2, tzinfo=utc)
        end = datetime(2026, 7, 8, 23, tzinfo=utc)
        r = await self.client.get(
            self.url, params={'admin_id': admin.id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()}
        )
        slots = r.json()['slots']

        slots_8th = [s for s in slots if s[0].startswith('2026-07-08')]
        assert ['2026-07-08T11:00:00+00:00', '2026-07-08T11:30:00+00:00'] not in slots_8th

    async def test_availability_admin_busy_end(self, mock_gcal_builder):
        """
        Tests the scenario where a meeting is booked not on the callbooker so the admin is busy at a random interval.
        In this test, they have a meeting from 4pm -> 4:30pm which clashes with 2 meetings.

        All slots free until the 4pm meeting where the 3:30pm -> 4pm is blocked by the meeting that starts at 4pm
        and then the next slot at 4:15pm -> 4:45pm is also blocked by the 30min meeting that starts at 4pm and finally
        the 5pm slot is blocked because although the 5pm -> 5:30pm is free, we check the meeting length + buffer is
        less than the day end of 5:31pm which it isn't (that would be 5pm + 30min meeting + 15 min buffer).
        """
        self.config.meeting_dur_mins = 30
        self.config.meeting_buffer_mins = 15
        self.config.meeting_min_start = '08:00'
        self.config.meeting_max_end = '17:31'
        await self.config.save()

        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )

        start_dt = datetime(2024, 1, 9, 16, tzinfo=utc)
        mock_gcal_builder.side_effect = fake_gcal_builder(start_dt=start_dt, meeting_dur_mins=30)

        start = datetime(2024, 1, 9, 2, tzinfo=utc)
        end = datetime(2024, 1, 9, 23, tzinfo=utc)
        r = await self.client.get(
            self.url, params={'admin_id': admin.id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()}
        )
        slots = r.json()['slots']

        assert slots == [
            ['2024-01-09T08:00:00+00:00', '2024-01-09T08:30:00+00:00'],
            ['2024-01-09T08:45:00+00:00', '2024-01-09T09:15:00+00:00'],
            ['2024-01-09T09:30:00+00:00', '2024-01-09T10:00:00+00:00'],
            ['2024-01-09T10:15:00+00:00', '2024-01-09T10:45:00+00:00'],
            ['2024-01-09T11:00:00+00:00', '2024-01-09T11:30:00+00:00'],
            ['2024-01-09T11:45:00+00:00', '2024-01-09T12:15:00+00:00'],
            ['2024-01-09T12:30:00+00:00', '2024-01-09T13:00:00+00:00'],
            ['2024-01-09T13:15:00+00:00', '2024-01-09T13:45:00+00:00'],
            ['2024-01-09T14:00:00+00:00', '2024-01-09T14:30:00+00:00'],
            ['2024-01-09T14:45:00+00:00', '2024-01-09T15:15:00+00:00'],
            ['2024-01-09T17:00:00+00:00', '2024-01-09T17:30:00+00:00'],
        ]


class SupportLinkTestCase(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.gen_url = '/callbooker/support-link/generate/tc2/'
        self.valid_url = '/callbooker/support-link/validate/'

    async def test_generate_support_link(self):
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True, tc2_admin_id=20
        )
        company = await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', tc2_cligency_id=10, sales_person=admin
        )
        headers = {'Authorization': f'token {settings.tc2_api_key}', 'Content-Type': 'application/json'}
        r = await self.client.get(
            self.gen_url,
            params={'tc2_admin_id': admin.tc2_admin_id, 'tc2_cligency_id': company.tc2_cligency_id},
            headers=headers,
        )
        assert r.status_code == 200, r.json()
        link = r.json()['link']
        company_id = int(re.search(r'company_id=(\d+)', link).group(1))
        assert company_id == company.id
        admin_id = int(re.search(r'admin_id=(\d+)', link).group(1))
        assert admin_id == admin.id
        expiry = datetime.fromtimestamp(int(re.search(r'e=(\d+)', link).group(1)))
        assert expiry > datetime.utcnow()
        sig = re.search(r's=(.*?)&', link).group(1)
        expected_sig = await sign_args(admin_id, company_id, int(expiry.timestamp()))
        assert sig == expected_sig

    async def test_generate_support_link_admin_doesnt_exist(self):
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True, tc2_admin_id=20
        )
        await Company.create(
            name='Junes Ltd', website='https://junes.com', country='GB', tc2_cligency_id=10, sales_person=admin
        )
        headers = {'Authorization': f'token {settings.tc2_api_key}'}
        r = await self.client.get(self.gen_url, params={'tc2_admin_id': 1, 'tc2_cligency_id': 10}, headers=headers)
        assert r.status_code == 404

    async def test_validate_support_link(self):
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        company = await Company.create(name='Junes Ltd', website='https://junes.com', country='GB', sales_person=admin)

        expiry = datetime.now() + timedelta(minutes=1)
        sig = await sign_args(admin.id, company.id, int(expiry.timestamp()))
        kwargs = {'s': sig, 'e': int(expiry.timestamp()), 'company_id': company.id, 'admin_id': admin.id}
        link = self.valid_url + f'?{urlencode(kwargs)}'

        r = await self.client.get(link)
        assert r.status_code == 200, r.json()

    async def test_validate_support_link_invalid_sig(self):
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        company = await Company.create(name='Junes Ltd', website='https://junes.com', country='GB', sales_person=admin)
        expiry = datetime.now() + timedelta(minutes=1)
        kwargs = {'s': 'foo', 'e': int(expiry.timestamp()), 'company_id': company.id, 'admin_id': admin.id}
        link = self.valid_url + f'?{urlencode(kwargs)}'
        r = await self.client.get(link)
        assert r.status_code == 403, r.json()
        assert r.json()['message'] == 'Invalid signature'

    async def test_validate_support_link_expired(self):
        admin = await Admin.create(
            first_name='Steve', last_name='Jobs', username='climan@example.com', is_sales_person=True
        )
        company = await Company.create(name='Junes Ltd', website='https://junes.com', country='GB', sales_person=admin)
        expiry = datetime.now() - timedelta(minutes=1)
        kwargs = {
            's': await sign_args(admin.id, company.id, int(expiry.timestamp())),
            'e': int(expiry.timestamp()),
            'company_id': company.id,
            'admin_id': admin.id,
        }
        link = self.valid_url + f'?{urlencode(kwargs)}'
        r = await self.client.get(link)
        assert r.status_code == 403
        assert r.json()['message'] == 'Link has expired'
