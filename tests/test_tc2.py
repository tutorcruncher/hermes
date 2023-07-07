from app.models import Admins, Companies, Contacts
from tests._common import HermesTestCase


def client_full_event_data():
    return {
        'action': 'create',
        'verb': 'create',
        'subject': {
            'id': 10,
            'model': 'Client',
            'meta_agency': {
                'id': 20,
                'name': 'MyTutors',
                'website': 'www.example.com',
                'status': 'active',
                'paid_invoice_count': 7,
                'country': 'United Kingdom (GB)',
            },
            'associated_admin': {
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
        },
    }


def client_deleted_event_data():
    return {
        'action': 'delete',
        'verb': 'delete',
        'subject': {
            'id': 10,
            'model': 'Client',
            'first_name': 'Harry',
            'last_name': 'Poster',
        },
    }


class TCCallbackTestCase(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.url = '/tc2/callback/'

    async def test_callback_invalid_api_key(self):
        r = await self.client.post(
            self.url, headers={'Authorization': 'Bearer 999'}, json={'_request_time': 123, 'events': []}
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
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0
        r = await self.client.post(
            self.url,
            json={'_request_time': 123, 'events': {'foo': 'bar'}},
            headers={'Authorization': 'Bearer test-key'},
        )
        assert r.status_code == 422, r.json()

    async def test_cb_client_event_test_1(self):
        """
        Create a new company
        Create new contacts
        With associated admin that doesn't exist
        """
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0
        events = [client_full_event_data()]
        r = await self.client.post(
            self.url, json={'_request_time': 123, 'events': events}, headers={'Authorization': 'Bearer test-key'}
        )
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert company.name == 'MyTutors'
        assert company.tc_agency_id == 20
        assert company.tc_cligency_id == 10
        assert company.status == 'active'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 7

        assert not company.estimated_income
        assert not company.client_manager
        assert not company.sales_person
        assert not company.bdr_person

        contact = await Contacts.get()
        assert contact.tc_sr_id == 40
        assert contact.first_name == 'Mary'
        assert contact.last_name == 'Booth'
        assert contact.email == 'mary@booth.com'

    async def test_cb_client_event_test_2(self):
        """
        Create a new company
        Create no contacts
        With associated admin
        """
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0

        admin = await Admins.create(
            tc_admin_id=30, first_name='Brain', last_name='Johnson', email='brian@tc.com', password='foo'
        )

        modified_data = client_full_event_data()
        modified_data['subject']['paid_recipients'] = []

        events = [modified_data]
        r = await self.client.post(
            self.url, json={'_request_time': 123, 'events': events}, headers={'Authorization': 'Bearer test-key'}
        )
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert company.name == 'MyTutors'
        assert company.tc_agency_id == 20
        assert company.tc_cligency_id == 10
        assert company.status == 'active'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 7
        assert await company.client_manager == admin

        assert not company.estimated_income
        assert not company.sales_person
        assert not company.bdr_person

        assert await Contacts.all().count() == 0

    async def test_cb_client_event_test_3(self):
        """
        Update a current company
        Create no contacts
        Setting associated admin to None
        """
        admin = await Admins.create(
            tc_admin_id=30, first_name='Brain', last_name='Johnson', email='brian@tc.com', password='foo'
        )
        await Companies.create(
            tc_agency_id=20, tc_cligency_id=10, name='OurTutors', status='inactive', client_manager=admin
        )
        assert await Contacts.all().count() == 0

        modified_data = client_full_event_data()
        modified_data['subject']['associated_admin'] = None
        modified_data['subject']['paid_recipients'] = []

        events = [modified_data]
        r = await self.client.post(
            self.url, json={'_request_time': 123, 'events': events}, headers={'Authorization': 'Bearer test-key'}
        )
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert company.name == 'MyTutors'
        assert company.tc_agency_id == 20
        assert company.tc_cligency_id == 10
        assert company.status == 'active'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 7
        assert not await company.client_manager

        assert not company.estimated_income
        assert not company.sales_person
        assert not company.bdr_person

        assert await Contacts.all().count() == 0

    async def test_cb_client_event_test_4(self):
        """
        Update a current company
        Create new contacts & Update contacts
        """
        company = await Companies.create(tc_agency_id=20, tc_cligency_id=10, name='OurTutors', status='inactive')
        contact_a = await Contacts.create(
            first_name='Jim', last_name='Snail', email='mary@booth.com', tc_sr_id=40, company=company
        )
        modified_data = client_full_event_data()
        modified_data['subject']['paid_recipients'].append(
            {'first_name': 'Rudy', 'last_name': 'Jones', 'email': 'rudy@jones.com', 'id': '41'}
        )
        events = [modified_data]
        r = await self.client.post(
            self.url, json={'_request_time': 123, 'events': events}, headers={'Authorization': 'Bearer test-key'}
        )
        assert r.status_code == 200, r.json()

        company = await Companies.get()
        assert company.name == 'MyTutors'
        assert company.tc_agency_id == 20
        assert company.tc_cligency_id == 10
        assert company.status == 'active'
        assert company.country == 'GB'
        assert company.paid_invoice_count == 7
        assert not await company.client_manager

        assert not company.estimated_income
        assert not company.sales_person
        assert not company.bdr_person

        assert await Contacts.all().count() == 2
        contact_a = await Contacts.get(id=contact_a.id)
        assert contact_a.tc_sr_id == 40
        assert contact_a.first_name == 'Mary'
        assert contact_a.last_name == 'Booth'

        contact_b = await Contacts.exclude(id=contact_a.id).get()
        assert contact_b.tc_sr_id == 41
        assert contact_b.first_name == 'Rudy'
        assert contact_b.last_name == 'Jones'

    async def test_cb_client_deleted_no_linked_data(self):
        """
        Company deleted, has no contacts
        """
        await Companies.create(tc_agency_id=20, tc_cligency_id=10, name='OurTutors', status='inactive')
        r = await self.client.post(
            self.url,
            json={'_request_time': 123, 'events': [client_deleted_event_data()]},
            headers={'Authorization': 'Bearer test-key'},
        )
        assert r.status_code == 200, r.json()
        assert await Companies.all().count() == 0

    async def test_cb_client_deleted_test_has_linked_data(self):
        """
        Company deleted, has contact
        """
        company = await Companies.create(tc_agency_id=20, tc_cligency_id=10, name='OurTutors', status='inactive')
        await Contacts.create(first_name='Jim', last_name='Snail', email='mary@booth.com', tc_sr_id=40, company=company)
        r = await self.client.post(
            self.url,
            json={'_request_time': 123, 'events': [client_deleted_event_data()]},
            headers={'Authorization': 'Bearer test-key'},
        )
        assert r.status_code == 200, r.json()
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0

    async def test_cb_client_deleted_doesnt_exist(self):
        """
        Company deleted, has no contacts
        """
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0
        r = await self.client.post(
            self.url,
            json={'_request_time': 123, 'events': [client_deleted_event_data()]},
            headers={'Authorization': 'Bearer test-key'},
        )
        assert r.status_code == 200, r.json()
        assert await Companies.all().count() == 0
        assert await Contacts.all().count() == 0

    async def test_cb_invoice_event_update_client(self):
        """
        Processing an invoice event means we get the client from TC.
        """
        pass

    async def test_cb_invoice_event_tc_request_error(self):
        """
        Processing an invoice event means we get the client from TC. Testing an error.
        """
        pass
