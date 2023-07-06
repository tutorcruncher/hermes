from datetime import datetime
from unittest import mock

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
    'client_manager': 20,
    'meeting_dt': int(datetime(2023, 7, 3, 9, tzinfo=utc).timestamp()),
}


def _as_iso_8601(dt: datetime):
    return dt.isoformat().replace('+00:00', 'Z')


class MockGCalResource:
    def execute(self):
        return {
            'calendars': {
                'climan@example.com': {
                    'busy': [
                        {
                            'start': _as_iso_8601(datetime(2023, 7, 3, 11, tzinfo=utc)),
                            'end': _as_iso_8601(datetime(2023, 7, 3, 12, 30, tzinfo=utc)),
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


class MeetingBookingTestCase(HermesTestCase):
    """
    A TestCase for testing when a company and contact need to be created when creating a meeting, and for testing when
    the admin is free for the meeting.
    """

    def setUp(self):
        super().setUp()
        self.url = '/callback/callbooker/'

    async def test_no_admin(self):
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data.pop('client_manager')
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 422
        assert r.json() == {
            'detail': [
                {
                    'loc': ['body', 'sales_person'],
                    'msg': 'Either sales_person or client_manager must be provided',
                    'type': 'value_error',
                }
            ]
        }

    async def test_two_admins(self):
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['sales_person'] = 21
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 422
        assert r.json() == {
            'detail': [
                {
                    'loc': ['body', 'sales_person'],
                    'msg': 'Only one of sales_person or client_manager must be provided',
                    'type': 'value_error',
                }
            ]
        }

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_1(self, mock_gcal_builder):
        """
        Book a new meeting
        Company doesn't exist so create
        Contact doesn't exist so create
        Create with client manager
        """
        mock_gcal_builder.side_effect = MockGCalResource
        cli_man = await Admins.create(
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
        assert not company.sales_person_id
        assert not company.bdr_person_id
        assert await company.client_manager == cli_man

        contact = await Contacts.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2023, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == cli_man
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SUPPORT

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_2(self, mock_gcal_builder):
        """
        Book a new meeting
        Company exists - match by cligency_id
        Contact doesn't exist so create
        No admins linked
        """
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        mock_gcal_builder.side_effect = MockGCalResource
        cli_man = await Admins.create(
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
        assert not company.sales_person_id
        assert not company.bdr_person_id
        assert not company.client_manager_id

        contact = await Contacts.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2023, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == cli_man
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SUPPORT

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_3(self, mock_gcal_builder):
        """
        Book a new meeting
        Company exists - match by cligency_id
        Contact exists - match by email
        No admins linked
        """
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        meeting_data.pop('client_manager')
        meeting_data['sales_person'] = 20
        mock_gcal_builder.side_effect = MockGCalResource
        cli_man = await Admins.create(
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
        assert not company.sales_person_id
        assert not company.bdr_person_id
        assert not company.client_manager_id

        contact = await Contacts.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'J'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2023, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == cli_man
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
        mock_gcal_builder.side_effect = MockGCalResource
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        cli_man = await Admins.create(
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
        assert not company.sales_person_id
        assert not company.bdr_person_id
        assert not company.client_manager_id

        contact = await Contacts.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'Junes'
        assert contact.email == 'b@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2023, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == cli_man
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SUPPORT

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_5(self, mock_gcal_builder):
        """
        Book a new meeting
        Company exists - match by name
        Contact exists - match by last name
        No admins linked
        """
        mock_gcal_builder.side_effect = MockGCalResource
        cli_man = await Admins.create(
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
        assert not company.sales_person_id
        assert not company.bdr_person_id
        assert not company.client_manager_id

        contact = await Contacts.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'Junes'
        assert contact.email == 'b@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2023, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == cli_man
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SUPPORT

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_6(self, mock_gcal_builder):
        """
        Book a new meeting
        Company doesn't exist so create
        Contact doesn't exist so create
        Create with Sales person
        """
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data.pop('client_manager')
        meeting_data['sales_person'] = 20
        mock_gcal_builder.side_effect = MockGCalResource
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
        )
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0
        r = await self.client.post(self.url, json=meeting_data)
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert not company.tc_cligency_id
        assert company.name == 'Junes Ltd'
        assert company.website == 'https://junes.com'
        assert company.country == 'GB'
        assert company.estimated_income == '1000'
        assert not company.client_manager
        assert not company.bdr_person_id
        assert await company.sales_person == sales_person

        contact = await Contacts.get()
        assert contact.first_name == 'Brain'
        assert contact.last_name == 'Junes'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2023, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == sales_person
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SALES

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_7(self, mock_gcal_builder):
        """
        Book a new meeting
        Company doens't exist but checking cligency_id
        Contact doesn't exist so create
        No admins linked
        """
        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['tc_cligency_id'] = 10
        mock_gcal_builder.side_effect = MockGCalResource
        cli_man = await Admins.create(
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
        assert not company.sales_person_id
        assert not company.bdr_person_id
        assert not company.client_manager_id

        contact = await Contacts.get()
        assert contact.first_name == 'B'
        assert contact.last_name == 'J'
        assert contact.email == 'brain@junes.com'
        assert contact.company_id == company.id

        meeting = await Meetings.get()
        assert meeting.status == Meetings.STATUS_PLANNED
        assert meeting.start_time == datetime(2023, 7, 3, 9, tzinfo=utc)
        assert await meeting.admin == cli_man
        assert await meeting.contact == contact
        assert meeting.meeting_type == Meetings.TYPE_SALES

    async def test_meeting_already_exists(self):
        cli_man = await Admins.create(
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
            start_time=datetime(2023, 7, 3, 7, 30, tzinfo=utc),
            admin=cli_man,
            meeting_type=Meetings.TYPE_SUPPORT,
        )

        r = await self.client.post(self.url, json=CB_MEETING_DATA)
        assert r.status_code == 400
        assert r.json() == {'message': 'You already have a meeting booked around this time.', 'status': 'error'}

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
        mock_gcal_builder.side_effect = MockGCalResource

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = int(datetime(2023, 7, 3, 12, 30, tzinfo=utc).timestamp())

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
    async def test_admin_busy_during(self, mock_gcal_builder):
        """
        The admin is busy from 11 - 12.30. Try booking a meeting at that starts at 11.15 and ends at 11.45.
        """
        mock_gcal_builder.side_effect = MockGCalResource

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = int(datetime(2023, 7, 3, 11, 15, tzinfo=utc).timestamp())

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
        mock_gcal_builder.side_effect = MockGCalResource

        meeting_data = CB_MEETING_DATA.copy()
        meeting_data['meeting_dt'] = int(datetime(2023, 7, 3, 10, 45, tzinfo=utc).timestamp())

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
