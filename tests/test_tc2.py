import copy
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta
from unittest import mock

from requests import HTTPError

from app.base_schema import build_custom_field_schema
from app.models import Admin, Company, Contact, CustomField, CustomFieldValue, Deal
from app.tc2.tasks import update_client_from_company
from app.utils import settings
from tests._common import HermesTestCase


def _client_data():
    return {
        'id': 10,
        'model': 'Client',
        'meta_agency': {
            'id': 20,
            'name': 'MyTutors',
            'website': 'www.example.com',
            'status': 'active',
            'paid_invoice_count': 2,
            'country': 'United Kingdom (GB)',
            'price_plan': '1-payg',
            'narc': False,
            'created': int((datetime.now() - timedelta(days=1)).timestamp()),
        },
        'associated_admin': {
            'id': 30,
            'first_name': 'Brain',
            'last_name': 'Johnson',
            'email': 'brian@tc.com',
        },
        'sales_person': {
            'id': 30,
            'first_name': 'Brain',
            'last_name': 'Johnson',
            'email': 'brian@tc.com',
        },
        'bdr_person': {
            'id': 30,
            'first_name': 'Brain',
            'last_name': 'Johnson',
            'email': 'brian@tc.com',
        },
        'paid_recipients': [
            {
                'id': 40,
                'first_name': 'Mary',
                'last_name': 'Booth',
                'email': 'mary@booth.com',
            }
        ],
        'status': 'live',
        'extra_attrs': [
            {'machine_name': 'pipedrive_url', 'value': 'https://example.pipedrive.com/organization/10'},
            {'machine_name': 'how_did_you_hear_about_us_1', 'value': '----'},
            {'machine_name': 'who_are_you_trying_to_reach', 'value': ' Support'},
        ],
        'user': {
            'email': 'mary@booth.com',
            'first_name': 'Mary',
            'last_name': 'Booth',
        },
    }


def client_full_event_data():
    return {
        'action': 'create',
        'verb': 'create',
        'subject': _client_data(),
    }


def client_deleted_event_data():
    return {
        'action': 'DELETED_A_CLIENT',
        'verb': 'delete',
        'subject': {
            'id': 10,
            'model': 'Client',
            'first_name': 'Harry',
            'last_name': 'Poster',
        },
    }


def invoice_event_data():
    return {
        'action': 'send invoice',
        'verb': 'send invoice',
        'subject': {
            'id': 50,
            'model': 'Invoice',
            'client': {
                'id': 10,
                'first_name': 'Mary',
                'last_name': 'Booth',
                'email': 'mary@booth.com',
            },
        },
    }


def mock_tc2_request(error=False):
    class MockResponse:
        def __init__(self, *args, **kwargs):
            self.status_code = 200

        def json(self):
            return _client_data()

        def raise_for_status(self):
            if error:
                raise HTTPError('Error')

    return MockResponse


class TC2CallbackTestCase(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.url = '/tc2/callback/'

    def _tc2_sig(self, payload):
        return hmac.new(settings.tc2_api_key.encode(), json.dumps(payload).encode(), hashlib.sha256).hexdigest()

    async def test_callback_invalid_api_key(self):
        r = await self.client.post(
            self.url, headers={'Webhook-Signature': 'Foobar'}, json={'_request_time': 123, 'events': []}
        )
        assert r.status_code == 403, r.json()

    async def test_callback_missing_api_key(self):
        r = await self.client.post(self.url, json={'_request_time': 123, 'events': []})
        assert r.status_code == 403, r.json()

    async def test_cb_client_event_invalid_data(self):
        """
        Create a new company
        Create new contacts
        With associated admin that doesn't exist
        """
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        data = {'_request_time': 123, 'events': {'foo': 'bar'}}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 422, r.json()

    async def test_ingnored_actions_no_meta_agency(self):
        """
        try to create a company with no meta_agency
        """
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        event_data = {
            'action': 'AGREE_TERMS',
            'verb': 'Agreed to Terms and Conditions',
            'subject': {
                'charge_via_branch': False,
                'id': 1234,
                'invoices_count': 0,
                'is_taxable': True,
                'model': 'Client',
                'payment_pending': '0.00',
                'received_notifications': [],
                'status': 'prospect',
                'url': 'https://secure.tutorcruncher.com/api/clients/1234/',
                'user': {
                    'country': 'None',
                    'email': "'test@email.com'",
                    'first_name': "'Test'",
                    'last_name': "'User'",
                    'mobile': 'None',
                    'phone': "'+123456789'",
                    'state': 'None',
                    'street': 'None',
                    'title': 'None',
                    'town': 'None',
                },
            },
        }

        events = [event_data]
        data = {'_request_time': 123, 'events': events}

        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        event_data['action'] = 'CLIENT_ENQUIRY'
        event_data['verb'] = 'Client Enquiry'
        events = [event_data]
        data = {'_request_time': 123, 'events': events}

        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_ignore_agree_terms(self, mock_add_task):
        """
        Ignore AGREE_TERMS event
        """
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0

        await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )

        modified_data = client_full_event_data()
        modified_data['action'] = 'AGREE_TERMS'

        events = [modified_data]
        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        assert await Deal.all().count() == 0

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_cb_client_event_test_1(self, mock_add_task):
        """
        Create a new company
        Create no contacts
        With associated admin
        Create a deal
        """
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0

        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )

        modified_data = client_full_event_data()
        modified_data['subject']['paid_recipients'] = []
        modified_data['subject']['meta_agency']['status'] = 'trial'
        modified_data['subject']['meta_agency']['paid_invoice_count'] = 0

        events = [modified_data]
        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.tc2_agency_id == 20
        assert company.tc2_cligency_id == 10
        assert company.tc2_status == 'trial'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 0
        assert await company.bdr_person == await company.support_person == await company.sales_person == admin
        assert company.has_signed_up
        assert company.sales_call_count == 0

        assert not company.estimated_income

        assert await Contact.all().count() == 0
        deal = await Deal.get()
        assert deal.name == 'MyTutors'
        assert await deal.pipeline == self.pipeline
        assert not deal.contact
        assert await deal.stage == self.stage

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_cb_client_event_test_2(self, mock_add_task):
        """
        Create a new company
        Create new contacts
        With associated admin that doesn't exist
        """
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        events = [client_full_event_data()]
        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 422
        assert r.json() == {
            'detail': [
                {
                    'loc': ['sales_person_id'],
                    'msg': 'Admin with tc2_admin_id 30 does not exist',
                    'type': 'value_error',
                }
            ]
        }

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_cb_client_event_test_3(self, mock_add_task):
        """
        Update a current company
        Create no contacts
        Setting associated admin to None
        """
        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )
        await Company.create(
            tc2_agency_id=20,
            tc2_cligency_id=10,
            name='OurTutors',
            status='inactive',
            support_person=admin,
            country='GB',
            sales_person=admin,
        )
        assert await Contact.all().count() == 0

        modified_data = client_full_event_data()
        modified_data['subject']['associated_admin'] = None
        modified_data['subject']['paid_recipients'] = []

        events = [modified_data]
        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.tc2_agency_id == 20
        assert company.tc2_cligency_id == 10
        assert company.tc2_status == 'active'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 2
        assert await company.bdr_person == await company.sales_person == admin
        assert company.has_signed_up
        assert company.sales_call_count == 0
        assert not await company.support_person

        assert not company.estimated_income

        assert await Contact.all().count() == 0

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_cb_client_event_test_4(self, mock_add_task):
        """
        Update a current company
        Create new contacts & Update contacts
        """
        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )
        company = await Company.create(
            tc2_agency_id=20, tc2_cligency_id=10, name='OurTutors', status='inactive', country='GB', sales_person=admin
        )
        contact_a = await Contact.create(
            first_name='Jim', last_name='Snail', email='mary@booth.com', tc2_sr_id=40, company=company
        )
        modified_data = copy.deepcopy(client_full_event_data())
        modified_data['subject']['paid_recipients'].append(
            {'first_name': 'Rudy', 'last_name': 'Jones', 'email': 'rudy@jones.com', 'id': '41'}
        )
        modified_data['subject']['associated_admin'] = None
        events = [modified_data]
        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.tc2_agency_id == 20
        assert company.tc2_cligency_id == 10
        assert company.tc2_status == 'active'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 2
        assert company.has_signed_up
        assert company.sales_call_count == 0
        assert not await company.support_person

        assert await company.bdr_person == await company.sales_person == admin
        assert not company.estimated_income

        assert await Contact.all().count() == 2
        contact_a = await Contact.get(id=contact_a.id)
        assert contact_a.tc2_sr_id == 40
        assert contact_a.first_name == 'Mary'
        assert contact_a.last_name == 'Booth'

        contact_b = await Contact.exclude(id=contact_a.id).get()
        assert contact_b.tc2_sr_id == 41
        assert contact_b.first_name == 'Rudy'
        assert contact_b.last_name == 'Jones'

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_cb_client_event_with_custom_fields(self, mock_add_task):
        """
        Create a new company with custom field values
        """
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0

        source_field = await CustomField.create(
            name='Source',
            field_type=CustomField.TYPE_STR,
            tc2_machine_name='source_campaign',
            linked_object_type='Company',
        )
        income_field = await CustomField.create(
            name='Estimated income',
            field_type=CustomField.TYPE_STR,
            tc2_machine_name='income',
            linked_object_type='Company',
            hermes_field_name='estimated_income',
        )
        await build_custom_field_schema()

        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )

        modified_data = client_full_event_data()
        modified_data['subject']['extra_attrs'] += [
            {'machine_name': 'source_campaign', 'value': 'Google'},
            {'machine_name': 'income', 'value': '10000'},
        ]
        modified_data['subject']['paid_recipients'] = []
        modified_data['subject']['meta_agency']['status'] = 'trial'
        modified_data['subject']['meta_agency']['paid_invoice_count'] = 0

        events = [modified_data]
        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.tc2_agency_id == 20
        assert company.tc2_cligency_id == 10
        assert company.tc2_status == 'trial'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 0
        assert await company.bdr_person == await company.support_person == await company.sales_person == admin

        assert company.estimated_income == '10000'

        assert await Contact.all().count() == 0
        deal = await Deal.get()
        assert deal.name == 'MyTutors'
        assert await deal.pipeline == self.pipeline
        assert not deal.contact
        assert await deal.stage == self.stage

        cf_value = await CustomFieldValue.get()
        assert cf_value.value == 'google'

        await source_field.delete()
        await income_field.delete()
        await build_custom_field_schema()

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_create_company_narc(self, mock_add_task):
        """
        Create a new company
        Dont create contacts
        Dont create deal
        With associated admin
        """

        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        assert await Deal.all().count() == 0
        modified_data = client_full_event_data()
        modified_data['subject']['meta_agency']['narc'] = True
        events = [modified_data]

        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.tc2_agency_id == 20
        assert company.tc2_cligency_id == 10
        assert company.tc2_status == 'active'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 2
        assert await company.support_person == await company.sales_person == admin

        assert await Contact.all().count() == 0
        assert await Deal.all().count() == 0

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_create_company_no_narc(self, mock_add_task):
        """
        Create a new company
        Dont create contacts
        Dont create deal
        With associated admin
        """

        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        assert await Deal.all().count() == 0
        modified_data = client_full_event_data()
        modified_data['subject']['meta_agency'].pop('narc')
        events = [modified_data]

        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.tc2_agency_id == 20
        assert company.tc2_cligency_id == 10
        assert company.tc2_status == 'active'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 2
        assert await company.support_person == await company.sales_person == admin

        assert await Contact.all().count() == 1
        assert await Deal.all().count() == 0

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_create_company_no_user_email(self, mock_add_task):
        """
        Create a new company with no user email, sets the user email to that of the first paid receipient
        Create new contacts
        With associated admin
        """

        await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        modified_data = client_full_event_data()
        modified_data['subject']['user']['email'] = None
        events = [modified_data]

        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()  # Expecting a successful response

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_create_company_no_sales_person(self, mock_add_task):
        """
        Company with no sales person, to raise clear Error
        """

        await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        assert await Deal.all().count() == 0
        modified_data = client_full_event_data()
        modified_data['subject']['sales_person'] = None
        events = [modified_data]

        data = {'_request_time': 123, 'events': events}
        with self.assertRaises(TypeError):
            await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})

    async def test_cb_client_deleted_no_linked_data(self):
        """
        Company deleted, has no contacts
        """
        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )
        await Company.create(
            tc2_agency_id=20, tc2_cligency_id=10, name='OurTutors', status='inactive', country='GB', sales_person=admin
        )
        data = {'_request_time': 123, 'events': [client_deleted_event_data()]}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()
        assert await Company.all().count() == 0

    async def test_cb_client_deleted_test_has_linked_data(self):
        """
        Company deleted, has contact
        """
        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )
        company = await Company.create(
            tc2_agency_id=20, tc2_cligency_id=10, name='OurTutors', status='inactive', country='GB', sales_person=admin
        )
        await Contact.create(first_name='Jim', last_name='Snail', email='mary@booth.com', tc2_sr_id=40, company=company)
        data = {'_request_time': 123, 'events': [client_deleted_event_data()]}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0

    async def test_cb_client_deleted_doesnt_exist(self):
        """
        Company deleted, has no contacts
        """
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        data = {'_request_time': 123, 'events': [client_deleted_event_data()]}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0

    @mock.patch('app.tc2.api.session.request')
    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_cb_invoice_event_update_client(self, mock_add_task, mock_tc2_get):
        """
        Processing an invoice event means we get the client from TC.
        """
        mock_tc2_get.side_effect = mock_tc2_request()

        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        data = {'_request_time': 123, 'events': [invoice_event_data()]}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.tc2_agency_id == 20
        assert company.tc2_cligency_id == 10
        assert company.tc2_status == 'active'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 2
        assert await company.bdr_person == await company.support_person == await company.sales_person == admin

        assert not company.estimated_income

        contact = await Contact.get()
        assert contact.tc2_sr_id == 40
        assert contact.first_name == 'Mary'
        assert contact.last_name == 'Booth'

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_cb_client_event_invalid_price_plan(self, mock_add_task):
        """
        Create a new company
        Create no contacts
        With associated admin
        Create a deal
        """
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0

        admin = await Admin.create(
            tc2_admin_id=30, first_name='Brain', last_name='Johnson', username='brian@tc.com', password='foo'
        )

        modified_data = client_full_event_data()
        modified_data['subject']['meta_agency']['price_plan'] = '1-basic'

        events = [modified_data]
        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.url, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        company = await Company.get()
        assert company.name == 'MyTutors'
        assert company.price_plan == Company.PP_PAYG
        assert await company.support_person == await company.sales_person == admin


class FakeTC2:
    def __init__(self):
        self.db = {'clients': {10: _client_data()}}


class MockResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self.json_data = json_data

    def json(self):
        return self.json_data

    def raise_for_status(self):
        return


def fake_tc2_request(fake_tc2: FakeTC2):
    def _tc2_request(*, url: str, method: str, json: dict, headers: dict):
        data = json
        obj_type = re.search(r'/api/(.*?)(?:/|$)', url).group(1)
        if method == 'GET':
            obj_id = int(url.split(f'/{obj_type}/')[1].rstrip('/'))
            return MockResponse(200, fake_tc2.db[obj_type][obj_id])
        else:
            assert method == 'POST'
            obj_id = next(
                id
                for id, obj_data in fake_tc2.db[obj_type].items()
                if obj_data['user']['email'] == data['user']['email']
            )

            admin_keys = ['sales_person', 'associated_admin', 'bdr_person']

            for key in admin_keys:
                data[key] = (
                    fake_tc2.db[obj_type][obj_id][key]
                    if data.get(key) == fake_tc2.db[obj_type][obj_id][key]['id']
                    else None
                )

            fake_tc2.db[obj_type][obj_id] = data
            return MockResponse(200, fake_tc2.db[obj_type][obj_id])

    return _tc2_request


class TC2TasksTestCase(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.tc2 = FakeTC2()

    @mock.patch('app.tc2.api.session.request')
    async def test_update_deal_no_cligency_id(self, mock_request):
        mock_request.side_effect = fake_tc2_request(self.tc2)
        admin = await Admin.create(pd_owner_id=10, username='testing@example.com', is_sales_person=True)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        await Deal.create(
            name='Old test deal',
            pd_deal_id=40,
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )
        await update_client_from_company(company)
        assert self.tc2.db['clients'] == {10: _client_data()}

    @mock.patch('app.tc2.api.session.request')
    async def test_update_cligency(self, mock_request):
        mock_request.side_effect = fake_tc2_request(self.tc2)
        admin = await Admin.create(
            pd_owner_id=10, username='testing@example.com', is_sales_person=True, tc2_admin_id=30
        )
        company = await Company.create(
            name='Test company',
            pd_org_id=20,
            tc2_cligency_id=10,
            sales_person=admin,
            price_plan=Company.PP_PAYG,
            bdr_person=admin,
        )
        await update_client_from_company(company)
        assert self.tc2.db['clients'] == {
            10: {
                'user': {
                    'email': 'mary@booth.com',
                    'phone': None,
                    'first_name': 'Mary',
                    'last_name': 'Booth',
                },
                'status': 'live',
                'sales_person': {
                    'id': 30,
                    'first_name': 'Brain',
                    'last_name': 'Johnson',
                    'email': 'brian@tc.com',
                },
                'associated_admin': None,
                'bdr_person': {
                    'id': 30,
                    'first_name': 'Brain',
                    'last_name': 'Johnson',
                    'email': 'brian@tc.com',
                },
                'paid_recipients': [
                    {
                        'email': 'mary@booth.com',
                        'first_name': 'Mary',
                        'last_name': 'Booth',
                    },
                ],
                'extra_attrs': {
                    'pipedrive_url': f'{settings.pd_base_url}/organization/20/',
                    'who_are_you_trying_to_reach': 'support',
                },
            }
        }

    @mock.patch('app.tc2.api.session.request')
    async def test_update_cligency_termination(self, mock_request):
        fake_tc2 = FakeTC2()
        fake_tc2.db['clients'][10]['extra_attrs'] += [
            {'machine_name': 'termination_category', 'value': "Doesn't suit business model"},
        ]
        mock_request.side_effect = fake_tc2_request(fake_tc2)
        admin = await Admin.create(pd_owner_id=10, username='testing@example.com', is_sales_person=True)
        company = await Company.create(
            name='Test company', pd_org_id=20, tc2_cligency_id=10, sales_person=admin, price_plan=Company.PP_PAYG
        )
        await update_client_from_company(company)
        assert fake_tc2.db['clients'][10]['extra_attrs'] == {
            'pipedrive_url': f'{settings.pd_base_url}/organization/20/',
            'who_are_you_trying_to_reach': 'support',
            'termination_category': 'doesnt-suit-business-model',
        }

    @mock.patch('app.tc2.api.session.request')
    async def test_update_cligency_with_deal(self, mock_request):
        mock_request.side_effect = fake_tc2_request(self.tc2)
        admin = await Admin.create(
            pd_owner_id=10, username='testing@example.com', is_sales_person=True, tc2_admin_id=30
        )
        company = await Company.create(
            name='Test company', pd_org_id=20, tc2_cligency_id=10, sales_person=admin, price_plan=Company.PP_PAYG
        )
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        await Deal.create(
            name='Old test deal',
            pd_deal_id=40,
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )
        await update_client_from_company(company)
        assert self.tc2.db['clients'] == {
            10: {
                'user': {
                    'email': 'mary@booth.com',
                    'phone': None,
                    'first_name': 'Mary',
                    'last_name': 'Booth',
                },
                'status': 'live',
                'sales_person': {
                    'id': 30,
                    'first_name': 'Brain',
                    'last_name': 'Johnson',
                    'email': 'brian@tc.com',
                },
                'associated_admin': None,
                'bdr_person': None,
                'paid_recipients': [
                    {
                        'email': 'mary@booth.com',
                        'first_name': 'Mary',
                        'last_name': 'Booth',
                    },
                ],
                'extra_attrs': {
                    'pipedrive_deal_stage': 'New',
                    'pipedrive_pipeline': 'payg',
                    'pipedrive_url': f'{settings.pd_base_url}/organization/20/',
                    'who_are_you_trying_to_reach': 'support',
                },
            }
        }

    @mock.patch('app.tc2.api.session.request')
    async def test_update_cligency_custom_fields(self, mock_request):
        mock_request.side_effect = fake_tc2_request(self.tc2)
        admin = await Admin.create(
            pd_owner_id=10, username='testing@example.com', is_sales_person=True, tc2_admin_id=30
        )
        company = await Company.create(
            name='Test company', pd_org_id=20, tc2_cligency_id=10, sales_person=admin, price_plan=Company.PP_PAYG
        )

        pipedrive_id_field = await CustomField.create(
            name='Pipedrive ID',
            field_type=CustomField.TYPE_INT,
            linked_object_type='Company',
            hermes_field_name='pd_org_id',
            tc2_machine_name='pipedrive_id',
        )
        domain_field = await CustomField.create(
            name='Domain',
            field_type=CustomField.TYPE_STR,
            linked_object_type='Company',
            tc2_machine_name='company_domain',
        )
        await CustomFieldValue.create(custom_field=domain_field, value='example.com', company=company)
        await update_client_from_company(company)
        assert self.tc2.db['clients'] == {
            10: {
                'user': {
                    'email': 'mary@booth.com',
                    'phone': None,
                    'first_name': 'Mary',
                    'last_name': 'Booth',
                },
                'status': 'live',
                'sales_person': {
                    'id': 30,
                    'first_name': 'Brain',
                    'last_name': 'Johnson',
                    'email': 'brian@tc.com',
                },
                'bdr_person': None,
                'associated_admin': None,
                'paid_recipients': [
                    {
                        'email': 'mary@booth.com',
                        'first_name': 'Mary',
                        'last_name': 'Booth',
                    },
                ],
                'extra_attrs': {
                    'pipedrive_url': f'{settings.pd_base_url}/organization/20/',
                    'pipedrive_id': 20,
                    'who_are_you_trying_to_reach': 'support',
                    'company_domain': 'example.com',
                },
            }
        }
        await pipedrive_id_field.delete()
        await domain_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.tc2.api.session.request')
    async def test_update_cligency_custom_fields_none(self, mock_request):
        """
        Update a company with custom fields, with no CustomFieldValue
        """

        mock_request.side_effect = fake_tc2_request(self.tc2)
        admin = await Admin.create(
            pd_owner_id=10, username='testing@example.com', is_sales_person=True, tc2_admin_id=30
        )
        company = await Company.create(
            name='Test company', pd_org_id=20, tc2_cligency_id=10, sales_person=admin, price_plan=Company.PP_PAYG
        )

        pipedrive_id_field = await CustomField.create(
            name='Pipedrive ID',
            field_type=CustomField.TYPE_INT,
            linked_object_type='Company',
            hermes_field_name='pd_org_id',
            tc2_machine_name='pipedrive_id',
        )
        domain_field = await CustomField.create(
            name='Domain',
            field_type=CustomField.TYPE_STR,
            linked_object_type='Company',
            tc2_machine_name='company_domain',
        )

        await update_client_from_company(company)
        assert self.tc2.db['clients'] == {
            10: {
                'user': {
                    'email': 'mary@booth.com',
                    'phone': None,
                    'first_name': 'Mary',
                    'last_name': 'Booth',
                },
                'status': 'live',
                'sales_person': {
                    'id': 30,
                    'first_name': 'Brain',
                    'last_name': 'Johnson',
                    'email': 'brian@tc.com',
                },
                'bdr_person': None,
                'associated_admin': None,
                'paid_recipients': [
                    {
                        'email': 'mary@booth.com',
                        'first_name': 'Mary',
                        'last_name': 'Booth',
                    },
                ],
                'extra_attrs': {
                    'pipedrive_url': f'{settings.pd_base_url}/organization/20/',
                    'pipedrive_id': 20,
                    'who_are_you_trying_to_reach': 'support',
                    'company_domain': None,
                },
            }
        }
        await pipedrive_id_field.delete()
        await domain_field.delete()
        await build_custom_field_schema()
