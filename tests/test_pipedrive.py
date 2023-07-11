import re
from unittest import mock

from app.models import Companies, Contacts, Admins
from app.pipedrive.tasks import check_update_pipedrive
from tests._common import HermesTestCase


class FakePipedrive:
    def __init__(self):
        self.db = {'organizations': {}, 'persons': {}, 'deals': {}}


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
    async def test_create_org_create_person(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Companies.create(name='Julies Ltd', website='https://junes.com', country='GB')
        contact = await Contacts.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        await check_update_pipedrive(company, contact)
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

    @mock.patch('app.pipedrive.api.session.request')
    async def test_update_org_create_person(self, mock_request):
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
        await check_update_pipedrive(company, contact)
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

    @mock.patch('app.pipedrive.api.session.request')
    async def test_create_org_create_person_with_owner_admin(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        sales_person = await Admins.create(
            first_name='Steve',
            last_name='Jobs',
            email='climan@example.com',
            is_sales_person=True,
            tc_admin_id=20,
            pd_owner_id=99,
        )
        company = await Companies.create(
            name='Julies Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        contact = await Contacts.create(
            first_name='Brian',
            last_name='Junes',
            email='brain@junes.com',
            company_id=company.id,
        )
        await check_update_pipedrive(company, contact)
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
        await check_update_pipedrive(company, contact)
        call_args = mock_request.call_args_list
        assert not any('PUT' in str(call) for call in call_args)
