import hashlib
import hmac
import json
from unittest import mock

from app.base_schema import build_custom_field_schema
from app.models import Admin, Company, CustomField, CustomFieldValue, Contact, Deal
from app.pipedrive.tasks import pd_post_process_client_event
from app.utils import settings
from tests._common import HermesTestCase
from tests.test_pipedrive import fake_pd_request, FakePipedrive
from tests.test_tc2 import mock_tc2_request, client_full_event_data


class TestMultipleServices(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.pipedrive = FakePipedrive()

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
    async def test_company_winback_1(self, mock_pd_request, mock_tc2_get):
        """
        Test Winback Case 1
        Client exists in TC2
        Org exists in Pipedrive
        Company does not exist in Hermes
        Person exists in Pipedrive
        Contact does not exist in Hermes
        Deal exists in Pipedrive
        Deal does not exist in Hermes
        """
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

        tc2_cligency_url = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_tc2_cligency_url_456',
            hermes_field_name='tc2_cligency_url',
            name='TC2 Cligency URL',
            field_type='str',
        )

        await build_custom_field_schema()

        assert not await Company.exists()
        assert not await Contact.exists()
        assert not await Deal.exists()

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
        # the lost person in pipedrive that needs to be updated
        self.pipedrive.db['persons'] = {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': 1,
            },
        }

        # The lost deal in pipedrive that needs to be updated
        self.pipedrive.db['deals'] = {
            1: {
                'id': 1,
                'title': 'MyTutors',
                'org_id': 1,
                'person_id': 2,
                '345_hermes_id_678': 1,
            }
        }
        debug(self.pipedrive.db['deals'])

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
        debug(self.pipedrive.db['deals'])

        await pd_post_process_client_event(company=company)

        # Check the org has been updated
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'MyTutors2',
                'address_country': 'GB',
                'owner_id': 10,
                '123_hermes_id_456': 1,
                '123_tc2_cligency_url_456': f'{settings.tc2_base_url}/clients/10/',
            }
        }

        # check the person has been updated
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Mary Booth',
                'owner_id': 10,
                'email': ['mary@booth.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': 1,
            },
        }

        debug(self.pipedrive.db['deals'])

        # Check the deal has been updated
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'MyTutors2',
                'org_id': 1,
                'person_id': 1,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                'user_id': 10,
                '345_hermes_id_678': 1,
            }
        }

        await tc2_cligency_url.delete()
        await build_custom_field_schema()

    @mock.patch('app.tc2.api.session.request')
    @mock.patch('app.pipedrive.api.session.request')
    async def test_company_winback_2(self, mock_pd_request, mock_tc2_get):
        """
        Test Winback Case 2
        Client exists in TC2
        Org exists in Pipedrive
        Company does not exist in Hermes
        Person does not exist in Pipedrive
        Contact does not exist in Hermes
        Deal does not exist in Pipedrive
        Deal does not exist in Hermes
        """
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)
        mock_tc2_get.side_effect = mock_tc2_request()

