from datetime import datetime
from unittest import mock

from httpx import HTTPError
from pytz import utc

from app.models import Admins, Companies, Contacts, Meetings
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
    'admin_id': 20,
    'meeting_dt': int(datetime(2026, 7, 3, 9, tzinfo=utc).timestamp()),
}


def _as_iso_8601(dt: datetime):
    return dt.isoformat().replace('+00:00', 'Z')


def fake_gcal_builder(error=False):
    class MockGCalResource:
        def execute(self):
            return {
                'calendars': {
                    'climan@example.com': {
                        'busy': [
                            {
                                'start': _as_iso_8601(datetime(2026, 7, 3, 11, tzinfo=utc)),
                                'end': _as_iso_8601(datetime(2026, 7, 3, 12, 30, tzinfo=utc)),
                            }
                        ]
                    }
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
    """

    def setUp(self):
        super().setUp()
        self.url = '/callbooker/sales/book/'

    async def test_dt_validate_check_ts(self):
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = 123
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 422
        assert r.json() == {
            'detail': [
                {
                    'loc': ['body', 'meeting_dt'],
                    'msg': 'meeting_dt must be in the future',
                    'type': 'value_error',
                }
            ]
        }

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_dt_validate_check_no_tz(self, mock_gcal_builder):
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = '2026-01-03T07:08'
        await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_client_manager=True,
            tc_admin_id=20,
        )
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()
        meeting = await Meetings.get()
        assert meeting.start_time == datetime(2026, 1, 3, 7, 8, tzinfo=utc)

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_dt_validate_check_utc(self, mock_gcal_builder):
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = '2026-01-03T07:08:00+00:00'
        await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_client_manager=True,
            tc_admin_id=20,
        )
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()
        meeting = await Meetings.get()
        assert meeting.start_time == datetime(2026, 1, 3, 7, 8, tzinfo=utc)

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_dt_validate_check_toronto(self, mock_gcal_builder):
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = '2026-01-03T02:08:00-05:00'
        await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_client_manager=True,
            tc_admin_id=20,
        )
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()
        meeting = await Meetings.get()
        assert meeting.start_time == datetime(2026, 1, 3, 7, 8, tzinfo=utc)

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_1(self, mock_gcal_builder):
        """
        Book a new meeting
        Company doesn't exist so create
        Contact doesn't exist so create
        Create with admin
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_client_manager=True,
            tc_admin_id=20,
        )
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0
        r = await self.client.post(self.url, json=CB_MEETING_DATA)
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert not company.tc_cligency_id
        assert company.name == 'Junes Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert company.estimated_income == '1000'
        assert not company.client_manager_id
        assert not company.bdr_person_id
        assert await company.sales_person == sales_person

        contact = await Contacts.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SALES

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_2(self, mock_gcal_builder):
        """
        Book a new meeting
        Company exists - match by cligency_id
        Contact doesn't exist so create
        """
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_client_manager=True,
            tc_admin_id=20,
        )
        await Companies.create(tc_cligency_id=10, name='Julies Ltd', website='https://junes.com', country='GB')

        assert await Companies.all().count() == 1
        assert await Contacts.all().count() == 0

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert company.tc_cligency_id == 10
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.client_manager_id
        assert not company.sales_person_id
        assert not company.bdr_person_id

        contact = await Contacts.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SALES

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_3(self, mock_gcal_builder):
        """
        Book a new meeting
        Company exists - match by cligency_id
        Contact exists - match by email
        """
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        company = await Companies.create(
            tc_cligency_id=10, name='Julies Ltd', website='https://junes.com', country='GB'
        )
        await Contacts.create(first_name='B', last_name='J', email='brain@junes.com', company_id=company.id)

        assert await Companies.all().count() == 1
        assert await Contacts.all().count() == 1

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert company.tc_cligency_id == 10
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.client_manager_id
        assert not company.bdr_person_id
        assert not company.sales_person_id

        contact = await Contacts.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'J'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SALES

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_4(self, mock_gcal_builder):
        """
        Book a new meeting
        Company exists - match by cligency_id
        Contact exists - match by last name
        No admins linked
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_client_manager=True,
            tc_admin_id=20,
        )
        company = await Companies.create(
            tc_cligency_id=10, name='Julies Ltd', website='https://junes.com', country='GB'
        )
        await Contacts.create(first_name='B', last_name='Junes', email='b@junes.com', company_id=company.id)

        assert await Companies.all().count() == 1
        assert await Contacts.all().count() == 1

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert company.tc_cligency_id == 10
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.client_manager_id
        assert not company.bdr_person_id
        assert not company.sales_person_id

        contact = await Contacts.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'Junes'
        assert contact.email == 'b@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SALES

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_5(self, mock_gcal_builder):
        """
        Book a new meeting
        Company exists - match by name
        Contact exists - match by last name
        No admins linked
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_client_manager=True,
            tc_admin_id=20,
        )
        company = await Companies.create(name='Junes Ltd', website='https://junes.com', country='GB')
        await Contacts.create(first_name='B', last_name='Junes', email='b@junes.com', company_id=company.id)

        assert await Companies.all().count() == 1
        assert await Contacts.all().count() == 1

        r = await self.client.post(self.url, json=CB_MEETING_DATA)
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert not company.tc_cligency_id
        assert company.name == 'Junes Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.client_manager_id
        assert not company.bdr_person_id

        contact = await Contacts.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'Junes'
        assert contact.email == 'b@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SALES

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_6(self, mock_gcal_builder):
        """
        Book a new meeting
        Company doens't exist but checking cligency_id
        Contact doesn't exist so create
        No admins linked
        """
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        company = await Companies.create(name='Julies Ltd', website='https://junes.com', country='GB')
        await Contacts.create(first_name='B', last_name='J', email='brain@junes.com', company_id=company.id)

        assert await Companies.all().count() == 1
        assert await Contacts.all().count() == 1

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert not company.tc_cligency_id
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.client_manager_id
        assert not company.bdr_person_id

        contact = await Contacts.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'J'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SALES

    async def test_meeting_already_exists(self):
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_client_manager=True,
            tc_admin_id=20,
        )
        company = await Companies.create(name='Junes Ltd', website='https://junes.com', country='GB')
        contact = await Contacts.create(first_name='B', last_name='Junes', email='b@junes.com', company_id=company.id)
        await Meetings.create(
            contact=contact,
            start_time=datetime(2026, 7, 3, 7, 30, tzinfo=utc),
            admin=sales_person,
            meeting_type=Meetings.TYPE_SUPPORT,
        )

        r = await self.client.post(self.url, json=CB_MEETING_DATA)
        assert r.status_code == 400
        assert r.json() == {'message': 'You already have a meeting booked around this time.', 'status': 'error'}

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_error_creating_gcal_event(self, mock_gcal_builder):
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        mock_gcal_builder.side_effect = fake_gcal_builder()
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        company = await Companies.create(name='Julies Ltd', website='https://junes.com', country='GB')
        await Contacts.create(first_name='B', last_name='J', email='brain@junes.com', company_id=company.id)

        assert await Companies.all().count() == 1
        assert await Contacts.all().count() == 1

        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert not company.tc_cligency_id
        assert company.name == 'Julies Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert not company.client_manager_id
        assert not company.bdr_person_id

        contact = await Contacts.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'J'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SALES

    async def test_admin_doesnt_exist(self):
        company = await Companies.create(name='Junes Ltd', website='https://junes.com', country='GB')
        await Contacts.create(first_name='B', last_name='Junes', email='b@junes.com', company_id=company.id)

        r = await self.client.post(self.url, json=CB_MEETING_DATA)
        assert r.status_code == 400
        assert r.json() == {'message': 'Admin does not exist.', 'status': 'error'}

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_admin_busy_start(self, mock_gcal_builder):
        """
        The admin is busy from 11 - 12.30. Try booking a meeting at that starts at 12.30 and ends at 1.
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = int(datetime(2026, 7, 3, 12, 30, tzinfo=utc).timestamp())

        await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0
        r = await self.client.post(self.url, json=meeting_data)
        assert r.json() == {'status': 'error', 'message': 'Admin is not free at this time.'}

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_admin_busy_during(self, mock_gcal_builder):
        """
        The admin is busy from 11 - 12.30. Try booking a meeting at that starts at 11.15 and ends at 11.45.
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = int(datetime(2026, 7, 3, 11, 15, tzinfo=utc).timestamp())

        await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 400
        assert r.json() == {'status': 'error', 'message': 'Admin is not free at this time.'}

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_admin_busy_end(self, mock_gcal_builder):
        """
        The admin is busy from 11 - 12.30. Try booking a meeting at that starts at 10.30 and ends at 11.
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = int(datetime(2026, 7, 3, 10, 45, tzinfo=utc).timestamp())

        await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 400
        assert r.json() == {'status': 'error', 'message': 'Admin is not free at this time.'}

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_support_call_book_create_contact(self, mock_gcal_builder):
        """
        Book a new SUPPORT meeting
        Company exists
        Contact doesn't exist so create
        Create with client manager
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        cli_man = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_client_manager=True,
            tc_admin_id=20,
        )
        await Companies.create(name='Julies Ltd', country='GB', tc_cligency_id=10)
        assert await Contacts.all().count() == 0
        r = await self.client.post('/callbooker/support/book/', json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert company.name == 'Julies Ltd'

        contact = await Contacts.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2026, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == cli_man
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SUPPORT


@mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
class AdminAvailabilityTestCase(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.url = '/callbooker/availability/'

    async def test_admin_slots_standard_simple_london(self, mock_gcal_builder):
        self.admin = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        mock_gcal_builder.side_effect = fake_gcal_builder()
        start = datetime(2026, 7, 2, 2, tzinfo=utc)
        end = datetime(2026, 7, 4, 23, tzinfo=utc)
        r = await self.client.post(
            self.url,
            json={'admin_id': self.admin.tc_admin_id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()},
        )
        slots = r.json()['slots']
        slots_2nd = [s for s in slots if s[0].startswith('2026-07-02')]
        slots_3rd = [s for s in slots if s[0].startswith('2026-07-03')]
        slots_4th = [s for s in slots if s[0].startswith('2026-07-04')]

        assert len(slots_2nd) == 10  # There should be 10 slots in the full day
        assert len(slots_3rd) == 7  # There is a busy section on the 3rd so less slots
        assert len(slots_4th) == 10  # There should be 10 slots in the full day

        assert slots_3rd == [
            ['2026-07-03T09:00:00+00:00', '2026-07-03T09:30:00+00:00'],
            ['2026-07-03T09:45:00+00:00', '2026-07-03T10:15:00+00:00'],
            ['2026-07-03T12:45:00+00:00', '2026-07-03T13:15:00+00:00'],
            ['2026-07-03T13:30:00+00:00', '2026-07-03T14:00:00+00:00'],
            ['2026-07-03T14:15:00+00:00', '2026-07-03T14:45:00+00:00'],
            ['2026-07-03T15:00:00+00:00', '2026-07-03T15:30:00+00:00'],
            ['2026-07-03T15:45:00+00:00', '2026-07-03T16:15:00+00:00'],
        ]

    async def test_admin_slots_toronto(self, mock_gcal_builder):
        """
        Testing when the admin is in the Toronto timezone
        """
        self.admin = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
            timezone='America/Toronto',
        )
        mock_gcal_builder.side_effect = fake_gcal_builder()
        start = datetime(2026, 7, 2, 2, tzinfo=utc)
        end = datetime(2026, 7, 4, 23, tzinfo=utc)
        r = await self.client.post(
            self.url,
            json={'admin_id': self.admin.tc_admin_id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()},
        )
        slots = r.json()['slots']
        slots_2nd = [s for s in slots if s[0].startswith('2026-07-02')]
        slots_3rd = [s for s in slots if s[0].startswith('2026-07-03')]
        slots_4th = [s for s in slots if s[0].startswith('2026-07-04')]

        assert len(slots_2nd) == 10  # There should be 10 slots in the full day
        assert len(slots_3rd) == 10  # Since the busy period is outside of the Admin's working hours, there are still 10
        assert len(slots_4th) == 10  # There should be 10 slots in the full day

        assert slots_3rd == [
            ['2026-07-03T14:00:00+00:00', '2026-07-03T14:30:00+00:00'],
            ['2026-07-03T14:45:00+00:00', '2026-07-03T15:15:00+00:00'],
            ['2026-07-03T15:30:00+00:00', '2026-07-03T16:00:00+00:00'],
            ['2026-07-03T16:15:00+00:00', '2026-07-03T16:45:00+00:00'],
            ['2026-07-03T17:00:00+00:00', '2026-07-03T17:30:00+00:00'],
            ['2026-07-03T17:45:00+00:00', '2026-07-03T18:15:00+00:00'],
            ['2026-07-03T18:30:00+00:00', '2026-07-03T19:00:00+00:00'],
            ['2026-07-03T19:15:00+00:00', '2026-07-03T19:45:00+00:00'],
            ['2026-07-03T20:00:00+00:00', '2026-07-03T20:30:00+00:00'],
            ['2026-07-03T20:45:00+00:00', '2026-07-03T21:15:00+00:00'],
        ]

    async def test_admin_slots_over_DST_change(self, mock_gcal_builder):
        """
        Testing when we're looking at the admin's slots over a DST change
        """
        """
        Testing when the admin is in the Toronto timezone
        """
        self.admin = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        mock_gcal_builder.side_effect = fake_gcal_builder()
        start = datetime(2026, 3, 28, 2, tzinfo=utc)
        end = datetime(2026, 3, 30, 23, tzinfo=utc)
        r = await self.client.post(
            self.url,
            json={'admin_id': self.admin.tc_admin_id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()},
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
        self.admin = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        mock_gcal_builder.side_effect = fake_gcal_builder()
        start = datetime(2026, 7, 3, 11, tzinfo=utc)
        end = datetime(2026, 7, 3, 12, tzinfo=utc)
        r = await self.client.post(
            self.url,
            json={'admin_id': self.admin.tc_admin_id, 'start_dt': start.timestamp(), 'end_dt': end.timestamp()},
        )
        assert r.json() == {'slots': [], 'status': 'ok'}
