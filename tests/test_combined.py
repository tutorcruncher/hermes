import copy
import hashlib
import hmac
import json
from datetime import datetime
from unittest import mock

from pytz import utc

from app.base_schema import build_custom_field_schema
from app.models import Admin, Company, Contact, CustomField, CustomFieldValue, Deal, Meeting, Pipeline
from app.pipedrive._schema import PDStatus
from app.pipedrive.tasks import pd_post_process_client_event, pd_post_process_sales_call
from app.tc2.tasks import update_client_from_company
from app.utils import settings
from tests._common import HermesTestCase
from tests.test_callbooker import CB_MEETING_DATA, fake_gcal_builder
from tests.test_pipedrive import (
    FakePipedrive,
    basic_pd_deal_data,
    basic_pd_org_data,
    fake_pd_request,
)
from tests.test_tc2 import FakeTC2, client_full_event_data, fake_tc2_request, mock_tc2_request


class TestMultipleServices(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.pipedrive = FakePipedrive()
        self.tc2 = FakeTC2()
        self.tc2_callback = '/tc2/callback/'
        self.pipedrive_callback = '/pipedrive/callback/'

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

        r = await self.client.post(self.pipedrive_callback, json=pd_org_data)
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
        r = await self.client.post(self.tc2_callback, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
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

        r = await self.client.post(self.pipedrive_callback, json=data)
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
        modified_data['subject']['meta_agency']['signup_questionnaire'] = {
            'how-did-you-hear-about-us': 'Blog or Article',
            'are-lessons-mostly-remote-or-in-person': 'Mostly in-person',
            'how-do-you-currently-match-your-students-to-tutors': 'We assign tutors to students manually',
            'do-you-provide-mostly-one-to-one-lessons-or-group-classes': 'Mostly one to one',
            'how-many-students-are-currently-actively-using-your-service': 45,
            'do-you-take-payment-from-clients-upfront-or-after-the-lesson-takes-place': 'Mostly after the lesson takes place',
        }
        events = [modified_data]

        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.tc2_callback, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
        assert r.status_code == 200, r.json()

        assert await Company.exists()
        company = await Company.get()
        assert company.name == 'MyTutors'
        assert not company.bdr_person
        assert await company.support_person == await company.sales_person == admin
        assert company.signup_questionnaire == {
            'how-did-you-hear-about-us': 'Blog or Article',
            'are-lessons-mostly-remote-or-in-person': 'Mostly in-person',
            'how-do-you-currently-match-your-students-to-tutors': 'We assign tutors to students manually',
            'do-you-provide-mostly-one-to-one-lessons-or-group-classes': 'Mostly one to one',
            'how-many-students-are-currently-actively-using-your-service': 45,
            'do-you-take-payment-from-clients-upfront-or-after-the-lesson-takes-place': 'Mostly after the lesson takes place',
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
                '123_signup_questionnaire_456': '{"how-did-you-hear-about-us": "Blog or Article", '
                '"are-lessons-mostly-remote-or-in-person": "Mostly in-person", '
                '"how-do-you-currently-match-your-students-to-tutors": "We assign '
                'tutors to students manually", '
                '"do-you-provide-mostly-one-to-one-lessons-or-group-classes": "Mostly '
                'one to one", '
                '"how-many-students-are-currently-actively-using-your-service": 45, '
                '"do-you-take-payment-from-clients-upfront-or-after-the-lesson-takes-place": '
                '"Mostly after the lesson takes place"}',
            }
        }


class TestDealCustomFieldInheritance(HermesTestCase):
    def setUp(self):
        super().setUp()
        self.pipedrive = FakePipedrive()
        self.tc2 = FakeTC2()
        self.tc2_callback = '/tc2/callback/'
        self.pipedrive_callback = '/pipedrive/callback/'
        self.callbooker_callback = '/callbooker/sales/book/'

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

    @mock.patch('app.pipedrive.api.session.request')
    async def test_cb_client_event_company_org_deal(self, mock_pd_request):
        """
        tc2 callback
        create company with cfs
        no contact
        create deal with orgs cfs
        create org
        create deal
        """
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)

        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=10,
        )
        # org cfs
        sales_custom_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_sales_person_456',
            hermes_field_name='sales_person',
            name='Sales Person',
            machine_name='sales_person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        bdr_custom_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_bdr_person_456',
            hermes_field_name='bdr_person',
            name='BDR Person',
            machine_name='bdr_person',
            field_type=CustomField.TYPE_FK_FIELD,
        )
        # this field is a custom field that would be inherited by the deal from the org, however its source is only
        # from TC2
        source_custom_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_source_456',
            hermes_field_name=None,
            tc2_machine_name='client_marketing_source',
            name='Source',
            machine_name='source',
            field_type=CustomField.TYPE_STR,
        )

        estimated_monthly_income_custom_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_estimated_monthly_income_456',
            hermes_field_name='estimated_income',
            tc2_machine_name='estimated_monthly_income',
            name='Estimated Monthly Income',
            machine_name='estimated_monthly_income',
            field_type=CustomField.TYPE_STR,
        )

        # deal cfs
        deal_sales_custom_field = await CustomField.create(
            linked_object_type='Deal',
            pd_field_id='234_sales_person_567',
            name='Sales Person',
            machine_name='sales_person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        deal_bdr_custom_field = await CustomField.create(
            linked_object_type='Deal',
            pd_field_id='234_bdr_person_567',
            name='BDR Person',
            machine_name='bdr_person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        deal_source_custom_field = await CustomField.create(
            linked_object_type='Deal',
            pd_field_id='234_source_567',
            name='Source',
            machine_name='source',
            field_type=CustomField.TYPE_STR,
        )

        deal_estimated_monthly_income_custom_field = await CustomField.create(
            linked_object_type='Deal',
            pd_field_id='234_estimated_monthly_income_567',
            name='Estimated Monthly Income',
            machine_name='estimated_monthly_income',
            field_type=CustomField.TYPE_STR,
        )

        await build_custom_field_schema()

        modified_data = client_full_event_data()
        modified_data['subject']['paid_recipients'] = []
        modified_data['subject']['meta_agency']['status'] = 'trial'
        modified_data['subject']['meta_agency']['paid_invoice_count'] = 0
        modified_data['subject']['extra_attrs'] += [
            {'machine_name': 'client_marketing_source', 'value': 'Google'},
            {'machine_name': 'estimated_monthly_income', 'value': '£20,000 - £50,000'},
        ]

        events = [modified_data]
        data = {'_request_time': 123, 'events': events}
        r = await self.client.post(self.tc2_callback, json=data, headers={'Webhook-Signature': self._tc2_sig(data)})
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
        assert not company.has_booked_call

        assert company.estimated_income

        assert await Contact.all().count() == 0
        deal = await Deal.get()
        assert deal.name == 'MyTutors'
        assert await deal.pipeline == self.pipeline
        assert not deal.contact
        assert await deal.stage == self.stage

        await pd_post_process_client_event(company, deal)

        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'MyTutors',
                'address_country': 'GB',
                'owner_id': 10,
                '123_hermes_id_456': company.id,
                '123_sales_person_456': admin.id,
                '123_bdr_person_456': admin.id,
                '123_source_456': 'google',
                '123_estimated_monthly_income_456': '£20,000 - £50,000',
            }
        }

        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'MyTutors',
                'org_id': 1,
                'person_id': None,
                'pipeline_id': (await Pipeline.get()).pd_pipeline_id,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                'user_id': 10,
                '345_hermes_id_678': deal.id,
                '234_sales_person_567': admin.id,
                '234_bdr_person_567': admin.id,
                '234_source_567': 'google',
                '234_estimated_monthly_income_567': '£20,000 - £50,000',
            }
        }

        await sales_custom_field.delete()
        await bdr_custom_field.delete()
        await source_custom_field.delete()
        await estimated_monthly_income_custom_field.delete()
        await deal_sales_custom_field.delete()
        await deal_bdr_custom_field.delete()
        await deal_source_custom_field.delete()
        await deal_estimated_monthly_income_custom_field.delete()
        await build_custom_field_schema()

    # need a test for a callbooker create company
    @mock.patch('app.pipedrive.api.session.request')
    @mock.patch('app.callbooker._google.AdminGoogleCalendar._create_resource')
    async def test_com_cli_create_update_org_deal(self, mock_gcal_builder, mock_pd_request):
        """
        Book a new meeting
        Company doesn't exist so create
        Contact doesn't exist so create
        Create with admin

        create org
        create deal
        """
        mock_gcal_builder.side_effect = fake_gcal_builder()
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)

        custom_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_sales_person_456',
            hermes_field_name='sales_person',
            name='Sales Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        support_person_custom_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_support_person_456',
            hermes_field_name='support_person',
            machine_name='support_person',
            name='Support Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        deal_custom_field = await CustomField.create(
            linked_object_type='Deal',
            pd_field_id='234_sales_person_567',
            name='Sales Person',
            machine_name='sales_person',
            field_type=CustomField.TYPE_INT,
        )

        deal_support_person_custom_field = await CustomField.create(
            linked_object_type='Deal',
            pd_field_id='234_support_person_567',
            name='Support Person',
            machine_name='support_person',
            field_type=CustomField.TYPE_INT,
        )

        await build_custom_field_schema()

        custom_field_values = await CustomFieldValue.all()
        assert len(custom_field_values) == 0

        sales_person = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_support_person=True,
            pd_owner_id=5,
            sells_payg=True,
            sells_gb=True,
        )
        assert await Company.all().count() == 0
        assert await Contact.all().count() == 0
        r = await self.client.post(self.callbooker_callback, json={'admin_id': sales_person.id, **CB_MEETING_DATA})
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
        assert not company.support_person_id

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

        deal = await Deal.get()
        assert deal.name == 'Junes Ltd'
        assert await deal.pipeline == self.pipeline
        assert await deal.stage == self.stage
        assert await deal.contact == contact
        assert await deal.company == company
        assert await deal.admin == sales_person

        await pd_post_process_sales_call(company, contact, meeting, deal)

        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Junes Ltd',
                'address_country': 'GB',
                'owner_id': sales_person.pd_owner_id,
                '123_hermes_id_456': company.id,
                '123_sales_person_456': sales_person.id,
                '123_support_person_456': None,
            }
        }
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'Junes Ltd',
                'org_id': 1,
                'person_id': 1,
                'pipeline_id': (await Pipeline.get()).pd_pipeline_id,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                'user_id': sales_person.pd_owner_id,
                '345_hermes_id_678': deal.id,
                '234_sales_person_567': sales_person.id,
                '234_support_person_567': 0,
            }
        }

        await custom_field.delete()
        await deal_custom_field.delete()
        await support_person_custom_field.delete()
        await deal_support_person_custom_field.delete()
        await build_custom_field_schema()

    ### TODO: Re-enabled in #281
    # @mock.patch('app.pipedrive.api.session.request')
    # async def test_org_update_custom_field_val_created_with_child_deal_cf(self, mock_request):
    #     mock_request.side_effect = fake_pd_request(self.pipedrive)
    #
    #     admin = await Admin.create(
    #         tc2_admin_id=30,
    #         first_name='Brain',
    #         last_name='Johnson',
    #         username='brian@tc.com',
    #         password='foo',
    #         pd_owner_id=10,
    #     )
    #
    #     source_field = await CustomField.create(
    #         linked_object_type='Company',
    #         pd_field_id='123_source_456',
    #         name='Source',
    #         field_type='str',
    #     )
    #
    #     deal_source_field = await CustomField.create(
    #         linked_object_type='Deal',
    #         pd_field_id='234_source_567',
    #         name='Source',
    #         field_type='str',
    #     )
    #     await build_custom_field_schema()
    #
    #     company = await Company.create(name='Old test company', sales_person=admin)
    #     self.pipedrive.db['organizations'] = {
    #         1: {
    #             'id': 10,
    #             'name': 'Julies Ltd',
    #             'address_country': 'GB',
    #             'owner_id': 10,
    #             '123_hermes_id_456': company.id,
    #             '123_source_456': 'Google',
    #         },
    #     }
    #
    #     contact = await Contact.create(
    #         first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
    #     )
    #     deal = await Deal.create(
    #         name='A deal with Julies Ltd',
    #         company=company,
    #         contact=contact,
    #         pipeline=self.pipeline,
    #         stage=self.stage,
    #         admin=admin,
    #         pd_deal_id=1,
    #     )
    #
    #     self.pipedrive.db['deals'] = {
    #         1: {
    #             'id': 1,
    #             'title': 'A deal with Julies Ltd',
    #             'org_id': 1,
    #             'person_id': 1,
    #             'user_id': 99,
    #             'pipeline_id': 1,
    #             'stage_id': 1,
    #             'status': 'open',
    #             '345_hermes_id_678': deal.id,
    #         }
    #     }
    #
    #     data = copy.deepcopy(basic_pd_org_data())
    #     data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
    #     data[PDStatus.PREVIOUS].update(hermes_id=company.id)
    #     data[PDStatus.CURRENT].update(**{'name': 'New test company', '123_source_456': 'Google'})
    #     r = await self.client.post(self.pipedrive_callback, json=data)
    #     assert r.status_code == 200, r.json()
    #     company = await Company.get()
    #     assert company.name == 'New test company'
    #
    #     await update_client_from_company(company)
    #
    #     assert self.pipedrive.db['organizations'] == {
    #         1: {
    #             'id': 10,
    #             'name': 'Julies Ltd',
    #             'address_country': 'GB',
    #             'owner_id': 10,
    #             '123_hermes_id_456': company.id,
    #             '123_source_456': 'Google',
    #         }
    #     }
    #
    #     assert self.pipedrive.db['deals'] == {
    #         1: {
    #             'title': 'A deal with Julies Ltd',
    #             'org_id': 20,
    #             'person_id': None,
    #             'pipeline_id': (await Pipeline.get()).pd_pipeline_id,
    #             'stage_id': 1,
    #             'status': 'open',
    #             'id': 1,
    #             'user_id': 10,
    #             '345_hermes_id_678': deal.id,
    #             '234_source_567': 'Google',
    #         }
    #     }
    #
    #     counter = 0
    #     cf_vals = await CustomFieldValue.all()
    #     for cf_val in cf_vals:
    #         custom_field = await cf_val.custom_field
    #         if custom_field.machine_name == 'source':
    #             assert cf_val.value == 'Google'
    #             counter += 1
    #
    #     assert counter == 2
    #
    #     await source_field.delete()
    #     await deal_source_field.delete()
    #     await build_custom_field_schema()
    #
    # #
    # @mock.patch('app.pipedrive.api.session.request')
    # async def test_org_update_custom_field_val_created_with_multiple_child_deals(self, mock_request):
    #     """
    #     test for when a company already exists with multiple deals we update the inherited cfs on all those deals
    #     """
    #     mock_request.side_effect = fake_pd_request(self.pipedrive)
    #
    #     admin = await Admin.create(
    #         tc2_admin_id=30,
    #         first_name='Brain',
    #         last_name='Johnson',
    #         username='brian@tc.com',
    #         password='foo',
    #         pd_owner_id=10,
    #     )
    #
    #     source_field = await CustomField.create(
    #         linked_object_type='Company',
    #         pd_field_id='123_source_456',
    #         name='Source',
    #         machine_name='source',
    #         field_type='str',
    #     )
    #
    #     deal_source_field = await CustomField.create(
    #         linked_object_type='Deal',
    #         pd_field_id='234_source_567',
    #         name='Source',
    #         machine_name='source',
    #         field_type='str',
    #     )
    #     await build_custom_field_schema()
    #
    #     company = await Company.create(name='Julies Ltd', sales_person=admin, pd_org_id=10)
    #     self.pipedrive.db['organizations'] = {
    #         1: {
    #             'id': 10,
    #             'name': 'Julies Ltd',
    #             'address_country': 'GB',
    #             'owner_id': 10,
    #             '123_hermes_id_456': company.id,
    #             '123_source_456': 'Google',
    #         },
    #     }
    #
    #     contact = await Contact.create(
    #         first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
    #     )
    #     deal = await Deal.create(
    #         name='A deal with Julies Ltd',
    #         company=company,
    #         contact=contact,
    #         pipeline=self.pipeline,
    #         stage=self.stage,
    #         admin=admin,
    #         pd_deal_id=1,
    #     )
    #
    #     deal2 = await Deal.create(
    #         name='A deal with Julies Ltd',
    #         company=company,
    #         contact=contact,
    #         pipeline=self.pipeline,
    #         stage=self.stage,
    #         admin=admin,
    #         pd_deal_id=2,
    #     )
    #
    #     self.pipedrive.db['deals'] = {
    #         1: {
    #             'id': 1,
    #             'title': 'A deal with Julies Ltd',
    #             'org_id': 10,
    #             'person_id': 1,
    #             'user_id': 99,
    #             'pipeline_id': 1,
    #             'stage_id': 1,
    #             'status': 'open',
    #             '345_hermes_id_678': deal.id,
    #         },
    #         2: {
    #             'id': 2,
    #             'title': 'A deal with Julies Ltd',
    #             'org_id': 10,
    #             'person_id': 1,
    #             'user_id': 99,
    #             'pipeline_id': 1,
    #             'stage_id': 1,
    #             'status': 'open',
    #             '345_hermes_id_678': deal2.id,
    #         },
    #     }
    #
    #     data = copy.deepcopy(basic_pd_org_data())
    #     data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
    #     data[PDStatus.PREVIOUS].update(hermes_id=company.id)
    #     data[PDStatus.CURRENT].update(**{'123_source_456': 'Google', 'hermes_id': company.id})
    #     r = await self.client.post(self.pipedrive_callback, json=data)
    #     assert r.status_code == 200, r.json()
    #     company = await Company.get()
    #     assert company.name == 'Julies Ltd'
    #
    #     await update_client_from_company(company)
    #
    #     assert self.pipedrive.db['organizations'] == {
    #         1: {
    #             'id': 10,
    #             'name': 'Julies Ltd',
    #             'address_country': 'GB',
    #             'owner_id': 10,
    #             '123_hermes_id_456': company.id,
    #             '123_source_456': 'Google',
    #         }
    #     }
    #
    #     assert self.pipedrive.db['deals'] == {
    #         1: {
    #             'title': 'A deal with Julies Ltd',
    #             'org_id': 10,
    #             'person_id': None,
    #             'pipeline_id': (await Pipeline.get()).pd_pipeline_id,
    #             'stage_id': 1,
    #             'status': 'open',
    #             'id': 1,
    #             'user_id': 10,
    #             '345_hermes_id_678': deal.id,
    #             '234_source_567': 'Google',
    #         },
    #         2: {
    #             'title': 'A deal with Julies Ltd',
    #             'org_id': 10,
    #             'person_id': None,
    #             'pipeline_id': (await Pipeline.get()).pd_pipeline_id,
    #             'stage_id': 1,
    #             'status': 'open',
    #             'id': 2,
    #             'user_id': 10,
    #             '345_hermes_id_678': deal2.id,
    #             '234_source_567': 'Google',
    #         },
    #     }
    #
    #     counter = 0
    #     cf_vals = await CustomFieldValue.all()
    #     for cf_val in cf_vals:
    #         custom_field = await cf_val.custom_field
    #         if custom_field.machine_name == 'source':
    #             assert cf_val.value == 'Google'
    #             counter += 1
    #
    #     assert counter == 3
    #
    #     await source_field.delete()
    #     await deal_source_field.delete()
    #     await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_ignore_update_of_inherited_custom_field_on_deal(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)

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
            machine_name='source',
            field_type='str',
        )

        deal_source_field = await CustomField.create(
            linked_object_type='Deal',
            pd_field_id='234_source_567',
            name='Source',
            machine_name='source',
            field_type='str',
        )
        await build_custom_field_schema()

        company = await Company.create(name='Julies Ltd', sales_person=admin, pd_org_id=1, country='GB')
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 10,
                '123_hermes_id_456': company.id,
                '123_source_456': 'Google',
            },
        }

        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=1,
        )

        deal2 = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=2,
        )

        self.pipedrive.db['deals'] = {
            1: {
                'id': 1,
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': 1,
                'user_id': admin.pd_owner_id,
                'pipeline_id': self.pipeline.pd_pipeline_id,
                'stage_id': 1,
                'status': 'open',
                '345_hermes_id_678': deal.id,
                '234_source_567': 'Google',
            },
            2: {
                'id': 2,
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': 1,
                'user_id': admin.pd_owner_id,
                'pipeline_id': self.pipeline.pd_pipeline_id,
                'stage_id': 1,
                'status': 'open',
                '345_hermes_id_678': deal2.id,
                '234_source_567': 'Google',
            },
        }

        await CustomFieldValue.create(custom_field=source_field, company=company, value='Google')
        await CustomFieldValue.create(custom_field=deal_source_field, deal=deal, value='Google')
        await CustomFieldValue.create(custom_field=deal_source_field, deal=deal2, value='Google')
        data = copy.deepcopy(basic_pd_deal_data())
        data[PDStatus.CURRENT]['pipeline_id'] = self.pipeline.pd_pipeline_id
        data[PDStatus.CURRENT]['stage_id'] = self.stage.pd_stage_id
        data[PDStatus.CURRENT]['user_id'] = admin.pd_owner_id
        data[PDStatus.CURRENT]['org_id'] = 1
        data[PDStatus.CURRENT]['person_id'] = 1
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(**{'234_source_567': 'Google', 'hermes_id': deal.id})
        data[PDStatus.PREVIOUS].update(hermes_id=deal.id)
        data[PDStatus.CURRENT].update(**{'234_source_567': 'Yahoo', 'hermes_id': deal.id})
        r = await self.client.post(self.pipedrive_callback, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()

        await update_client_from_company(company)

        counter = 0
        cf_vals = await CustomFieldValue.all()
        for cf_val in cf_vals:
            custom_field = await cf_val.custom_field
            if custom_field.machine_name == 'source':
                assert cf_val.value == 'Google'
                counter += 1

        assert counter == 3

        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 10,
                '123_hermes_id_456': company.id,
                '123_source_456': 'Google',
            }
        }

        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': 1,
                'pipeline_id': (await Pipeline.get()).pd_pipeline_id,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                'user_id': 10,
                '345_hermes_id_678': deal.id,
                '234_source_567': 'Google',
            },
            2: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': 1,
                'pipeline_id': (await Pipeline.get()).pd_pipeline_id,
                'stage_id': 1,
                'status': 'open',
                'id': 2,
                'user_id': 10,
                '345_hermes_id_678': deal2.id,
                '234_source_567': 'Google',
            },
        }

        await source_field.delete()
        await deal_source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_pd_post_process_client_event_value_error(self, mock_pd_request):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=10,
        )

        company = await Company.create(
            name='Test Company',
            sales_person=admin,
        )

        sales_person = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_sales_person_456',
            hermes_field_name='sales_person',
            name='Sales Person',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        await build_custom_field_schema()

        await pd_post_process_client_event(company=company)

        await sales_person.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_duplicate_hermes_ids_in_pd(self, mock_pd_request):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=10,
        )

        await Company.create(id=1, name='Old test company', sales_person=admin, pd_org_id=1)
        await Company.create(id=2, name='Another test company', sales_person=admin, pd_org_id=2)

        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'Old test company',
                'address_country': None,
                'owner_id': 10,
                '123_hermes_id_456': '1, 2',
                '123_sales_person_456': admin.id,
            },
        }

        data = copy.deepcopy(basic_pd_org_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update({'123_hermes_id_456': '1, 2'})
        r = await self.client.post(self.pipedrive_callback, json=data)
        assert r.status_code == 200

        assert await Company.exists(id=1)
        assert not await Company.exists(id=2)

        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Old test company',
                'address_country': None,
                'owner_id': 10,
                '123_hermes_id_456': 1,
                '123_sales_person_456': admin.id,
            },
        }

    @mock.patch('app.pipedrive.api.session.request')
    async def test_deal_update_merged_please(self, mock_pd_request):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)

        self.pipedrive.db = {
            'organizations': {
                1: {
                    'id': 1,
                    'name': 'Test company',
                    'address_country': 'GB',
                    'owner_id': None,
                    '123_hermes_id_456': 1,
                }
            },
            'deals': {
                1: {
                    'title': 'Old test deal',
                    'org_id': 1,
                    'person_id': None,
                    'pipeline_id': 1,
                    'stage_id': 1,
                    'status': 'open',
                    'id': 1,
                    'user_id': 1,
                    '345_hermes_id_678': 1,
                },
                2: {
                    'title': 'Old test deal2',
                    'org_id': 1,
                    'person_id': None,
                    'pipeline_id': 1,
                    'stage_id': 1,
                    'status': 'open',
                    'id': 2,
                    'user_id': 1,
                    '345_hermes_id_678': 2,
                },
            },
            'persons': {
                1: {
                    'id': 1,
                    'name': 'Brian Blessed',
                    'email': 'brian@tc.com',
                    'org_id': 1,
                    '234_hermes_id_567': 1,
                }
            },
            'pipelines': {
                1: {
                    'id': 1,
                    'name': 'Pipeline 1',
                    'dft_entry_stage_id': 1,
                }
            },
            'stages': {
                1: {
                    'id': 1,
                    'name': 'Stage 2',
                }
            },
        }

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=1,
        )

        company = await Company.create(name='Test company', pd_org_id=1, sales_person=admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=1, company=company)
        deal = await Deal.create(
            name='Old test deal',
            pd_deal_id=1,
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )
        deal2 = await Deal.create(
            name='Old test deal2',
            pd_deal_id=2,
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )

        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
            deal=deal2,
        )

        assert await Deal.exists()

        data = copy.deepcopy(basic_pd_deal_data())
        data[PDStatus.CURRENT].update(
            **{
                '345_hermes_id_678': f'{deal.id},{deal2.id}',
                'title': 'Old test deal',
                'org_id': 1,
                'person_id': 1,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'user_id': 1,
            }
        )
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])

        r = await self.client.post(self.pipedrive_callback, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get(id=deal.id)
        assert not await Deal.exists(id=deal2.id)

        assert deal.name == 'Old test deal'
        meeting2 = await Meeting.get(id=meeting.id)
        assert await meeting2.deal == deal

    @mock.patch('app.pipedrive.api.session.request')
    async def test_deal_update_merged_previous(self, mock_pd_request):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)

        self.pipedrive.db = {
            'organizations': {
                1: {
                    'id': 1,
                    'name': 'Test company',
                    'address_country': 'GB',
                    'owner_id': None,
                    '123_hermes_id_456': 1,
                }
            },
            'deals': {
                1: {
                    'title': 'Old test deal',
                    'org_id': 1,
                    'person_id': None,
                    'pipeline_id': 1,
                    'stage_id': 1,
                    'status': 'open',
                    'id': 1,
                    'user_id': 1,
                    '345_hermes_id_678': 1,
                },
                2: {
                    'title': 'Old test deal2',
                    'org_id': 1,
                    'person_id': None,
                    'pipeline_id': 1,
                    'stage_id': 1,
                    'status': 'open',
                    'id': 2,
                    'user_id': 1,
                    '345_hermes_id_678': 2,
                },
            },
            'persons': {
                1: {
                    'id': 1,
                    'name': 'Brian Blessed',
                    'email': 'brian@tc.com',
                    'org_id': 1,
                    '234_hermes_id_567': 1,
                }
            },
            'pipelines': {
                1: {
                    'id': 1,
                    'name': 'Pipeline 1',
                    'dft_entry_stage_id': 1,
                }
            },
            'stages': {
                1: {
                    'id': 1,
                    'name': 'Stage 2',
                }
            },
        }

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=1,
        )

        company = await Company.create(name='Test company', pd_org_id=1, sales_person=admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=1, company=company)
        deal = await Deal.create(
            name='Old test deal',
            pd_deal_id=1,
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )
        deal2 = await Deal.create(
            name='Old test deal2',
            pd_deal_id=2,
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )

        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
            deal=deal2,
        )

        assert await Deal.exists()

        data = copy.deepcopy(basic_pd_deal_data())
        data[PDStatus.CURRENT].update(
            **{
                '345_hermes_id_678': f'{deal.id},{deal2.id}',
                'title': 'Old test deal',
                'org_id': 1,
                'person_id': 1,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'user_id': 1,
            }
        )
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(title='New test deal')
        r = await self.client.post(self.pipedrive_callback, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'New test deal'
        meeting2 = await Meeting.get(id=meeting.id)
        assert await meeting2.deal == deal

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_merged_hermes_ids(self, mock_pd_request):
        mock_pd_request.side_effect = fake_pd_request(self.pipedrive)

        self.pipedrive.db = {
            'organizations': {
                1: {
                    'id': 1,
                    'name': 'Test company',
                    'address_country': 'GB',
                    'owner_id': None,
                    '123_hermes_id_456': 1,
                }
            },
            'deals': {
                1: {
                    'title': 'Old test deal',
                    'org_id': 1,
                    'person_id': None,
                    'pipeline_id': 1,
                    'stage_id': 1,
                    'status': 'open',
                    'id': 1,
                    'user_id': 1,
                    '345_hermes_id_678': 1,
                },
                2: {
                    'title': 'Old test deal2',
                    'org_id': 1,
                    'person_id': None,
                    'pipeline_id': 1,
                    'stage_id': 1,
                    'status': 'open',
                    'id': 2,
                    'user_id': 1,
                    '345_hermes_id_678': 2,
                },
            },
            'persons': {
                1: {
                    'id': 1,
                    'name': 'Brian Blessed',
                    'email': 'brian@tc.com',
                    'org_id': 1,
                    '234_hermes_id_567': 1,
                },
                2: {
                    'id': 2,
                    'name': 'Brian Blessed',
                    'email': 'brian@tc.com',
                    'org_id': 1,
                    '234_hermes_id_567': 2,
                },
            },
            'pipelines': {
                1: {
                    'id': 1,
                    'name': 'Pipeline 1',
                    'dft_entry_stage_id': 1,
                }
            },
            'stages': {
                1: {
                    'id': 1,
                    'name': 'Stage 2',
                }
            },
        }

        admin = await Admin.create(
            tc2_admin_id=30,
            first_name='Brain',
            last_name='Johnson',
            username='brian@tc.com',
            password='foo',
            pd_owner_id=1,
        )

        company = await Company.create(name='Test company', pd_org_id=1, sales_person=admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=1, company=company)
        contact2 = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=2, company=company)
        await Deal.create(
            name='Old test deal',
            pd_deal_id=1,
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )
        await Deal.create(
            name='Old test deal2',
            pd_deal_id=2,
            company=company,
            contact=contact2,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )

        data = copy.deepcopy(basic_pd_person_data())
        data[PDStatus.CURRENT].update(
            **{
                '234_hermes_id_567': f'{contact.id},{contact2.id}',
                'name': 'Brian Blessed',
                'email': 'brian@tc.com',
                'org_id': 1,
                'owner_id': 1,
            }
        )
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])

        r = await self.client.post(self.pipedrive_callback, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'Brian Blessed'
