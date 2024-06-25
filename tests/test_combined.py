import copy
import hashlib
import hmac
import json
from unittest import mock

from app.base_schema import build_custom_field_schema
from app.models import Admin, Company, CustomField, CustomFieldValue
from app.pipedrive.tasks import pd_post_process_client_event
from app.utils import settings
from tests._common import HermesTestCase
from tests.test_callbooker import fake_gcal_builder
from tests.test_pipedrive import FakePipedrive, basic_pd_org_data, fake_pd_request
from tests.test_tc2 import FakeTC2, client_full_event_data, fake_tc2_request, mock_tc2_request


class TestMultipleServices(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.pipedrive = FakePipedrive()
        self.tc2 = FakeTC2()

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        kwargs = dict(
            tc2_machine_name='hermes_id',
            name='Hermes ID',
            hermes_field_name='id',
            field_type=CustomField.TYPE_FK_FIELD,
        )
        await CustomField.create(linked_object_type='Company', pd_field_id='123_hermes_id_456', **kwargs)
        await CustomField.create(linked_object_type='Contact', pd_field_id='234_hermes_id_567', **kwargs)
        await CustomField.create(linked_object_type='Deal', pd_field_id='345_hermes_id_678', **kwargs)
        await build_custom_field_schema()

    def _tc2_sig(self, payload):
        return hmac.new(settings.tc2_api_key.encode(), json.dumps(payload).encode(), hashlib.sha256).hexdigest()

    @mock.patch('app.tc2.api.session.request')
    @mock.patch('app.pipedrive.api.session.request')
    async def test_generate_support_link_company_doesnt_exist_get_from_tc(self, mock_pd_request, mock_tc2_get):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)
        mock_tc2_get.side_effect = mock_tc2_request()

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=10,
        )

        headers = {'Authorization': f'token {settings.tc2_api_key}'}
        r = await self.client.get(
            '/callbooker/support-link/generate/tc2/',
            params={'tc2_admin_id': admin.tc2_admin_id, 'tc2_cligency_id': 10},
            headers=headers,
        )
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.tc2_agency_id == 20
        assert company.tc2_cligency_id == 10

    @mock.patch('app.tc2.api.session.request')
    @mock.patch('app.pipedrive.api.session.request')
    async def test_create_company_with_tc_custom_field_empty(self, mock_pd_request, mock_tc2_get):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)
        mock_tc2_get.side_effect = mock_tc2_request()

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=10,
        )

        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_source_456',
            name='Source',
            field_type='str',
        )
        await build_custom_field_schema()

        assert not await Company.exists()
        pd_org_data = {
            'v': 1,
            'matches_filters': {'current': []},
            'meta': {'action': 'updated', 'object': 'organization'},
            'current': {
                'owner_id': 10,
                'id': 20,
                'name': 'Test company',
                'address_country': None,
                '123_source_456': None,
            },
            'previous': {},
            'event': 'updated.organization',
        }

        r = await self.client.post('/pipedrive/callback/', json=pd_org_data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.sales_person_id == admin.id
        assert not await CustomFieldValue.exists()

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.tc2.api.session.request')
    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_cb_company_exists_in_tc_and_pd_but_not_in_hermes(self, mock_pd_request, mock_tc2_get):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)
        mock_tc2_get.side_effect = mock_tc2_request()

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=10,
        )

        tc2_cligency_url = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_tc2_cligency_url_456',
            hermes_field_name='tc2_cligency_url',
            name='TC2 Cligency URL',
            field_type=CustomField.TYPE_STR,
        )
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_sales_person_456',
            hermes_field_name='sales_person',
            name='Sales Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        await build_custom_field_schema()

        assert not await Company.exists()

        # The lost org in pipedrive that needs to be updated
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'MyTutors',
                'address_country': 'GB',
                'owner_id': 99,
                '123_tc2_cligency_url_456': f'{settings.tc2_base_url}/clients/10/',
            }
        }

        # Create the company in TC2 send the webhook to Hermes
        modified_data = client_full_event_data()
        modified_data['subject']['meta_agency']['name'] = 'MyTutors2'

        events = [modified_data]
        data = {'_request_time': 123, 'events': events}
        r = await self.client.post('/tc2/callback/', json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        assert await Company.exists()
        company = await Company.get()

        assert company.tc2_cligency_url == f'{settings.tc2_base_url}/clients/10/'

        await pd_post_process_client_event(company=company)

        # Check the org has been updated
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'MyTutors2',
                'address_country': 'GB',
                'owner_id': 10,
                '123_hermes_id_456': company.id,
                '123_tc2_cligency_url_456': f'{settings.tc2_base_url}/clients/10/',
                '123_sales_person_456': admin.id,
            }
        }

        await tc2_cligency_url.delete()
        await build_custom_field_schema()

    @mock.patch('app.tc2.api.session.request')
    @mock.patch('app.pipedrive.api.session.request')
    async def test_pipedrive_cb_org_exists_no_hermes_id_match(self, mock_pd_request, mock_tc2_get):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)
        mock_tc2_get.side_effect = mock_tc2_request()

        await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=10,
        )

        # The lost org in pipedrive that needs to be updated
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'MyTutors',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': 999,
            }
        }
        assert not await Company.exists()

        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['previous'].update(id=1)
        data['current'].update(id=1, name='New test company')

        r = await self.client.post('/pipedrive/callback/', json=data)
        assert r.status_code == 200, r.json()

        assert await Company.exists()
        company = await Company.get()

        await pd_post_process_client_event(company=company)
        # Check the org has been updated
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'New test company',
                'address_country': None,
                'owner_id': 10,
                '123_hermes_id_456': company.id,
            }
        }

    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    @mock.patch('app.tc2.api.session.request')
    @mock.patch('app.pipedrive.api.session.request')
    async def test_callbooker_sales_call_full(self, _mock_pd_request, _mock_tc2_request, _mock_gcal_builder):
        _mock_pd_request.side_effect = fake_pd_request(self.pipedrive)
        _mock_tc2_request.side_effect = mock_tc2_request()
        _mock_gcal_builder.side_effect = fake_gcal_builder()
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_sales_person_456',
            hermes_field_name='sales_person',
            name='Sales Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_bdr_person_456',
            hermes_field_name='bdr_person_person',
            name='BDR Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_support_person_456',
            hermes_field_name='support_person',
            name='Support Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )
        await build_custom_field_schema()
        assert not await Company.exists()
        assert not self.pipedrive.db['organizations']

        sales_admin = await Admin.create(
            tc2_admin_id=100,
            first_name='Brain',
            last_name='Johnson',
            username='climan@example.com',
            pd_owner_id=10,
        )
        bdr_person = await Admin.create(
            tc2_admin_id=101,
            first_name='Jeremy',
            last_name='Irons',
            username='jeremy@tc.com',
            pd_owner_id=11,
        )

        r = await self.client.post(
            '/callbooker/sales/book/',
            json={
                'email': 'jules@example.com',
                'admin_id': sales_admin.id,
                'bdr_person_id': bdr_person.tc2_admin_id,
                'estimated_income': 100,
                'currency': 'GBP',
                'website': 'https://www.example.com',
                'country': 'GB',
                'name': 'Jules Holland',
                'company_name': 'MyTutors',
                'price_plan': 'payg',
                'meeting_dt': '2032-01-01 12:00',
            },
        )
        assert r.json() == {'status': 'ok'}
        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.bdr_person_id == bdr_person.id
        assert company.sales_person_id == sales_admin.id

    @mock.patch('app.tc2.api.session.request')
    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_cb_create_company_create_org_update_org(self, mock_pd_request, mock_tc2_get):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)
        mock_tc2_get.side_effect = fake_tc2_request(self.tc2)

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
        )

        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_sales_person_456',
            hermes_field_name='sales_person',
            name='Sales Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_bdr_person_456',
            hermes_field_name='bdr_person',
            name='BDR Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )
        await build_custom_field_schema()

        modified_data = client_full_event_data()
        modified_data['subject']['meta_agency']['name'] = 'MyTutors'
        modified_data['subject']['bdr_person'] = None
        events = [modified_data]

        data = {'_request_time': 123, 'events': events}
        r = await self.client.post('/tc2/callback/', json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        assert await Company.exists()
        company = await Company.get()
        assert company.name == 'MyTutors'
        assert not company.bdr_person
        assert await company.support_person == await company.sales_person == admin

        # check that pipedrive has the correct data
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'MyTutors',
                'address_country': 'GB',
                'owner_id': None,
                '123_hermes_id_456': company.id,
                '123_sales_person_456': admin.id,
                '123_bdr_person_456': None,
            }
        }

    @mock.patch('app.tc2.api.session.request')
    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_cb_create_company_cf_json(self, mock_pd_request, mock_tc2_get):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)
        mock_tc2_get.side_effect = fake_tc2_request(self.tc2)

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
        )

        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_sales_person_456',
            hermes_field_name='sales_person',
            name='Sales Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_bdr_person_456',
            hermes_field_name='bdr_person',
            name='BDR Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_signup_questionnaire_456',
            hermes_field_name='signup_questionnaire',
            name='Agency Questionnaire',
            field_type=CustomField.TYPE_STR,
        )
        await build_custom_field_schema()

        modified_data = client_full_event_data()
        modified_data['subject']['meta_agency']['name'] = 'MyTutors'
        modified_data['subject']['bdr_person'] = None
        modified_data['subject']['signup_questionnaire'] = {
            'question1': 'answer1',
            'question2': 'answer2',
        }
        events = [modified_data]

        data = {'_request_time': 123, 'events': events}
        r = await self.client.post('/tc2/callback/', json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        assert await Company.exists()
        company = await Company.get()
        assert company.name == 'MyTutors'
        assert not company.bdr_person
        assert await company.support_person == await company.sales_person == admin
        assert company.signup_questionnaire == {
            'question1': 'answer1',
            'question2': 'answer2',
        }

        # check that pipedrive has the correct data
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'MyTutors',
                'address_country': 'GB',
                'owner_id': None,
                '123_hermes_id_456': company.id,
                '123_sales_person_456': admin.id,
                '123_bdr_person_456': None,
                '123_signup_questionnaire_456': '{"question1": "answer1", "question2": "answer2"}',
            }
        }
