import re
from datetime import timezone, datetime, timedelta
from unittest import mock

from app.models import Companies, Contacts, Admins, Meetings, Deals, Pipelines
from app.pipedrive.tasks import post_sales_call, post_support_call
from tests._common import HermesTestCase


class FakePipedrive:
    def __init__(self):
        self.db = {'organizations': {}, 'persons': {}, 'deals': {}, 'activities': {}}


class MockResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self.json_data = json_data

    def json(self):
        return self.json_data

    def raise_for_status(self):
        return


def fake_pd_request(fake_pipedrive: FakePipedrive):
    def _pd_request(*, url: str, method: str, data: dict, headers: dict):
        obj_type = re.search(r'/api/(.*?)(?:/|$)', url).group(1)
        if method == 'GET':
            obj_id = int(url.split(f'/{obj_type}/')[1])
            return MockResponse(200, fake_pipedrive.db[obj_type][obj_id])
        elif method == 'POST':
            obj_id = len(fake_pipedrive.db[obj_type].keys()) + 1
            data['id'] = obj_id
            fake_pipedrive.db[obj_type][obj_id] = data
            return MockResponse(200, fake_pipedrive.db[obj_type][obj_id])
        else:
            assert method == 'PUT'
            obj_id = int(url.split(f'/{obj_type}/')[1])
            fake_pipedrive.db[obj_type][obj_id].update(**data)
            return MockResponse(200, fake_pipedrive.db[obj_type][obj_id])

    return _pd_request


class PipedriveTestCase(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.pipedrive = FakePipedrive()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_sales_call_booked(self, mock_request):
        """
        Test that the sales call flow creates the org, person, deal and activity in pipedrive. None of the objects
        already exist so should create one of each in PD.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        company = await Companies.create(name='Julies Ltd', website='https://junes.com', country='GB')
        contact = await Contacts.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        admin = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
            pd_owner_id=99,
        )
        meeting = await Meetings.create(
            company=company,
            contact=contact,
            meeting_type=Meetings.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        deal = await Deals.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            pipeline_stage=self.pipeline_stage,
            admin=admin,
        )
        await post_sales_call(company, contact, meeting, deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': None,
                'estimated_income': '',
                'status': 'pending_email_conf',
                'website': 'https://junes.com',
                'paid_invoice_count': 0,
                'has_booked_call': False,
                'has_signed_up': False,
                'tc_profile_url': '',
            },
        }
        assert (await Companies.get()).pd_org_id == 1
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': None,
                'email': 'brain@junes.com',
                'phone': None,
                'address_country': None,
                'org_id': 1,
            },
        }
        assert (await Contacts.get()).pd_person_id == 1
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': 1,
                'pipeline_id': (await Pipelines.get()).pd_pipeline_id,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
            }
        }
        assert (await Deals.get()).pd_deal_id == 1
        assert self.pipedrive.db['activities'] == {
            1: {
                'id': 1,
                'due_dt': '2023-01-01',
                'due_time': '00:00',
                'subject': 'Introductory call with Steve Jobs',
                'user_id': 99,
                'deal_id': 1,
                'person_id': 1,
                'org_id': 1,
            },
        }

    @mock.patch('app.pipedrive.api.session.request')
    async def test_support_call_booked_org_exists(self, mock_request):
        """
        Test that the support call workflow works. The company exists in Pipedrive so they should have an activity
        created for them.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        company = await Companies.create(name='Julies Ltd', website='https://junes.com', country='GB', pd_org_id=10)
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 10,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': None,
                'estimated_income': '',
                'status': 'pending_email_conf',
                'website': 'https://junes.com',
                'paid_invoice_count': 0,
                'has_booked_call': False,
                'has_signed_up': False,
                'tc_profile_url': '',
            },
        }
        contact = await Contacts.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        admin = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
            pd_owner_id=99,
        )
        meeting = await Meetings.create(
            company=company,
            contact=contact,
            meeting_type=Meetings.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        await post_support_call(contact, meeting)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 10,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': None,
                'estimated_income': '',
                'status': 'pending_email_conf',
                'website': 'https://junes.com',
                'paid_invoice_count': 0,
                'has_booked_call': False,
                'has_signed_up': False,
                'tc_profile_url': '',
            },
        }
        assert (await Companies.get()).pd_org_id == 10
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': None,
                'email': 'brain@junes.com',
                'phone': None,
                'address_country': None,
                'org_id': 10,
            },
        }
        assert (await Contacts.get()).pd_person_id == 1
        assert self.pipedrive.db['deals'] == {}
        assert not await Deals.exists()
        assert self.pipedrive.db['activities'] == {
            1: {
                'due_dt': '2023-01-01',
                'due_time': '00:00',
                'subject': 'Introductory call with Steve Jobs',
                'user_id': 99,
                'deal_id': None,
                'person_id': 1,
                'org_id': 10,
                'id': 1,
            },
        }

    @mock.patch('app.pipedrive.api.session.request')
    async def test_support_call_booked_no_org(self, mock_request):
        """
        Test that the support call workflow works. The company doesn't exist in Pipedrive so no activity created
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        company = await Companies.create(name='Julies Ltd', website='https://junes.com', country='GB')
        contact = await Contacts.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        admin = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
            pd_owner_id=99,
        )
        meeting = await Meetings.create(
            company=company,
            contact=contact,
            meeting_type=Meetings.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        await post_support_call(contact, meeting)
        assert self.pipedrive.db['organizations'] == {}
        assert self.pipedrive.db['persons'] == {}
        assert self.pipedrive.db['deals'] == {}
        assert not await Deals.exists()
        assert self.pipedrive.db['activities'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_update_org_create_person_deal_exists(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Companies.create(name='Julies Ltd', website='https://junes.com', country='GB', pd_org_id=1)
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'Junes Ltd',
                'address_country': 'GB',
                'owner_id': None,
                'estimated_income': '',
                'status': 'pending_email_conf',
                'website': 'https://junes.com',
                'paid_invoice_count': 0,
                'has_booked_call': False,
                'has_signed_up': False,
                'tc_profile_url': '',
            },
        }
        contact = await Contacts.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        admin = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
            pd_owner_id=99,
        )
        meeting = await Meetings.create(
            company=company,
            contact=contact,
            meeting_type=Meetings.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        deal = await Deals.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            pipeline_stage=self.pipeline_stage,
            admin=admin,
            pd_deal_id=17,
        )
        await post_sales_call(company=company, contact=contact, meeting=meeting, deal=deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': None,
                'estimated_income': '',
                'status': 'pending_email_conf',
                'website': 'https://junes.com',
                'paid_invoice_count': 0,
                'has_booked_call': False,
                'has_signed_up': False,
                'tc_profile_url': '',
            },
        }
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': None,
                'email': 'brain@junes.com',
                'phone': None,
                'address_country': None,
                'org_id': 1,
            },
        }
        assert self.pipedrive.db['deals'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_create_org_create_person_with_owner_admin(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
            pd_owner_id=99,
        )
        company = await Companies.create(
            name='Julies Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        contact = await Contacts.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meetings.create(
            company=company,
            contact=contact,
            meeting_type=Meetings.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=sales_person,
        )
        deal = await Deals.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            pipeline_stage=self.pipeline_stage,
            admin=sales_person,
            pd_deal_id=17,
        )
        await post_sales_call(company=company, contact=contact, meeting=meeting, deal=deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                'estimated_income': '',
                'status': 'pending_email_conf',
                'website': 'https://junes.com',
                'paid_invoice_count': 0,
                'has_booked_call': False,
                'has_signed_up': False,
                'tc_profile_url': '',
            },
        }
        assert (await Companies.get()).pd_org_id == 1
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': 'brain@junes.com',
                'phone': None,
                'address_country': None,
                'org_id': 1,
            },
        }
        assert (await Contacts.get()).pd_person_id == 1

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_person_dont_need_update(self, mock_request):
        """
        This is basically testing that if the data in PD and the DB are up to date, we don't do the update request
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Companies.create(name='Julies Ltd', website='https://junes.com', country='GB', pd_org_id=1)
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': None,
                'estimated_income': '',
                'status': 'pending_email_conf',
                'website': 'https://junes.com',
                'paid_invoice_count': 0,
                'has_booked_call': False,
                'has_signed_up': False,
                'tc_profile_url': '',
            },
        }
        contact = await Contacts.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id, pd_person_id=1
        )
        self.pipedrive.db['persons'] = {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': None,
                'email': 'brain@junes.com',
                'phone': None,
                'address_country': None,
                'org_id': 1,
            },
        }
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        admin = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
            pd_owner_id=99,
        )
        meeting = await Meetings.create(
            company=company,
            contact=contact,
            meeting_type=Meetings.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        deal = await Deals.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            pipeline_stage=self.pipeline_stage,
            admin=admin,
            pd_deal_id=17,
        )
        await post_sales_call(company, contact, meeting, deal)
        call_args = mock_request.call_args_list
        assert not any('PUT' in str(call) for call in call_args)
