import copy
import re
from datetime import datetime, timedelta, timezone
from unittest import mock

from app.base_schema import build_custom_field_schema
from app.models import Admin, Company, Contact, Deal, Meeting, Pipeline, Stage, CustomField, CustomFieldValue
from app.pipedrive.tasks import (
    pd_post_process_sales_call,
    pd_post_process_support_call,
    pd_post_process_client_event,
)
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
    def _pd_request(*, url: str, method: str, data: dict):
        obj_type = re.search(r'/api/v1/(.*?)(?:/|\?api_token=)', url).group(1)
        obj_id = re.search(rf'/api/v1/{obj_type}/(\d+)', url)
        obj_id = obj_id and int(obj_id.group(1))
        if method == 'GET':
            if obj_id:
                return MockResponse(200, {'data': fake_pipedrive.db[obj_type][obj_id]})
            else:
                return MockResponse(200, {'data': list(fake_pipedrive.db[obj_type].values())})
        elif method == 'POST':
            obj_id = len(fake_pipedrive.db[obj_type].keys()) + 1
            data['id'] = obj_id
            fake_pipedrive.db[obj_type][obj_id] = data
            return MockResponse(200, {'data': fake_pipedrive.db[obj_type][obj_id]})
        else:
            assert method == 'PUT'
            fake_pipedrive.db[obj_type][obj_id].update(**data)
            return MockResponse(200, {'data': fake_pipedrive.db[obj_type][obj_id]})

    return _pd_request


class PipedriveTasksTestCase(HermesTestCase):
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

    @mock.patch('app.pipedrive.api.session.request')
    async def test_sales_call_booked(self, mock_request):
        """
        Test that the sales call flow creates the org, person, deal and activity in pipedrive. None of the objects
        already exist so should create one of each in PD.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Julies Ltd', country='GB', sales_person=admin)
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )
        await pd_post_process_sales_call(company, contact, meeting, deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                'id': 1,
                '123_hermes_id_456': company.id,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        assert (await Contact.get()).pd_person_id == 1
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': 1,
                'pipeline_id': (await Pipeline.get()).pd_pipeline_id,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                'user_id': 99,
                '345_hermes_id_678': deal.id,
            }
        }
        assert (await Deal.get()).pd_deal_id == 1
        assert self.pipedrive.db['activities'] == {
            1: {
                'id': 1,
                'due_date': '2023-01-01',
                'due_time': '00:00',
                'subject': 'TutorCruncher demo with Steve Jobs',
                'user_id': 99,
                'deal_id': 1,
                'person_id': 1,
                'org_id': 1,
            },
        }

    @mock.patch('app.pipedrive.api.session.request')
    async def test_sales_call_booked_with_custom_field(self, mock_request):
        """
        Test that the sales call flow creates the org, person, deal and activity in pipedrive. None of the objects
        already exist so should create one of each in PD.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        website_field = await CustomField.create(
            tc2_machine_name='website',
            pd_field_id='123_website_456',
            name='Website',
            field_type='str',
            linked_object_type='Company',
        )
        await build_custom_field_schema()

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Julies Ltd', country='GB', sales_person=admin)
        await CustomFieldValue.create(custom_field=website_field, company=company, value='https://junes.com')
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )
        await pd_post_process_sales_call(company, contact, meeting, deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                'id': 1,
                '123_website_456': 'https://junes.com',
                '123_hermes_id_456': company.id,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        assert (await Contact.get()).pd_person_id == 1
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': 1,
                'pipeline_id': (await Pipeline.get()).pd_pipeline_id,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                'user_id': 99,
                '345_hermes_id_678': deal.id,
            }
        }
        assert (await Deal.get()).pd_deal_id == 1
        assert self.pipedrive.db['activities'] == {
            1: {
                'id': 1,
                'due_date': '2023-01-01',
                'due_time': '00:00',
                'subject': 'TutorCruncher demo with Steve Jobs',
                'user_id': 99,
                'deal_id': 1,
                'person_id': 1,
                'org_id': 1,
            },
        }

        await website_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_support_call_booked_org_exists(self, mock_request):
        """
        Test that the support call workflow works. The company exists in Pipedrive so they should have an activity
        created for them.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )

        company = await Company.create(
            name='Julies Ltd', website='https://junes.com', country='GB', pd_org_id=10, sales_person=admin
        )
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 10,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
            },
        }
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        await pd_post_process_support_call(contact, meeting)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 10,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
            },
        }
        assert (await Company.get()).pd_org_id == 10
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 10,
                '234_hermes_id_567': contact.id,
            },
        }
        assert (await Contact.get()).pd_person_id == 1
        assert self.pipedrive.db['deals'] == {}
        assert not await Deal.exists()
        assert self.pipedrive.db['activities'] == {
            1: {
                'due_date': '2023-01-01',
                'due_time': '00:00',
                'subject': 'TutorCruncher demo with Steve Jobs',
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
        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )

        company = await Company.create(name='Julies Ltd', website='https://junes.com', country='GB', sales_person=admin)
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        await pd_post_process_support_call(contact, meeting)
        assert self.pipedrive.db['organizations'] == {}
        assert self.pipedrive.db['persons'] == {}
        assert self.pipedrive.db['deals'] == {}
        assert not await Deal.exists()
        assert self.pipedrive.db['activities'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_update_org_create_person_deal_exists(self, mock_request):
        """
        The org should be updated, the person should be created and since the
        deal is already in the db with a pd_deal_id, it shouldn't be created in PD.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(
            name='Julies Ltd', website='https://junes.com', country='GB', pd_org_id=1, sales_person=admin
        )
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'Junes Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
            },
        }
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=17,
        )
        await pd_post_process_sales_call(company=company, contact=contact, meeting=meeting, deal=deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
            },
        }
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        assert self.pipedrive.db['deals'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_create_org_create_person_with_owner_admin(self, mock_request):
        """
        The org should be created, the person should be created and since the
        deal is already in the db with a pd_deal_id, it shouldn't be created in PD.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        sales_person = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(
            name='Julies Ltd', website='https://junes.com', country='GB', sales_person=sales_person
        )
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=sales_person,
        )
        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=sales_person,
            pd_deal_id=17,
        )
        await pd_post_process_sales_call(company=company, contact=contact, meeting=meeting, deal=deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        assert (await Contact.get()).pd_person_id == 1

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_person_dont_need_update(self, mock_request):
        """
        This is basically testing that if the data in PD and the DB are up to date, we don't do the update request
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(
            name='Julies Ltd', website='https://junes.com', country='GB', pd_org_id=1, sales_person=admin
        )
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
            },
        }
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id, pd_person_id=1
        )
        self.pipedrive.db['persons'] = {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )
        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=17,
        )
        self.pipedrive.db['deals'] = {
            1: {
                'id': 1,
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': 1,
                'user_id': 99,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                '345_hermes_id_678': deal.id,
            }
        }
        await pd_post_process_sales_call(company, contact, meeting, deal)
        call_args = mock_request.call_args_list
        assert not any('PUT' in str(call) for call in call_args)

    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        await CustomField.create(
            name='TC2 status',
            field_type=CustomField.TYPE_STR,
            pd_field_id='123_tc2_status_456',
            hermes_field_name='tc2_status',
            linked_object_type='Company',
        )
        await build_custom_field_schema()

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(
            name='Julies Ltd',
            website='https://junes.com',
            country='GB',
            sales_person=admin,
            status=Company.STATUS_TRIAL,
        )
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        await pd_post_process_client_event(company)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
                '123_tc2_status_456': company.tc2_status,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        assert (await Contact.get()).pd_person_id == 1
        assert self.pipedrive.db['deals'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event_data_should_be_none(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        await CustomField.create(
            name='TC2 status',
            field_type=CustomField.TYPE_STR,
            pd_field_id='123_tc2_status_456',
            hermes_field_name='tc2_status',
            linked_object_type='Company',
        )
        await CustomField.create(
            name='TC2 cligency url',
            field_type=CustomField.TYPE_STR,
            pd_field_id='123_tc2_cligency_url_456',
            hermes_field_name='tc2_cligency_url',
            linked_object_type='Company',
        )
        await CustomField.create(
            name='Website',
            field_type=CustomField.TYPE_STR,
            pd_field_id='123_website_456',
            hermes_field_name='website',
            linked_object_type='Company',
        )
        await CustomField.create(
            name='Paid Invoice Count',
            field_type=CustomField.TYPE_INT,
            pd_field_id='123_paid_invoice_count_456',
            hermes_field_name='paid_invoice_count',
            linked_object_type='Company',
        )

        await build_custom_field_schema()

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(
            name='Julies Ltd',
            website='https://junes.com',
            country='GB',
            sales_person=admin,
            status=Company.STATUS_TRIAL,
        )
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        await pd_post_process_client_event(company)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
                '123_tc2_status_456': company.tc2_status,
                '123_tc2_cligency_url_456': company.tc2_cligency_url,
                '123_website_456': company.website,
                '123_paid_invoice_count_456': company.paid_invoice_count,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        assert (await Contact.get()).pd_person_id == 1
        assert self.pipedrive.db['deals'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event_with_deal(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Julies Ltd', website='https://junes.com', country='GB', sales_person=admin)
        contact = await Contact.create(
            first_name='Brian',
            last_name='Junes',
            email='brain@junes.com',
            company_id=company.id,
            pd_person_id=1,
        )
        self.pipedrive.db['persons'] = {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        deal = await Deal.create(
            name='Julies Ltd',
            status=Deal.STATUS_OPEN,
            admin=admin,
            company=company,
            contact=contact,
            stage=self.stage,
            pipeline=self.pipeline,
        )
        await pd_post_process_client_event(company, deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': ['brain@junes.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        assert (await Contact.get()).pd_person_id == 1
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'Julies Ltd',
                'org_id': 1,
                'person_id': 1,
                'user_id': 99,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                '345_hermes_id_678': deal.id,
            },
        }
        assert (await Deal.get()).pd_deal_id == 1


def basic_pd_org_data():
    return {
        'v': 1,
        'matches_filters': {'current': []},
        'meta': {'action': 'updated', 'object': 'organization'},
        'current': {'owner_id': 10, 'id': 20, 'name': 'Test company', 'address_country': None},
        'previous': {},
        'event': 'updated.organization',
    }


def basic_pd_person_data():
    return {
        'v': 1,
        'matches_filters': {'current': []},
        'meta': {'action': 'updated', 'object': 'person'},
        'current': {
            'owner_id': 10,
            'id': 30,
            'name': 'Brian Blessed',
            'email': [''],
            'phone': [{'value': '0208112555', 'primary': 'true'}],
            'org_id': 20,
        },
        'previous': {},
        'event': 'updated.person',
    }


def basic_pd_deal_data():
    return {
        'v': 1,
        'matches_filters': {'current': []},
        'meta': {'action': 'updated', 'object': 'deal'},
        'current': {
            'id': 40,
            'person_id': 30,
            'stage_id': 50,
            'close_time': None,
            'org_id': 20,
            'status': 'open',
            'title': 'Deal 1',
            'pipeline_id': 60,
            'user_id': 10,
        },
        'previous': {},
        'event': 'updated.deal',
    }


def basic_pd_pipeline_data():
    return {
        'v': 1,
        'matches_filters': {'current': []},
        'meta': {'action': 'updated', 'object': 'pipeline'},
        'current': {'name': 'Pipeline 1', 'id': 60, 'active': True},
        'previous': {},
        'event': 'updated.pipeline',
    }


def basic_pd_stage_data():
    return {
        'v': 1,
        'matches_filters': {'current': []},
        'meta': {'action': 'updated', 'object': 'stage'},
        'current': {'name': 'Stage 1', 'pipeline_id': 60, 'id': 50},
        'previous': {},
        'event': 'updated.stage',
    }


class PipedriveCallbackTestCase(HermesTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.pipedrive = FakePipedrive()
        self.admin = await Admin.create(pd_owner_id=10, username='testing@example.com', is_sales_person=True)
        self.url = '/pipedrive/callback/'
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

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_create(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        assert not await Company.exists()
        r = await self.client.post(self.url, json=basic_pd_org_data())
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.sales_person_id == self.admin.id

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_create_no_custom_fields(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        await CustomField.all().delete()
        await build_custom_field_schema()

        assert not await Company.exists()
        r = await self.client.post(self.url, json=basic_pd_org_data())
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.sales_person_id == self.admin.id

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_create_with_custom_hermes_field(self, mock_request):
        website_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_website_456',
            hermes_field_name='website',
            tc2_machine_name='website',
            name='Website',
            field_type='str',
        )
        await build_custom_field_schema()
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        assert not await Company.exists()
        data = copy.deepcopy(basic_pd_org_data())
        data['current']['123_website_456'] = 'https://junes.com'
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.sales_person_id == self.admin.id
        assert company.website == 'https://junes.com'
        assert not await CustomFieldValue.all().count()

        await website_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_create_with_custom_field_val(self, mock_request):
        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_source_456',
            name='Source',
            field_type='str',
        )
        await build_custom_field_schema()

        mock_request.side_effect = fake_pd_request(self.pipedrive)
        assert not await Company.exists()
        data = copy.deepcopy(basic_pd_org_data())
        data['current']['123_source_456'] = 'Google'

        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.sales_person_id == self.admin.id
        cf_val = await CustomFieldValue.get()
        assert cf_val.value == 'Google'
        assert await cf_val.custom_field == source_field
        assert await cf_val.company == company

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_create_with_cf_hermes_default(self, mock_request):
        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_paid_invoice_count_456',
            hermes_field_name='paid_invoice_count',
            name='Paid Invoice Count',
            field_type='int',
        )
        await build_custom_field_schema()

        mock_request.side_effect = fake_pd_request(self.pipedrive)
        assert not await Company.exists()
        data = copy.deepcopy(basic_pd_org_data())

        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.sales_person_id == self.admin.id

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_create_with_no_old_cf_vals(self, mock_request):
        company = await Company.create(
            name='Julies Ltd',
            website='https://junes.com',
            country='GB',
            status=Company.STATUS_TRIAL,
            sales_person=self.admin,
        )

        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_source_456',
            name='Source',
            field_type='str',
        )
        await build_custom_field_schema()

        mock_request.side_effect = fake_pd_request(self.pipedrive)
        assert await Company.exists()
        data = copy.deepcopy(basic_pd_org_data())
        data['current'] = data.pop('current')
        data['current']['123_source_456'] = 'Google'
        data['current']['123_hermes_id_456'] = company.id

        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.sales_person_id == self.admin.id
        cf_val = await CustomFieldValue.get()
        assert cf_val.value == 'Google'
        assert await cf_val.custom_field == source_field
        assert await cf_val.company == company

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_create_owner_doesnt_exist(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        data = copy.deepcopy(basic_pd_org_data())
        data['current']['owner_id'] = 999
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 422, r.json()
        assert r.json() == {
            'detail': [{'loc': ['owner_id'], 'msg': 'Admin with pd_owner_id 999 does not exist', 'type': 'value_error'}]
        }

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_delete(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        assert await Company.exists()
        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = data.pop('current')
        data['previous']['hermes_id'] = company.id
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Company.exists()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_delete_with_custom_field_val(self, mock_request):
        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_source_456',
            name='Source',
            field_type='str',
        )
        await build_custom_field_schema()
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)

        await CustomFieldValue.create(custom_field=source_field, company=company, value='Bing')

        assert await Company.exists()
        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = data.pop('current')
        data['previous']['hermes_id'] = company.id
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Company.exists()

        assert not await CustomFieldValue.exists()

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Old test company', sales_person=self.admin)
        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['previous'].update(hermes_id=company.id)
        data['current'].update(name='New test company')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_with_custom_hermes_field(self, mock_request):
        website_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_website_456',
            hermes_field_name='website',
            tc2_machine_name='website',
            name='Website',
            field_type='str',
        )
        await build_custom_field_schema()

        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Old test company', sales_person=self.admin)
        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['previous'].update(hermes_id=company.id)
        data['current'].update(**{'name': 'New test company', '123_website_456': 'https://newjunes.com'})
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'
        assert company.website == 'https://newjunes.com'

        await website_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_custom_field_val_created(self, mock_request):
        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_source_456',
            name='Source',
            field_type='str',
        )
        await build_custom_field_schema()

        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Old test company', sales_person=self.admin)
        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['previous'].update(hermes_id=company.id)
        data['current'].update(**{'name': 'New test company', '123_source_456': 'Google'})
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'

        cf_val = await CustomFieldValue.get()
        assert cf_val.value == 'Google'
        assert await cf_val.custom_field == source_field

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_custom_field_val_updated(self, mock_request):
        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_source_456',
            name='Source',
            field_type='str',
        )
        await build_custom_field_schema()
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Old test company', sales_person=self.admin)

        await CustomFieldValue.create(custom_field=source_field, company=company, value='Bing')

        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['previous'].update(hermes_id=company.id)
        data['current'].update(**{'name': 'New test company', '123_source_456': 'Google'})
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'

        cf_val = await CustomFieldValue.get()
        assert cf_val.value == 'Google'
        assert await cf_val.custom_field == source_field

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_custom_field_val_deleted(self, mock_request):
        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_source_456',
            name='Source',
            field_type='str',
        )
        await build_custom_field_schema()
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Old test company', sales_person=self.admin)

        await CustomFieldValue.create(custom_field=source_field, company=company, value='Bing')

        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['previous'].update(hermes_id=company.id)
        data['current'].update(**{'name': 'New test company'})
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'

        assert not await CustomFieldValue.exists()

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_no_changes(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Old test company', sales_person=self.admin)
        data = copy.deepcopy(basic_pd_org_data())
        data['current']['hermes_id'] = company.id
        data['previous'] = copy.deepcopy(data['current'])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Old test company'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_doesnt_exist(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['current'].update(name='New test company')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_create(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        assert not await Contact.exists()
        r = await self.client.post(self.url, json=basic_pd_person_data())
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.first_name == 'Brian'
        assert contact.last_name == 'Blessed'
        assert await contact.company == company
        assert contact.phone == '0208112555'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_create_company_doesnt_exist(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        data = copy.deepcopy(basic_pd_person_data())
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Contact.exists()
        assert not await Company.exists()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_delete(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', company=company)
        assert await Contact.exists()
        data = copy.deepcopy(basic_pd_person_data())
        data['previous'] = data.pop('current')
        data['previous']['hermes_id'] = contact.id
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Contact.exists()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='John', last_name='Smith', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_person_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['previous']['hermes_id'] = contact.id
        data['current'].update(name='Jessica Jones')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'Jessica Jones'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_no_changes(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='John', last_name='Smith', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_person_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['previous']['hermes_id'] = contact.id
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'John Smith'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_doesnt_exist(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        data = copy.deepcopy(basic_pd_person_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['current'].update(name='Brimstone')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'Brimstone'

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_create(self, mock_add_task):
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        assert not await Deal.exists()
        r = await self.client.post(self.url, json=basic_pd_deal_data())
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'Deal 1'
        assert await deal.company == company
        assert await deal.contact == contact
        assert await deal.stage == stage
        assert await deal.admin == self.admin

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_create_owner_doesnt_exist(self, mock_add_task):
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_deal_data())
        data['current']['user_id'] = 999
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 422, r.json()
        assert r.json() == {
            'detail': [{'loc': ['user_id'], 'msg': 'Admin with pd_owner_id 999 does not exist', 'type': 'value_error'}]
        }

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_create_stage_doesnt_exist(self, mock_add_task):
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_deal_data())
        data['current']['stage_id'] = 999
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 422, r.json()
        assert r.json() == {
            'detail': [{'loc': ['stage_id'], 'msg': 'Stage with pd_stage_id 999 does not exist', 'type': 'value_error'}]
        }

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_create_pipeline_doesnt_exist(self, mock_add_task):
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_deal_data())
        data['current']['pipeline_id'] = 999
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 422, r.json()
        assert r.json() == {
            'detail': [
                {
                    'loc': ['pipeline_id'],
                    'msg': 'Pipeline with pd_pipeline_id 999 does not exist',
                    'type': 'value_error',
                }
            ]
        }

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_create_contact_doesnt_exist(self, mock_add_task):
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_deal_data())
        data['current']['person_id'] = 999
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'Deal 1'
        assert await deal.company == company
        assert not await deal.contact
        assert await deal.stage == stage
        assert await deal.admin == self.admin

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_delete(self, mock_add_task):
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', company=company)
        deal = await Deal.create(
            name='Test deal',
            pd_deal_id=40,
            company=company,
            contact=contact,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
        )
        assert await Deal.exists()
        data = copy.deepcopy(basic_pd_deal_data())
        data['previous'] = data.pop('current')
        data['previous']['hermes_id'] = deal.id
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Deal.exists()

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_update_reeeee(self, mock_add_task):
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        deal = await Deal.create(
            name='Old test deal',
            pd_deal_id=40,
            company=company,
            contact=contact,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
        )
        assert await Deal.exists()

        data = copy.deepcopy(basic_pd_deal_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['previous']['hermes_id'] = deal.id
        data['current'].update(title='New test deal')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'New test deal'

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_update_no_changes(self, mock_add_task):
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        deal = await Deal.create(
            name='Old test deal',
            pd_deal_id=40,
            company=company,
            contact=contact,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
        )
        assert await Deal.exists()
        data = copy.deepcopy(basic_pd_deal_data())
        data['current']['hermes_id'] = deal.id
        data['previous'] = copy.deepcopy(data['current'])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'Old test deal'

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_update_doesnt_exist(self, mock_add_task):
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_deal_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['current'].update(title='New test deal')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'New test deal'

    async def test_pipeline_create(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        r = await self.client.post(self.url, json=basic_pd_pipeline_data())
        assert r.status_code == 200, r.json()
        pipeline = await Pipeline.get()
        assert pipeline.name == 'Pipeline 1'
        assert pipeline.pd_pipeline_id == 60

    async def test_pipeline_delete(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Pipeline.create(name='Pipeline 1', pd_pipeline_id=60)
        data = copy.deepcopy(basic_pd_pipeline_data())
        data['previous'] = data.pop('current')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Pipeline.exists()

    async def test_pipeline_update(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Pipeline.create(name='Old Pipeline', pd_pipeline_id=60)
        data = copy.deepcopy(basic_pd_pipeline_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['current'].update(name='New Pipeline')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        pipeline = await Pipeline.get()
        assert pipeline.name == 'New Pipeline'

    async def test_pipeline_update_no_changes(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Pipeline.create(name='Old Pipeline', pd_pipeline_id=60)
        data = copy.deepcopy(basic_pd_pipeline_data())
        data['previous'] = copy.deepcopy(data['current'])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        pipeline = await Pipeline.get()
        assert pipeline.name == 'Old Pipeline'

    async def test_pipeline_update_doesnt_exist(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        data = copy.deepcopy(basic_pd_pipeline_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['current'].update(name='New test pipeline')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        pipeline = await Pipeline.get()
        assert pipeline.name == 'New test pipeline'

    async def test_stage_create(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        r = await self.client.post(self.url, json=basic_pd_stage_data())
        assert r.status_code == 200, r.json()
        stage = await Stage.get()
        assert stage.name == 'Stage 1'
        assert stage.pd_stage_id == 50

    async def test_stage_delete(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Stage.create(name='Stage 1', pd_stage_id=50)
        data = copy.deepcopy(basic_pd_stage_data())
        data['previous'] = data.pop('current')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Stage.exists()

    async def test_stage_update(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Stage.create(name='Stage 1', pd_stage_id=50)
        data = copy.deepcopy(basic_pd_stage_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['current'].update(name='New Stage')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        stage = await Stage.get()
        assert stage.name == 'New Stage'

    async def test_stage_update_no_changes(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Stage.create(name='Old Stage', pd_stage_id=50)
        data = copy.deepcopy(basic_pd_stage_data())
        data['previous'] = copy.deepcopy(data['current'])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        stage = await Stage.get()
        assert stage.name == 'Old Stage'

    async def test_stage_update_doesnt_exist(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        data = copy.deepcopy(basic_pd_stage_data())
        data['previous'] = copy.deepcopy(data['current'])
        data['current'].update(name='New test stage')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        stage = await Stage.get()
        assert stage.name == 'New test stage'
