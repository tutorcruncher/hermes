from datetime import date, datetime, timedelta, timezone
from unittest import mock
from unittest.mock import PropertyMock

from app.base_schema import build_custom_field_schema
from app.models import Admin, Company, Contact, CustomField, CustomFieldValue, Deal, Meeting, Pipeline
from app.pipedrive._process import update_or_create_inherited_deal_custom_field_values
from app.pipedrive._schema import Organisation
from app.pipedrive.tasks import (
    pd_post_process_client_event,
    pd_post_process_sales_call,
    pd_post_process_support_call,
    pd_post_purge_client_event,
)
from tests._common import HermesTestCase
from tests.pipedrive.helpers import FakePipedrive, fake_pd_request


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

    async def test_organisation_from_company_datetime_to_date_conversion(self):
        """
        Test that Organisation.from_company() correctly converts datetime fields to date fields.
        This test ensures that when a Company has datetime fields (created, email_confirmed_dt, etc.),
        the Organisation schema properly accepts date objects after conversion.

        This would fail if the Organisation schema had datetime fields instead of date fields,
        because Pydantic 2.9+ is strict about datetime-to-date conversions.
        """
        admin = await Admin.create(
            first_name='John',
            last_name='Doe',
            username='john@example.com',
            is_sales_person=True,
            tc2_admin_id=30,
            pd_owner_id=100,
        )

        # Create a company with all datetime fields populated with non-zero time components
        # These datetime values have hours, minutes, seconds - not exact dates
        company = await Company.create(
            name='Test Company',
            country='US',
            sales_person=admin,
            email_confirmed_dt=datetime(2025, 1, 10, 14, 30, 43, 562, tzinfo=timezone.utc),
            pay0_dt=datetime(2025, 1, 11, 9, 0, 0, tzinfo=timezone.utc),
            pay1_dt=datetime(2025, 1, 12, 11, 15, 20, tzinfo=timezone.utc),
            pay3_dt=datetime(2025, 1, 13, 16, 45, 30, tzinfo=timezone.utc),
            card_saved_dt=datetime(2025, 1, 14, 8, 20, 10, tzinfo=timezone.utc),
            gclid='test_gclid_12345',
            gclid_expiry_dt=datetime(2025, 2, 15, 23, 59, 59, tzinfo=timezone.utc),
        )

        # This should successfully create an Organisation with date fields
        # If the Organisation schema fields were datetime instead of date, this would fail with:
        # "Datetimes provided to dates should have zero time - e.g. be exact dates"
        org = await Organisation.from_company(company)

        # Verify that the organisation was created successfully
        assert org.name == 'Test Company'
        assert org.address_country == 'US'
        assert org.owner_id == 100
        assert org.gclid == 'test_gclid_12345'

        # Verify that all the datetime fields were converted to date objects
        # created is auto-generated, so we just verify it exists and is a date
        assert org.created is not None
        assert isinstance(org.created, date)
        assert not isinstance(org.created, datetime)

        # Verify the manually set datetime fields were converted correctly
        assert org.email_confirmed_dt == date(2025, 1, 10)
        assert org.pay0_dt == date(2025, 1, 11)
        assert org.pay1_dt == date(2025, 1, 12)
        assert org.pay3_dt == date(2025, 1, 13)
        assert org.card_saved_dt == date(2025, 1, 14)
        assert org.gclid_expiry_dt == date(2025, 2, 15)

        # Verify that these are indeed date objects, not datetime objects
        assert isinstance(org.email_confirmed_dt, date)
        assert not isinstance(org.email_confirmed_dt, datetime)
        assert isinstance(org.pay0_dt, date)
        assert not isinstance(org.pay0_dt, datetime)

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_deleted_in_pipedrive(self, mock_request):
        """
        Test that when a company has a pd_org_id but the org was deleted in Pipedrive,
        the code handles the 404 gracefully and creates a new org.
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
        # Create company with pd_org_id that doesn't exist in fake Pipedrive
        company = await Company.create(name='Deleted Org Company', country='GB', sales_person=admin, pd_org_id=16994)

        # This should handle the 404 gracefully and create a new org
        await pd_post_process_client_event(company)

        # Verify that the company now has a new pd_org_id (not 16994)
        await company.refresh_from_db()
        assert company.pd_org_id != 16994
        assert company.pd_org_id is not None

        # Verify that a new org was created in pipedrive
        assert len(self.pipedrive.db['organizations']) == 1
        created_org = list(self.pipedrive.db['organizations'].values())[0]
        assert created_org['name'] == 'Deleted Org Company'
        assert created_org['address_country'] == 'GB'
        assert created_org['owner_id'] == 99

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_gone_in_pipedrive(self, mock_request):
        """
        Test that when a company has a pd_org_id but the org returns 410 Gone in Pipedrive
        (permanently deleted), the code handles it gracefully and creates a new org.
        """
        mock_request.side_effect = fake_pd_request(
            self.pipedrive, error_responses={('GET', 'organizations', 16994): (410, 'Gone')}
        )

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        # Create company with pd_org_id that returns 410 in Pipedrive
        company = await Company.create(name='Gone Org Company', country='GB', sales_person=admin, pd_org_id=16994)

        # This should handle the 410 gracefully and create a new org
        await pd_post_process_client_event(company)

        # Verify that the company now has a new pd_org_id (not 16994)
        await company.refresh_from_db()
        assert company.pd_org_id != 16994
        assert company.pd_org_id is not None

        # Verify that a new org was created in pipedrive
        assert len(self.pipedrive.db['organizations']) == 1
        created_org = list(self.pipedrive.db['organizations'].values())[0]
        assert created_org['name'] == 'Gone Org Company'
        assert created_org['address_country'] == 'GB'
        assert created_org['owner_id'] == 99

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_deleted_in_pipedrive(self, mock_request):
        """
        Test that when a contact has a pd_person_id but the person was deleted in Pipedrive,
        the code handles the 404 gracefully and creates a new person.
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
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=1)
        self.pipedrive.db['organizations'][1] = {'id': 1, 'name': 'Test Company'}

        # Create contact with pd_person_id that doesn't exist in fake Pipedrive
        contact = await Contact.create(
            first_name='John',
            last_name='Doe',
            email='john@example.com',
            company=company,
            pd_person_id=9999,
        )

        # This should handle the 404 gracefully and create a new person
        await pd_post_process_client_event(company)

        # Verify that the contact now has a new pd_person_id (not 9999)
        await contact.refresh_from_db()
        assert contact.pd_person_id != 9999
        assert contact.pd_person_id is not None

        # Verify that a new person was created in pipedrive
        assert len(self.pipedrive.db['persons']) == 1
        created_person = list(self.pipedrive.db['persons'].values())[0]
        assert created_person['name'] == 'John Doe'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_deal_deleted_in_pipedrive(self, mock_request):
        """
        Test that when a deal has a pd_deal_id but the deal was deleted in Pipedrive,
        the code handles the 404 gracefully and creates a new deal.
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
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=1)
        self.pipedrive.db['organizations'][1] = {'id': 1, 'name': 'Test Company'}

        contact = await Contact.create(
            first_name='John', last_name='Doe', email='john@example.com', company=company, pd_person_id=1
        )
        self.pipedrive.db['persons'][1] = {'id': 1, 'name': 'John Doe'}

        # Create deal with pd_deal_id that doesn't exist in fake Pipedrive
        deal = await Deal.create(
            name='Test Deal',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=8888,
        )

        # This should handle the 404 gracefully and create a new deal
        await pd_post_process_client_event(company, deal)

        # Verify that the deal now has a new pd_deal_id (not 8888)
        await deal.refresh_from_db()
        assert deal.pd_deal_id != 8888
        assert deal.pd_deal_id is not None

        # Verify that a new deal was created in pipedrive
        assert len(self.pipedrive.db['deals']) == 1
        created_deal = list(self.pipedrive.db['deals'].values())[0]
        assert created_deal['title'] == 'Test Deal'

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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            }
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            }
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            }
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            }
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            }
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'person_id': (await Contact.get()).pd_person_id,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'person_id': (await Contact.get()).pd_person_id,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
    async def test_date_custom_field_create_company(self, mock_request):
        """Test creating a company with a date custom field value"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        date_field = await CustomField.create(
            name='Contract Start Date',
            field_type=CustomField.TYPE_DATE,
            pd_field_id='123_contract_start_date_456',
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
            name='Test Company',
            country='GB',
            sales_person=admin,
        )

        # Create a custom field value
        contract_date = date(2024, 1, 15)
        await CustomFieldValue.create(
            custom_field=date_field,
            company=company,
            value=str(contract_date),
        )

        await pd_post_process_client_event(company)

        # Verify the date is stored in the database
        cf_value = await CustomFieldValue.get(custom_field=date_field, company=company)
        assert cf_value.value == '2024-01-15'

        # Verify the date is sent to Pipedrive
        org_data = self.pipedrive.db['organizations'][1]
        assert org_data['123_contract_start_date_456'] == '2024-01-15'
        assert org_data['name'] == 'Test Company'
        assert org_data['address_country'] == 'GB'
        assert org_data['owner_id'] == 99
        assert org_data['123_hermes_id_456'] == company.id
        # With mode='json', datetime is serialized to ISO format string
        assert org_data['created'] == company.created.date().isoformat()

        await date_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_date_custom_field_update_from_pipedrive(self, mock_request):
        """Test updating a company with a date custom field from Pipedrive webhook"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        date_field = await CustomField.create(
            name='Contract Start Date',
            field_type=CustomField.TYPE_DATE,
            pd_field_id='123_contract_start_date_456',
            linked_object_type='Company',
        )
        await build_custom_field_schema()

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            pd_owner_id=99,
        )
        company = await Company.create(
            name='Test Company',
            country='GB',
            sales_person=admin,
        )

        # Simulate receiving a webhook from Pipedrive with a date value
        pd_org_data = {
            'meta': {'action': 'updated', 'entity': 'organization', 'version': '2.0'},
            'data': {
                'owner_id': 99,
                'id': 20,
                'name': 'Test Company',
                'address_country': 'GB',
                '123_hermes_id_456': company.id,
                '123_contract_start_date_456': '2024-03-20',
            },
            'previous': {
                'owner_id': 99,
                'id': 20,
                'name': 'Test Company',
                'address_country': 'GB',
                '123_hermes_id_456': company.id,
            },
        }

        r = await self.client.post('/pipedrive/callback/', json=pd_org_data)
        assert r.status_code == 200, r.json()

        # Verify the date is stored in the database
        cf_value = await CustomFieldValue.get(custom_field=date_field, company=company)
        assert cf_value.value == '2024-03-20'

        await date_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_date_custom_field_update_value(self, mock_request):
        """Test updating an existing date custom field value"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        date_field = await CustomField.create(
            name='Contract Start Date',
            field_type=CustomField.TYPE_DATE,
            pd_field_id='123_contract_start_date_456',
            linked_object_type='Company',
        )
        await build_custom_field_schema()

        admin = await Admin.create(first_name='Steve', last_name='Jobs', username='climan@example.com', pd_owner_id=99)
        company = await Company.create(name='Test Company', country='GB', sales_person=admin)

        initial_date = date(2024, 1, 15)
        await CustomFieldValue.create(custom_field=date_field, company=company, value=initial_date)

        pd_org_data = {
            'meta': {'action': 'updated', 'entity': 'organization', 'version': '2.0'},
            'data': {
                'owner_id': 99,
                'id': 20,
                'name': 'Test Company',
                'address_country': 'GB',
                '123_hermes_id_456': company.id,
                '123_contract_start_date_456': '2024-06-30',
            },
            'previous': {
                'owner_id': 99,
                'id': 20,
                'name': 'Test Company',
                'address_country': 'GB',
                '123_hermes_id_456': company.id,
                '123_contract_start_date_456': '2024-01-15',
            },
        }

        r = await self.client.post('/pipedrive/callback/', json=pd_org_data)
        assert r.status_code == 200, r.json()

        # Verify the date was updated
        cf_value = await CustomFieldValue.get(custom_field=date_field, company=company)
        assert cf_value.value == '2024-06-30'

        # Verify only one custom field value exists (updated, not created new)
        cf_values = await CustomFieldValue.filter(custom_field=date_field, company=company)
        assert len(cf_values) == 1

        await date_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_date_custom_field_with_none_value(self, mock_request):
        """Test that None/null date values are handled properly"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        date_field = await CustomField.create(
            name='Contract Start Date',
            field_type=CustomField.TYPE_DATE,
            pd_field_id='123_contract_start_date_456',
            linked_object_type='Company',
        )
        await build_custom_field_schema()

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            pd_owner_id=99,
        )
        company = await Company.create(
            name='Test Company',
            country='GB',
            sales_person=admin,
        )

        # Simulate receiving a webhook with None date value
        pd_org_data = {
            'meta': {'action': 'updated', 'entity': 'organization', 'version': '2.0'},
            'data': {
                'owner_id': 99,
                'id': 20,
                'name': 'Test Company',
                'address_country': 'GB',
                '123_hermes_id_456': company.id,
                '123_contract_start_date_456': None,
            },
            'previous': {
                'owner_id': 99,
                'id': 20,
                'name': 'Test Company',
                'address_country': 'GB',
                '123_hermes_id_456': company.id,
            },
        }

        r = await self.client.post('/pipedrive/callback/', json=pd_org_data)
        assert r.status_code == 200, r.json()

        # Verify no custom field value was created for None
        cf_values = await CustomFieldValue.filter(custom_field=date_field, company=company)
        assert len(cf_values) == 0

        await date_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_date_custom_field_on_deal(self, mock_request):
        """Test date custom field on Deal objects"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        date_field = await CustomField.create(
            name='Expected Close Date',
            field_type=CustomField.TYPE_DATE,
            pd_field_id='345_expected_close_date_678',
            linked_object_type='Deal',
        )
        await build_custom_field_schema()

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            pd_owner_id=99,
        )
        company = await Company.create(
            name='Test Company',
            country='GB',
            sales_person=admin,
        )
        contact = await Contact.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            company=company,
        )
        deal = await Deal.create(
            name='Test Deal',
            company=company,
            contact=contact,
            admin=admin,
            pipeline=self.pipeline,
            stage=self.stage,
        )

        # Create a date custom field value for the deal
        close_date = date(2024, 12, 31)
        await CustomFieldValue.create(
            custom_field=date_field,
            deal=deal,
            value=str(close_date),
        )

        meeting = await Meeting.create(
            company=company,
            contact=contact,
            admin=admin,
            start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
            meeting_type=Meeting.TYPE_SALES,
        )

        await pd_post_process_sales_call(company, contact, meeting, deal)

        # Verify the date is sent to Pipedrive for the deal
        assert '345_expected_close_date_678' in self.pipedrive.db['deals'][1]
        assert self.pipedrive.db['deals'][1]['345_expected_close_date_678'] == '2024-12-31'

        await date_field.delete()
        await build_custom_field_schema()

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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            }
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'person_id': (await Contact.get()).pd_person_id,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert len(self.pipedrive.db['persons']) == 2  # We don't do get_or_create for persons, we just create them.
        assert (await Contact.get()).pd_person_id == 2
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': (await Contact.get()).pd_person_id,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert len(self.pipedrive.db['persons']) == 2  # We don't do get_or_create for persons, we just create them.
        assert (await Contact.get()).pd_person_id == 2
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': (await Contact.get()).pd_person_id,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert len(self.pipedrive.db['persons']) == 2  # We don't do get_or_create for persons, we just create them.
        assert (await Contact.get()).pd_person_id == 2
        assert self.pipedrive.db['deals'] == {
            1: {
                'title': 'A deal with Julies Ltd',
                'org_id': 1,
                'person_id': (await Contact.get()).pd_person_id,
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            }
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
                'created': company.created.date().isoformat(),
                'pay0_dt': None,
                'pay1_dt': None,
                'pay3_dt': None,
                'card_saved_dt': None,
                'email_confirmed_dt': None,
                'gclid': None,
                'gclid_expiry_dt': None,
            }
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

    @mock.patch('app.pipedrive.api.session.request')
    async def test_tc2_client_event_with_gclid_data(self, mock_request):
        """Test that GCLID data is sent to Pipedrive when processing client events."""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        await build_custom_field_schema()

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )

        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # Create company with GCLID data
        company = await Company.create(
            name='Test Agency',
            website='https://test.com',
            country='GB',
            sales_person=admin,
            status=Company.STATUS_PAYING,
            has_signed_up=True,
            created=dt,
            pay0_dt=dt,
            pay1_dt=dt,
            pay3_dt=dt,
            email_confirmed_dt=dt,
            card_saved_dt=dt,
            gclid='test-gclid-123',
            gclid_expiry_dt=dt,
        )

        contact = await Contact.create(
            first_name='Test', last_name='User', email='test@test.com', company_id=company.id
        )

        deal = await Deal.create(
            name='Test Deal',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=None,
        )

        await pd_post_process_client_event(company, deal)

        # Date fields are now sent as dates, not datetimes
        dt_date_str = dt.date().isoformat()
        # Assert GCLID, pay dates, and event tracking fields are sent to Pipedrive
        assert self.pipedrive.db['organizations'] == {
            1: {
                'name': 'Test Agency',
                'address_country': 'GB',
                'owner_id': 99,
                'created': dt_date_str,
                'pay0_dt': dt_date_str,
                'pay1_dt': dt_date_str,
                'pay3_dt': dt_date_str,
                'gclid': 'test-gclid-123',
                'gclid_expiry_dt': dt_date_str,
                'email_confirmed_dt': dt_date_str,
                'card_saved_dt': dt_date_str,
                '123_hermes_id_456': company.id,
                'id': 1,
            },
        }
        assert (await Company.get()).pd_org_id == 1
        assert self.pipedrive.db['persons'] == {
            1: {
                'id': 1,
                'name': 'Test User',
                'owner_id': 99,
                'email': ['test@test.com'],
                'phone': None,
                'org_id': 1,
                '234_hermes_id_567': contact.id,
            },
        }
        assert self.pipedrive.db['deals'] == {
            1: {
                'id': 1,
                'title': 'Test Deal',
                'org_id': 1,
                'person_id': 1,
                'user_id': 99,
                'pipeline_id': 1,
                'stage_id': 1,
                'status': 'open',
                '345_hermes_id_678': deal.id,
            }
        }

    @mock.patch('app.pipedrive.api.session.request')
    async def test_sales_call_company_deleted_before_task_runs(self, mock_request):
        """
        Test that pd_post_process_sales_call handles DoesNotExist gracefully when the company
        is deleted before the background task runs (simulating the Sentry error scenario).
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

        # Delete the company to simulate it being deleted before the background task runs
        await company.delete()

        # This should not raise an exception, but log and return gracefully
        await pd_post_process_sales_call(company, contact, meeting, deal)

        # Nothing should be created in Pipedrive since the company was deleted
        assert self.pipedrive.db['organizations'] == {}
        assert self.pipedrive.db['persons'] == {}
        assert self.pipedrive.db['deals'] == {}
        assert self.pipedrive.db['activities'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_sales_call_deal_deleted_before_task_runs(self, mock_request):
        """
        Test that pd_post_process_sales_call handles DoesNotExist gracefully when the deal
        is deleted before the background task runs (the actual Sentry error case).
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

        # Delete the deal to simulate it being deleted before the background task runs
        await deal.delete()

        # This should not raise an exception, but log and return gracefully
        await pd_post_process_sales_call(company, contact, meeting, deal)

        # Company and contact should be created, but deal and activity should not
        assert len(self.pipedrive.db['organizations']) == 1
        assert len(self.pipedrive.db['persons']) == 1
        assert self.pipedrive.db['deals'] == {}
        assert self.pipedrive.db['activities'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_client_event_company_deleted_before_task_runs(self, mock_request):
        """
        Test that pd_post_process_client_event handles DoesNotExist gracefully when the company
        is deleted before the background task runs.
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
        await Contact.create(first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id)

        # Delete the company to simulate it being deleted before the background task runs
        await company.delete()

        # This should not raise an exception, but log and return gracefully
        await pd_post_process_client_event(company)

        # Nothing should be created in Pipedrive
        assert self.pipedrive.db['organizations'] == {}
        assert self.pipedrive.db['persons'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_client_event_deal_deleted_before_task_runs(self, mock_request):
        """
        Test that pd_post_process_client_event handles DoesNotExist gracefully when the deal
        is deleted before the background task runs (the actual Sentry error scenario).
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
        deal = await Deal.create(
            name='A deal with Julies Ltd',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )

        # Delete the deal to simulate it being deleted before the background task runs
        await deal.delete()

        # This should not raise an exception, but log and return gracefully
        await pd_post_process_client_event(company, deal)

        # Company and contact should be created, but deal should not
        assert len(self.pipedrive.db['organizations']) == 1
        assert len(self.pipedrive.db['persons']) == 1
        assert self.pipedrive.db['deals'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_support_call_contact_deleted_before_task_runs(self, mock_request):
        """
        Test that pd_post_process_support_call handles DoesNotExist gracefully when the contact
        is deleted before the background task runs.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_support_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Julies Ltd', country='GB', sales_person=admin, pd_org_id=1)
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SUPPORT,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )

        # Delete the contact to simulate it being deleted before the background task runs
        await contact.delete()

        # This should not raise an exception, but log and return gracefully
        await pd_post_process_support_call(contact, meeting)

        # Nothing should be created in Pipedrive
        assert self.pipedrive.db['persons'] == {}
        assert self.pipedrive.db['activities'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_support_call_meeting_deleted_before_task_runs(self, mock_request):
        """
        Test that pd_post_process_support_call handles DoesNotExist gracefully when the meeting
        is deleted before the background task runs.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_support_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Julies Ltd', country='GB', sales_person=admin, pd_org_id=1)
        contact = await Contact.create(
            first_name='Brian', last_name='Junes', email='brain@junes.com', company_id=company.id
        )
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        meeting = await Meeting.create(
            company=company,
            contact=contact,
            meeting_type=Meeting.TYPE_SUPPORT,
            start_time=start,
            end_time=start + timedelta(hours=1),
            admin=admin,
        )

        # Delete the meeting to simulate it being deleted before the background task runs
        await meeting.delete()

        # This should not raise an exception, but log and return gracefully
        await pd_post_process_support_call(contact, meeting)

        # Person should be created but activity should not
        assert len(self.pipedrive.db['persons']) == 1
        assert self.pipedrive.db['activities'] == {}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_client_event_deal_deleted_before_custom_field_values_created(self, mock_request):
        """
        Test that update_or_create_inherited_deal_custom_field_values handles IntegrityError
        gracefully when a deal is deleted before custom field values are created for it.

        This reproduces the race condition where:
        1. Deals are fetched from the company
        2. A deal gets deleted from the database by another process (e.g., webhook)
        3. The code tries to create CustomFieldValues for the deleted deal
        4. This should be caught and logged, not raise an IntegrityError
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
            name='Julies Ltd',
            country='GB',
            sales_person=admin,
            tc2_status=Company.STATUS_PENDING_EMAIL_CONF,
        )
        deal = await Deal.create(
            name='Test Deal', company=company, admin=admin, pipeline=self.pipeline, stage=self.stage
        )

        # Create a custom field that should be inherited by the deal
        tc2_status_cf = await CustomField.create(
            name='TC2 Status',
            machine_name='tc2_status',
            field_type=CustomField.TYPE_STR,
            hermes_field_name='tc2_status',
            linked_object_type='Company',
            pd_field_id='123_tc2_status_456',
        )
        # Create the corresponding deal custom field
        await CustomField.create(
            name='TC2 Status',
            machine_name='tc2_status',
            field_type=CustomField.TYPE_STR,
            linked_object_type='Deal',
            pd_field_id='345_tc2_status_678',
        )
        await build_custom_field_schema()

        await CustomFieldValue.create(custom_field=tc2_status_cf, company=company, value='pending_email_conf')
        deal_id = deal.id  # Get the deal ID before deletion

        # Mock company.deals to return the in-memory deal object, then delete it from DB
        # This simulates the race condition where the deal list is fetched, then a deal is deleted
        # by another process before we try to create CustomFieldValues
        async def mock_deals_property():
            return [deal]

        with mock.patch.object(type(company), 'deals', new_callable=PropertyMock) as mock_deals:
            # Make the property return an awaitable that yields the deal list
            mock_deals.return_value = mock_deals_property()

            # Delete the deal from the database AFTER it's in the "fetched" list
            await Deal.filter(id=deal_id).delete()

            # This should not raise an IntegrityError, but log and continue gracefully
            await update_or_create_inherited_deal_custom_field_values(company)

        # No CustomFieldValues should be created for the deleted deal
        assert await CustomFieldValue.filter(deal_id=deal_id).count() == 0

    @mock.patch('app.pipedrive.api.session.request')
    async def test_client_event_deal_deleted_before_deleting_custom_field_value(self, mock_request):
        """
        Test that update_or_create_inherited_deal_custom_field_values handles DoesNotExist gracefully
        when trying to delete a custom field value for a deal that was deleted.

        This tests the branch where value is None and we try to delete a CustomFieldValue.
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
            name='Julies Ltd',
            country='GB',
            sales_person=admin,
            tc2_status=None,  # This will be None, triggering the delete branch
        )
        deal = await Deal.create(
            name='Test Deal', company=company, admin=admin, pipeline=self.pipeline, stage=self.stage
        )

        # Create a custom field that should be inherited by the deal
        await CustomField.create(
            name='TC2 Status',
            machine_name='tc2_status',
            field_type=CustomField.TYPE_STR,
            hermes_field_name='tc2_status',
            linked_object_type='Company',
            pd_field_id='123_tc2_status_456',
        )
        # Create the corresponding deal custom field
        deal_cf = await CustomField.create(
            name='TC2 Status',
            machine_name='tc2_status',
            field_type=CustomField.TYPE_STR,
            linked_object_type='Deal',
            pd_field_id='345_tc2_status_678',
        )
        await build_custom_field_schema()

        # Create a custom field value for the deal that we'll try to delete
        cfv = await CustomFieldValue.create(custom_field=deal_cf, deal=deal, value='pending_email_conf')

        # Get the deal ID before deletion
        deal_id = deal.id

        # Mock company.deals to return the in-memory deal object
        async def mock_deals_property():
            return [deal]

        with mock.patch.object(type(company), 'deals', new_callable=PropertyMock) as mock_deals:
            # Make the property return an awaitable that yields the deal list
            mock_deals.return_value = mock_deals_property()

            # Delete the deal from the database AFTER it's in the "fetched" list
            # This will cascade delete the CustomFieldValue too
            await Deal.filter(id=deal_id).delete()

            # This should not raise a DoesNotExist error, but log and continue gracefully
            await update_or_create_inherited_deal_custom_field_values(company)

        # The custom field value should have been cascade deleted when the deal was deleted
        assert await CustomFieldValue.filter(id=cfv.id).count() == 0

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_other_http_error(self, mock_request):
        """
        Test that HTTPErrors other than 404/410 are raised when updating an org.
        """
        from httpx import HTTPError

        mock_request.side_effect = fake_pd_request(
            self.pipedrive, error_responses={('GET', 'organizations', 123): (500, 'Internal Server Error')}
        )

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=123)

        # This should raise an HTTPError (not catch it)
        with self.assertRaises(HTTPError):
            await pd_post_process_client_event(company)

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_other_http_error(self, mock_request):
        """
        Test that HTTPErrors other than 404/410 are raised when updating a person.
        """
        from httpx import HTTPError

        mock_request.side_effect = fake_pd_request(
            self.pipedrive, error_responses={('GET', 'persons', 456): (500, 'Internal Server Error')}
        )

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=1)
        self.pipedrive.db['organizations'][1] = {'id': 1, 'name': 'Test Company'}

        await Contact.create(
            first_name='John', last_name='Doe', email='john@example.com', company=company, pd_person_id=456
        )

        # This should raise an HTTPError (not catch it)
        with self.assertRaises(HTTPError):
            await pd_post_process_client_event(company)

    @mock.patch('app.pipedrive.api.session.request')
    async def test_deal_update_other_http_error(self, mock_request):
        """
        Test that HTTPErrors other than 404/410 are logged (not raised) when updating a deal.
        """
        mock_request.side_effect = fake_pd_request(
            self.pipedrive, error_responses={('GET', 'deals', 789): (500, 'Internal Server Error')}
        )

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=1)
        self.pipedrive.db['organizations'][1] = {'id': 1, 'name': 'Test Company'}

        contact = await Contact.create(
            first_name='John', last_name='Doe', email='john@example.com', company=company, pd_person_id=1
        )
        self.pipedrive.db['persons'][1] = {'id': 1, 'name': 'John Doe'}

        deal = await Deal.create(
            name='Test Deal',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=789,
        )

        # This should NOT raise - it logs the error and continues
        await pd_post_process_client_event(company, deal)

        # Verify that the deal was NOT updated (still has old pd_deal_id)
        await deal.refresh_from_db()
        assert deal.pd_deal_id == 789

    @mock.patch('app.pipedrive.api.session.request')
    async def test_delete_organisation_error(self, mock_request):
        """
        Test error handling when deleting an organisation fails.
        """
        from app.pipedrive.api import delete_organisation

        mock_request.side_effect = fake_pd_request(
            self.pipedrive, error_responses={('DELETE', 'organizations', 123): Exception('Connection timeout')}
        )

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=123)

        # This should not raise - it logs the error
        await delete_organisation(company)

        # Verify that pd_org_id is still set (deletion failed)
        await company.refresh_from_db()
        assert company.pd_org_id == 123

    @mock.patch('app.pipedrive.api.session.request')
    async def test_delete_persons_error(self, mock_request):
        """
        Test error handling when deleting persons fails.
        """
        from app.pipedrive.api import delete_persons

        mock_request.side_effect = fake_pd_request(
            self.pipedrive, error_responses={('DELETE', 'persons', 456): Exception('Connection timeout')}
        )

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=1)
        self.pipedrive.db['organizations'][1] = {'id': 1, 'name': 'Test Company'}

        contact = await Contact.create(
            first_name='John', last_name='Doe', email='john@example.com', company=company, pd_person_id=456
        )

        # This should not raise - it logs the error
        await delete_persons([contact])

        # Verify that pd_person_id is still set (deletion failed)
        await contact.refresh_from_db()
        assert contact.pd_person_id == 456

    @mock.patch('app.pipedrive.api.session.request')
    async def test_delete_deal_error(self, mock_request):
        """
        Test error handling when deleting a deal fails.
        """
        from app.pipedrive.api import delete_deal

        mock_request.side_effect = fake_pd_request(
            self.pipedrive, error_responses={('DELETE', 'deals', 789): Exception('Connection timeout')}
        )

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='climan@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=1)
        self.pipedrive.db['organizations'][1] = {'id': 1, 'name': 'Test Company'}

        contact = await Contact.create(
            first_name='John', last_name='Doe', email='john@example.com', company=company, pd_person_id=1
        )
        self.pipedrive.db['persons'][1] = {'id': 1, 'name': 'John Doe'}

        deal = await Deal.create(
            name='Test Deal',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
            pd_deal_id=789,
        )

        # This should not raise - it logs the error
        await delete_deal(deal)

        # Verify that pd_deal_id is still set (deletion failed)
        await deal.refresh_from_db()
        assert deal.pd_deal_id == 789

    @mock.patch('app.pipedrive.api.session.request')
    async def test_inherited_custom_field_with_fk_field(self, mock_request):
        """
        Test that TYPE_FK_FIELD custom fields are handled correctly in inherited deal custom fields.
        This covers line 40 in _process.py.
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
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=1)
        self.pipedrive.db['organizations'][1] = {'id': 1, 'name': 'Test Company'}

        # Create a FK custom field on Company that should be inherited by Deal
        await CustomField.create(
            name='Sales Person',
            machine_name='sales_person_fk',
            hermes_field_name='sales_person',
            field_type=CustomField.TYPE_FK_FIELD,
            linked_object_type='Company',
            pd_field_id='company_sales_person_fk',
        )

        # Create corresponding deal field
        deal_fk_field = await CustomField.create(
            name='Sales Person',
            machine_name='sales_person_fk',
            field_type=CustomField.TYPE_FK_FIELD,
            linked_object_type='Deal',
            pd_field_id='deal_sales_person_fk',
        )

        await build_custom_field_schema()

        contact = await Contact.create(
            first_name='John', last_name='Doe', email='john@example.com', company=company, pd_person_id=1
        )
        self.pipedrive.db['persons'][1] = {'id': 1, 'name': 'John Doe'}

        deal = await Deal.create(
            name='Test Deal',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )

        # Update the inherited custom field values
        await update_or_create_inherited_deal_custom_field_values(company)

        # Verify that the custom field value was created with the admin's ID
        cfv = await CustomFieldValue.get(custom_field=deal_fk_field, deal=deal)
        assert cfv.value == str(admin.id)

    @mock.patch('app.pipedrive.api.session.request')
    async def test_inherited_custom_field_delete_none_value(self, mock_request):
        """
        Test that custom field values are deleted when the inherited value becomes None.
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
        company = await Company.create(name='Test Company', country='GB', sales_person=admin, pd_org_id=1)
        self.pipedrive.db['organizations'][1] = {'id': 1, 'name': 'Test Company'}

        # Create a custom field on Company that should be inherited by Deal
        await CustomField.create(
            name='Test Field',
            machine_name='test_field',
            hermes_field_name='website',  # This can be None
            field_type=CustomField.TYPE_STR,
            linked_object_type='Company',
            pd_field_id='company_test_field',
        )

        # Create corresponding deal field
        deal_field = await CustomField.create(
            name='Test Field',
            machine_name='test_field',
            field_type=CustomField.TYPE_STR,
            linked_object_type='Deal',
            pd_field_id='deal_test_field',
        )

        await build_custom_field_schema()

        contact = await Contact.create(
            first_name='John', last_name='Doe', email='john@example.com', company=company, pd_person_id=1
        )
        self.pipedrive.db['persons'][1] = {'id': 1, 'name': 'John Doe'}

        deal = await Deal.create(
            name='Test Deal',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )

        # Create a custom field value
        cfv = await CustomFieldValue.create(custom_field=deal_field, deal=deal, value='old_value')

        # Update the inherited custom field values (website is None, so it should delete the cfv)
        await update_or_create_inherited_deal_custom_field_values(company)

        # Verify that the custom field value was deleted
        assert not await CustomFieldValue.filter(id=cfv.id).exists()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_duplicate_custom_field_values_handled(self, mock_request):
        """
        Test that duplicate CustomFieldValue records are handled correctly.

        This reproduces the Sentry error #5935024822 where duplicate CustomFieldValue
        records existed for the same custom_field_id + deal combination, causing
        MultipleObjectsReturned error when update_or_create was called with incorrect syntax.

        Without the fix (incorrect update_or_create syntax), this would raise:
        MultipleObjectsReturned: Multiple objects returned for "CustomFieldValue", expected exactly one

        With the fix, it should handle duplicates gracefully and update correctly.
        """
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        # Create a custom field that should be inherited from Company to Deal
        await CustomField.create(
            name='UTM Campaign',
            field_type=CustomField.TYPE_STR,
            pd_field_id='123_utm_campaign_456',
            hermes_field_name='utm_campaign',
            linked_object_type='Company',
        )

        # Create the same custom field for Deal (to be inherited)
        deal_utm_campaign_field = await CustomField.create(
            name='UTM Campaign',
            field_type=CustomField.TYPE_STR,
            pd_field_id='345_utm_campaign_678',
            machine_name='utm_campaign',
            linked_object_type='Deal',
        )

        await build_custom_field_schema()

        admin = await Admin.create(
            first_name='Steve',
            last_name='Jobs',
            username='steve@example.com',
            is_sales_person=True,
            tc2_admin_id=20,
            pd_owner_id=99,
        )

        # Create company with utm_campaign set
        company = await Company.create(
            name='Test Company',
            country='GB',
            sales_person=admin,
            utm_campaign='google_ads_2024',
        )

        contact = await Contact.create(
            first_name='John',
            last_name='Doe',
            email='john@test.com',
            company_id=company.id,
        )

        deal = await Deal.create(
            name='Test Deal',
            company=company,
            contact=contact,
            pipeline=self.pipeline,
            stage=self.stage,
            admin=admin,
        )

        # Create the first CustomFieldValue - this should succeed
        await CustomFieldValue.create(
            custom_field=deal_utm_campaign_field,
            deal=deal,
            value='google_ads_2024',
        )

        # Verify only one record exists
        final_values = await CustomFieldValue.filter(custom_field=deal_utm_campaign_field, deal=deal)
        assert len(final_values) == 1, 'Should have exactly one CustomFieldValue record'

        await pd_post_process_client_event(company, deal)

        final_values = await CustomFieldValue.filter(custom_field=deal_utm_campaign_field, deal=deal)
        assert len(final_values) == 1, 'Should still have exactly one CustomFieldValue record'
        assert final_values[0].value == 'google_ads_2024', 'Value should be preserved'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_fetch_organisation_with_merged_hermes_id(self, mock_request):
        """Test that fetching an org from Pipedrive API with merged hermes_id doesn't crash"""
        from app.pipedrive._schema import Organisation
        from app.pipedrive.api import pipedrive_request

        admin = await Admin.create(
            first_name='John',
            last_name='Doe',
            username='john@example.com',
            is_sales_person=True,
            tc2_admin_id=30,
            pd_owner_id=100,
        )

        # Create two companies that would have been merged in Pipedrive
        company1 = await Company.create(name='Company 1', pd_org_id=999, sales_person=admin)
        company2 = await Company.create(name='Company 2', pd_org_id=888, sales_person=admin)

        # Mock Pipedrive API returning an org with merged hermes_id
        merged_org_data = {
            'success': True,
            'data': {
                'id': 999,
                'name': 'Merged Company',
                'owner_id': 100,
                'address_country': 'US',
                '123_hermes_id_456': f'{company1.id}, {company2.id}',  # Comma-separated IDs from merge
            },
        }

        mock_request.return_value.json.return_value = merged_org_data
        mock_request.return_value.status_code = 200
        mock_request.return_value.raise_for_status = lambda: None

        # This should not raise a ValidationError
        result = await pipedrive_request(f'organizations/{company1.pd_org_id}')

        # Should be able to parse the Organization without error
        pipedrive_org = Organisation(**result['data'])

        # The merged hermes_id should have been automatically parsed to the highest ID
        assert hasattr(pipedrive_org, 'hermes_id') or '123_hermes_id_456' in pipedrive_org.model_fields_set

        # Verify the org was created successfully with the name from Pipedrive
        assert pipedrive_org.name == 'Merged Company'
        assert pipedrive_org.id == 999
