import copy
import re
from datetime import datetime, timedelta, timezone
from unittest import mock
from urllib.parse import parse_qs

from app.base_schema import build_custom_field_schema
from app.models import Admin, Company, Contact, CustomField, CustomFieldValue, Deal, Meeting, Pipeline, Stage
from app.pipedrive._schema import PDStatus
from app.pipedrive.tasks import (
    pd_post_process_client_event,
    pd_post_process_sales_call,
    pd_post_process_support_call,
    pd_post_purge_client_event,
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
        extra_path = re.search(rf'/api/v1/{obj_type}/(.*?)(?=\?)', url)
        extra_path = extra_path and extra_path.group(1)
        obj_id = re.search(rf'/api/v1/{obj_type}/(\d+)', url)
        obj_id = obj_id and int(obj_id.group(1))
        if method == 'GET':
            if obj_id:
                return MockResponse(200, {'data': fake_pipedrive.db[obj_type][obj_id]})
            else:
                # if object type includes /search then it's a search request
                if 'search' in extra_path:
                    search_term = parse_qs(re.search(r'\?(.*)', url).group(1))['term'][0]
                    objs = [
                        obj
                        for obj in fake_pipedrive.db[obj_type].values()
                        if any(search_term in str(v) for v in obj.values())
                    ]
                    return MockResponse(200, {'data': {'items': [{'item': i} for i in objs]}})
                else:
                    return MockResponse(200, {'data': list(fake_pipedrive.db[obj_type].values())})
        elif method == 'POST':
            obj_id = len(fake_pipedrive.db[obj_type].keys()) + 1
            data['id'] = obj_id
            fake_pipedrive.db[obj_type][obj_id] = data
            return MockResponse(200, {'data': fake_pipedrive.db[obj_type][obj_id]})
        elif method == 'PUT':
            fake_pipedrive.db[obj_type][obj_id].update(**data)
            return MockResponse(200, {'data': fake_pipedrive.db[obj_type][obj_id]})
        else:
            assert method == 'DELETE'
            del fake_pipedrive.db[obj_type][obj_id]
            return MockResponse(200, {'data': {'id': obj_id}})

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
    async def test_sales_call_booked_with_bdr(self, mock_request):
        """
        Test that the sales call flow creates the org, person, deal and activity in pipedrive. None of the objects
        already exist so should create one of each in PD.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_bdr_person_id_456',
            name='BDR person',
            hermes_field_name='bdr_person',
            field_type=CustomField.TYPE_FK_FIELD,
        )
        await build_custom_field_schema()

        sales_person = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        bdr_person = await Admin.create(
            first_name='Brian',
            last_name='Jacques',
            username='bdr@example.com',
            is_bdr_person=True,
            tc2_admin_id=22,
            pd_owner_id=101,
        )
        company = await Company.create(
            name='Julies Ltd', country='GB', sales_person=sales_person, bdr_person=bdr_person
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
        )
        await pd_post_process_sales_call(company, contact, meeting, deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                'id': 1,
                '123_hermes_id_456': company.id,
                '123_bdr_person_id_456': bdr_person.id,
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
        deal is already in the db with a pd_deal_id, it a new one shouldn't be created in PD.
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
            pd_deal_id=1,
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

    @mock.patch('app.pipedrive.api.session.request')
    async def test_create_org_create_person_with_owner_admin(self, mock_request):
        """
        The org should be created, the person should be created and since the
        deal is already in the db with a pd_deal_id, a new deal shouldn't be created in PD.
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

        self.pipedrive.db['deals'] = {
            17: {
                'id': 17,
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
            pd_deal_id=1,
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
    async def test_company_narc_delete_org_person_deal(self, mock_request):
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
            name='Julies Ltd', website='https://junes.com', country='GB', pd_org_id=1, sales_person=admin, narc=True
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
        await Meeting.create(
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
            pd_deal_id=1,
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
        await pd_post_purge_client_event(company, deal)
        call_args = mock_request.call_args_list
        assert all('DELETE' in str(call) for call in call_args)

        assert self.pipedrive.db['organizations'] == {}
        assert self.pipedrive.db['persons'] == {}
        assert self.pipedrive.db['deals'] == {}

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

        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=None,
        )

        await pd_post_process_client_event(company, deal)
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
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': None,
                'user_id': 99,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                '345_hermes_id_678': deal.id,
            }
        }

        assert await Deal.all().count() == 1


    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event_company_cf_on_deal(self, mock_request):
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

        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=None,
        )

        await pd_post_process_client_event(company, deal)
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
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': None,
                'user_id': 99,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                '345_hermes_id_678': deal.id,
            }
        }

        assert await Deal.all().count() == 1

    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event_narc_no_pd(self, mock_request):
        """
        Test that if the company is NARC, we don't create the org in PD.
        """
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
            narc=True,
        )
        await Contact.create(first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id)
        await pd_post_purge_client_event(company)
        assert self.pipedrive.db['organizations'] == {}
        assert (await Company.get()).pd_org_id is None
        assert self.pipedrive.db['persons'] == {}
        assert (await Contact.get()).pd_person_id is None
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
            name='TC2 color',
            field_type=CustomField.TYPE_STR,
            pd_field_id='123_tc2_color_456',
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
                '123_tc2_color_456': None,
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
        self.pipedrive.db['organizations'] = {1: {'id': 1, 'name': 'Julies Ltd', 'address_country': 'GB'}}
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
                'organization': {'id': 1},
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
                'organization': {'id': 1},
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

    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event_org_exists_linked_by_company_id(self, mock_request):
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
            tc2_cligency_id=444444,
        )
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_tc2_cligency_id_456': 444444,
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
            pd_deal_id=None,
        )

        await pd_post_process_client_event(company, deal)
        assert self.pipedrive.db['organizations'] == {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
                '123_hermes_id_456': company.id,
                '123_tc2_status_456': company.tc2_status,
                '123_tc2_cligency_id_456': 444444,
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
                'person_id': None,
                'user_id': 99,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                '345_hermes_id_678': deal.id,
            }
        }

        assert await Deal.all().count() == 1

    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event_org_exists_linked_by_contacts_emails(self, mock_request):
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
            tc2_cligency_id=444444,
        )
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
            },
        }
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        self.pipedrive.db['persons'] = {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': 'brain@junes.com',
                'phone': None,
                'organization': {'id': 1},
            },
        }

        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=None,
        )

        await pd_post_process_client_event(company, deal)
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
        assert len(self.pipedrive.db['persons']) == 2  # We don't do get_or_create for persons, we just create them.
        assert (await Contact.get()).pd_person_id == 2
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': None,
                'user_id': 99,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                '345_hermes_id_678': deal.id,
            }
        }

        assert await Deal.all().count() == 1

    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event_org_exists_linked_by_contacts_phones(self, mock_request):
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
            tc2_cligency_id=444444,
        )
        self.pipedrive.db['organizations'] = {
            1: {
                'id': 1,
                'name': 'Julies Ltd',
                'address_country': 'GB',
                'owner_id': 99,
            },
        }
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='junebug@junes.com', company_id=company.id, phone=235689
        )
        self.pipedrive.db['persons'] = {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': 'brain@junes.com',
                'phone': 235689,
                'organization': {'id': 1},
            },
        }

        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=None,
        )

        await pd_post_process_client_event(company, deal)
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
        assert len(self.pipedrive.db['persons']) == 2  # We don't do get_or_create for persons, we just create them.
        assert (await Contact.get()).pd_person_id == 2
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': None,
                'user_id': 99,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                '345_hermes_id_678': deal.id,
            }
        }

        assert await Deal.all().count() == 1

    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event_org_exists_contact_exists_no_org(self, mock_request):
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
            tc2_cligency_id=444444,
        )
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='junebug@junes.com', company_id=company.id, phone=235689
        )
        self.pipedrive.db['persons'] = {
            1: {
                'id': 1,
                'name': 'Brian Junes',
                'owner_id': 99,
                'email': 'brain@junes.com',
                'phone': 235689,
            },
        }

        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=None,
        )

        await pd_post_process_client_event(company, deal)
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
        assert len(self.pipedrive.db['persons']) == 2  # We don't do get_or_create for persons, we just create them.
        assert (await Contact.get()).pd_person_id == 2
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': None,
                'user_id': 99,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                'id': 1,
                '345_hermes_id_678': deal.id,
            }
        }

        assert await Deal.all().count() == 1

    @mock.patch('app.pipedrive.api.session.request')
    async def test_update_deal(self, mock_request):
        """
        The org should be updated, the person should be created and deal gets updated
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
            name='A deal with Julies Ltd 2',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=1,
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
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd 2',
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


def basic_pd_org_data():
    return {
        'v': 1,
        'matches_filters': {PDStatus.CURRENT: []},
        'meta': {'action': 'updated', 'object': 'organization'},
        PDStatus.CURRENT: {'owner_id': 10, 'id': 20, 'name': 'Test company', 'address_country': None},
        PDStatus.PREVIOUS: None,
        'event': 'updated.organization',
    }


def basic_pd_person_data():
    return {
        'v': 1,
        'matches_filters': {PDStatus.CURRENT: []},
        'meta': {'action': 'updated', 'object': 'person'},
        PDStatus.CURRENT: {
            'owner_id': 10,
            'id': 30,
            'name': 'Brian Blessed',
            'email': [''],
            'phone': [{'value': '0208112555', 'primary': 'true'}],
            'org_id': 20,
        },
        PDStatus.PREVIOUS: {},
        'event': 'updated.person',
    }


def basic_pd_deal_data():
    return {
        'v': 1,
        'matches_filters': {PDStatus.CURRENT: []},
        'meta': {'action': 'updated', 'object': 'deal'},
        PDStatus.CURRENT: {
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
        PDStatus.PREVIOUS: None,
        'event': 'updated.deal',
    }


def basic_pd_pipeline_data():
    return {
        'v': 1,
        'matches_filters': {PDStatus.CURRENT: []},
        'meta': {'action': 'updated', 'object': 'pipeline'},
        PDStatus.CURRENT: {'name': 'Pipeline 1', 'id': 60, 'active': True},
        PDStatus.PREVIOUS: {},
        'event': 'updated.pipeline',
    }


def basic_pd_stage_data():
    return {
        'v': 1,
        'matches_filters': {PDStatus.CURRENT: []},
        'meta': {'action': 'updated', 'object': 'stage'},
        PDStatus.CURRENT: {'name': 'Stage 1', 'pipeline_id': 60, 'id': 50},
        PDStatus.PREVIOUS: {},
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
    async def test_org_create_with_hermes_id_company_missing(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        assert not await Company.exists()
        data = copy.deepcopy(basic_pd_org_data())
        data[PDStatus.CURRENT]['123_hermes_id_456'] = 75
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 422, r.json()
        assert r.json() == {
            'detail': [
                {
                    'loc': [
                        'hermes_id',
                    ],
                    'msg': 'Company with id 75 does not exist',
                    'type': 'value_error',
                },
            ],
        }

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
        data[PDStatus.CURRENT]['123_website_456'] = 'https://junes.com'
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
        data[PDStatus.CURRENT]['123_source_456'] = 'Google'

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
        data[PDStatus.CURRENT]['123_paid_invoice_count_456'] = None

        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.sales_person_id == self.admin.id

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_create_with_cf_hermes_no_default(self, mock_request):
        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_tc2_cligency_url_456',
            hermes_field_name='tc2_cligency_url',
            name='TC2 Cligency URL',
            field_type='str',
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
        data[PDStatus.CURRENT] = data.pop(PDStatus.CURRENT)
        data[PDStatus.CURRENT]['123_source_456'] = 'Google'
        data[PDStatus.CURRENT]['123_hermes_id_456'] = company.id

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
        data[PDStatus.CURRENT]['owner_id'] = 999
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
        data[PDStatus.PREVIOUS] = data.pop(PDStatus.CURRENT)
        data[PDStatus.PREVIOUS]['hermes_id'] = company.id
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
        data[PDStatus.PREVIOUS] = data.pop(PDStatus.CURRENT)
        data[PDStatus.PREVIOUS]['hermes_id'] = company.id
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
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(hermes_id=company.id)
        data[PDStatus.CURRENT].update(name='New test company')
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
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(hermes_id=company.id)
        data[PDStatus.CURRENT].update(**{'name': 'New test company', '123_website_456': 'https://newjunes.com'})
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'
        assert company.website == 'https://newjunes.com'

        await website_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_signup_questionnaire_custom_field(self, mock_request):
        website_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_signup_questionnaire_456',
            hermes_field_name='signup_questionnaire',
            tc2_machine_name='signup_questionnaire',
            name='Signup Questionnaire',
            field_type='str',
        )
        await build_custom_field_schema()

        mock_request.side_effect = fake_pd_request(self.pipedrive)

        company = await Company.create(
            name='Old test company',
            sales_person=self.admin,
            signup_questionnaire={
                'question1': 'answer1',
                'question2': 'answer2',
            },
        )
        data = copy.deepcopy(basic_pd_org_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(
            hermes_id=company.id, **{'123_signup_questionnaire_456': '{"question1": "answer1", "question2": "answer2"}'}
        )
        data[PDStatus.CURRENT].update(
            **{
                'name': 'New test company',
                '123_signup_questionnaire_456': '{"question1": "answer123", "question2": "answer2456"}',
            }
        )
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'
        assert company.signup_questionnaire == {
            'question1': 'answer1',
            'question2': 'answer2',
        }

        await website_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_merged(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Old test company', sales_person=self.admin)
        company2 = await Company.create(name='Old test company2', sales_person=self.admin)
        contact2 = await Contact.create(first_name='John', last_name='Smith', pd_person_id=31, company=company2)
        deal2 = await Deal.create(
            name='Test deal',
            pd_deal_id=40,
            company=company2,
            contact=contact2,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
        )

        data = copy.deepcopy(basic_pd_org_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(**{'123_hermes_id_456': f'{company.id},{company2.id}'})
        data[PDStatus.CURRENT].update(**{'name': 'New test company'})
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'
        contact_2 = await Contact.get(id=contact2.id)
        assert await contact_2.company == company
        deal_2 = await Deal.get(id=deal2.id)
        assert await deal_2.company == company

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
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(hermes_id=company.id)
        data[PDStatus.CURRENT].update(**{'name': 'New test company', '123_source_456': 'Google'})
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
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(hermes_id=company.id)
        data[PDStatus.CURRENT].update(**{'name': 'New test company', '123_source_456': 'Google'})
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
    async def test_org_update_associated_custom_fk_field(self, mock_request):
        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )

        support_person_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_support_person_id_456',
            hermes_field_name='support_person',
            name='Support Person ID',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        await build_custom_field_schema()
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Old test company', sales_person=self.admin)

        await CustomFieldValue.create(custom_field=support_person_field, company=company, value=admin.id)

        data = copy.deepcopy(basic_pd_org_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(hermes_id=company.id)
        data[PDStatus.CURRENT].update(
            **{
                'name': 'New test company',
                '123_support_person_id_456': admin.id,
            }
        )
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'

        cf_val = await CustomFieldValue.get()
        assert cf_val.value == str(admin.id)
        assert await cf_val.custom_field == support_person_field

        await support_person_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_associated_custom_fk_field_error(self, mock_request):
        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )

        support_person_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_support_person_id_456',
            hermes_field_name='support_person',
            name='Support Person ID',
            field_type=CustomField.TYPE_FK_FIELD,
        )

        await build_custom_field_schema()
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Old test company', sales_person=self.admin)

        await CustomFieldValue.create(custom_field=support_person_field, company=company, value=admin.id)

        data = copy.deepcopy(basic_pd_org_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(hermes_id=company.id)
        data[PDStatus.CURRENT].update(
            **{
                'name': 'New test company',
                '123_support_person_id_456': 400,
            }
        )
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 422  # valadation error

        await support_person_field.delete()
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
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(hermes_id=company.id)
        data[PDStatus.CURRENT].update(**{'name': 'New test company'})
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
        data[PDStatus.CURRENT]['hermes_id'] = company.id
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Old test company'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_doesnt_exist(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        data = copy.deepcopy(basic_pd_org_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(name='New test company')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_no_hermes_id(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        await Company.create(name='Old test company', sales_person=self.admin, pd_org_id=20)
        data = copy.deepcopy(basic_pd_org_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(name='New test company')
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
        data[PDStatus.PREVIOUS] = data.pop(PDStatus.CURRENT)
        data[PDStatus.PREVIOUS]['hermes_id'] = contact.id
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Contact.exists()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='John', last_name='Smith', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_person_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS]['hermes_id'] = contact.id
        data[PDStatus.CURRENT].update(name='Jessica Jones')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'Jessica Jones'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_merged(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='John', last_name='Smith', pd_person_id=30, company=company)
        contact_2 = await Contact.create(first_name='John', last_name='Smith', pd_person_id=31, company=company)
        deal2 = await Deal.create(
            name='Test deal',
            pd_deal_id=40,
            company=company,
            contact=contact_2,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
        )

        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact_2,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=self.admin,
        )

        data = copy.deepcopy(basic_pd_person_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(**{'234_hermes_id_567': f'{contact.id},{contact_2.id}'})
        data[PDStatus.CURRENT].update(name='Jessica Jones')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'Jessica Jones'
        deal2 = await Deal.get(id=deal2.id)
        assert await deal2.contact == contact
        meeting2 = await Meeting.get(id=meeting.id)
        assert await meeting2.contact == contact

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_no_changes(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='John', last_name='Smith', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_person_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS]['hermes_id'] = contact.id
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'John Smith'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_no_hermes_id(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        await Contact.create(first_name='John', last_name='Smith', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_person_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'John Smith'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_doesnt_exist(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        data = copy.deepcopy(basic_pd_person_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(name='Brimstone')
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
        data[PDStatus.CURRENT]['user_id'] = 999
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
        data[PDStatus.CURRENT]['stage_id'] = 999
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
        data[PDStatus.CURRENT]['pipeline_id'] = 999
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
        data[PDStatus.CURRENT]['person_id'] = 999
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
        data[PDStatus.PREVIOUS] = data.pop(PDStatus.CURRENT)
        data[PDStatus.PREVIOUS]['hermes_id'] = deal.id
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Deal.exists()

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_update(self, mock_add_task):
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
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS]['hermes_id'] = deal.id
        data[PDStatus.CURRENT].update(title='New test deal')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'New test deal'

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_update_merged(self, mock_add_task):
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
        deal2 = await Deal.create(
            name='Old test deal2',
            pd_deal_id=41,
            company=company,
            contact=contact,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
        )

        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=self.admin,
            deal=deal2,
        )

        assert await Deal.exists()

        data = copy.deepcopy(basic_pd_deal_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(**{'345_hermes_id_678': f'{deal.id},{deal2.id}', 'title': 'New test deal'})
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'New test deal'
        meeting2 = await Meeting.get(id=meeting.id)
        assert await meeting2.deal == deal

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_update_merged_previous(self, mock_add_task):
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
        deal2 = await Deal.create(
            name='Old test deal2',
            pd_deal_id=41,
            company=company,
            contact=contact,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
        )

        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SALES,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=self.admin,
            deal=deal2,
        )

        assert await Deal.exists()

        data = copy.deepcopy(basic_pd_deal_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.PREVIOUS].update(**{'345_hermes_id_678': f'{deal.id},{deal2.id}'})
        data[PDStatus.CURRENT].update(title='New test deal')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'New test deal'
        meeting2 = await Meeting.get(id=meeting.id)
        assert await meeting2.deal == deal

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
        data[PDStatus.CURRENT]['hermes_id'] = deal.id
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
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
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(title='New test deal')
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
        data[PDStatus.PREVIOUS] = data.pop(PDStatus.CURRENT)
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Pipeline.exists()

    async def test_pipeline_update(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Pipeline.create(name='Old Pipeline', pd_pipeline_id=60)
        data = copy.deepcopy(basic_pd_pipeline_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(name='New Pipeline')
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
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        pipeline = await Pipeline.get()
        assert pipeline.name == 'Old Pipeline'

    async def test_pipeline_update_doesnt_exist(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        data = copy.deepcopy(basic_pd_pipeline_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(name='New test pipeline')
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
        data[PDStatus.PREVIOUS] = data.pop(PDStatus.CURRENT)
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Stage.exists()

    async def test_stage_update(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Stage.create(name='Stage 1', pd_stage_id=50)
        data = copy.deepcopy(basic_pd_stage_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(name='New Stage')
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
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        stage = await Stage.get()
        assert stage.name == 'Old Stage'

    async def test_stage_update_doesnt_exist(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        data = copy.deepcopy(basic_pd_stage_data())
        data[PDStatus.PREVIOUS] = copy.deepcopy(data[PDStatus.CURRENT])
        data[PDStatus.CURRENT].update(name='New test stage')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        stage = await Stage.get()
        assert stage.name == 'New test stage'
