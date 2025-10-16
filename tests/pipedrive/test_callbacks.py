import copy
from unittest import mock

from app.base_schema import build_custom_field_schema
from app.models import Admin, Company, Contact, CustomField, CustomFieldValue, Deal, Pipeline, Stage
from tests._common import HermesTestCase
from tests.pipedrive.helpers import (
    FakePipedrive,
    basic_pd_deal_data,
    basic_pd_org_data,
    basic_pd_person_data,
    basic_pd_pipeline_data,
    basic_pd_stage_data,
    fake_pd_request,
)


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
    async def test_org_create_with_actual_v2_webhook_format(self, mock_request):
        """Test that the actual webhook v2 format with custom_fields structure works"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        source_field = await CustomField.create(
            linked_object_type='Company',
            pd_field_id='d30bf32a173cdfa780901d5eeb92a8f2d1ccd980',
            name='Source',
            field_type='str',
        )
        await build_custom_field_schema()

        assert not await Company.exists()
        # This is the actual webhook v2 format Pipedrive sends
        webhook_data = {
            'data': {
                'id': 20,
                'name': 'Test company',
                'owner_id': 10,
                'address_country': None,
                'custom_fields': {
                    'd30bf32a173cdfa780901d5eeb92a8f2d1ccd980': {'type': 'varchar', 'value': 'google'},
                    '123_hermes_id_456': None,
                },
            },
            'previous': None,
            'meta': {'action': 'change', 'entity': 'organization', 'version': '2.0'},
        }
        r = await self.client.post(self.url, json=webhook_data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.sales_person_id == self.admin.id
        # Verify custom field was properly extracted
        cf_value = await CustomFieldValue.get(custom_field=source_field, company=company)
        assert cf_value.value == 'google'

        await source_field.delete()
        await build_custom_field_schema()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_create_with_hermes_id_company_missing(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        assert not await Company.exists()
        data = copy.deepcopy(basic_pd_org_data())
        data['data']['123_hermes_id_456'] = 75
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
    async def test_org_create_with_null_date_fields(self, mock_request):
        """Test that organizations with None/null date fields don't cause parsing errors"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        # Create date custom fields that map to hermes fields
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_pay0_dt_456',
            hermes_field_name='pay0_dt',
            name='Pay0 Date',
            field_type='date',
        )
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_pay1_dt_456',
            hermes_field_name='pay1_dt',
            name='Pay1 Date',
            field_type='date',
        )
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_gclid_expiry_dt_456',
            hermes_field_name='gclid_expiry_dt',
            name='GCLID Expiry Date',
            field_type='date',
        )
        await build_custom_field_schema()

        # Simulate webhook data with null date fields (like the error case)
        data = {
            'meta': {'action': 'create', 'entity': 'organization'},
            'data': {
                'id': 17430,
                'name': 'personal',
                'owner_id': 10,  # Use the test admin's pd_owner_id
                'address_country': None,
                '123_pay0_dt_456': None,
                '123_pay1_dt_456': None,
                '123_gclid_expiry_dt_456': None,
            },
            'previous': None,
        }

        assert not await Company.exists()
        r = await self.client.post(self.url, json=data)
        # This should succeed without a ParseError about "expected string or bytes-like object"
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'personal'
        assert company.pay0_dt is None
        assert company.pay1_dt is None
        assert company.gclid_expiry_dt is None

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
        data['data']['123_website_456'] = 'https://junes.com'
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
        data['data']['123_source_456'] = 'Google'

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
        data['data']['123_paid_invoice_count_456'] = None

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
        data['data']['123_source_456'] = 'Google'
        data['data']['123_hermes_id_456'] = company.id

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
        data['data']['owner_id'] = 999
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
        data['previous'] = data.pop('data')
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
        data['previous'] = data.pop('data')
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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous'].update(hermes_id=company.id)
        data['data'].update(name='New test company')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_with_null_date_fields(self, mock_request):
        """Test that updating organizations with None/null date fields doesn't cause parsing errors"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        # Create date custom fields that map to hermes fields
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_pay0_dt_456',
            hermes_field_name='pay0_dt',
            name='Pay0 Date',
            field_type='date',
        )
        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='123_email_confirmed_dt_456',
            hermes_field_name='email_confirmed_dt',
            name='Email Confirmed Date',
            field_type='date',
        )
        await build_custom_field_schema()

        company = await Company.create(name='Test company', pd_org_id=17430, sales_person=self.admin)

        # Simulate webhook data for an update with null date fields
        data = {
            'meta': {'action': 'update', 'entity': 'organization'},
            'data': {
                'id': 17430,
                'name': 'Test company',
                'owner_id': 10,
                'address_country': None,
                '123_pay0_dt_456': None,
                '123_email_confirmed_dt_456': None,
                '123_hermes_id_456': company.id,
            },
            'previous': {
                'id': 17430,
                'name': 'Test company',
                'owner_id': 10,
                '123_pay0_dt_456': None,
                '123_email_confirmed_dt_456': None,
                '123_hermes_id_456': company.id,
            },
        }

        r = await self.client.post(self.url, json=data)
        # This should succeed without a ParseError about "expected string or bytes-like object"
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Test company'
        assert company.pay0_dt is None
        assert company.email_confirmed_dt is None

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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous'].update(hermes_id=company.id)
        data['data'].update(**{'name': 'New test company', '123_website_456': 'https://newjunes.com'})
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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous'].update(
            hermes_id=company.id, **{'123_signup_questionnaire_456': '{"question1": "answer1", "question2": "answer2"}'}
        )
        data['data'].update(
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

    ## TODO: Re-enable in #282
    # @mock.patch('app.pipedrive.api.session.request')
    # async def test_org_update_merged(self, mock_request):
    #     mock_request.side_effect = fake_pd_request(self.pipedrive)
    #
    #     stage = await Stage.create(pd_stage_id=50, name='Stage 1')
    #     pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
    #     company = await Company.create(name='Old test company', sales_person=self.admin)
    #     company2 = await Company.create(name='Old test company2', sales_person=self.admin)
    #     contact2 = await Contact.create(first_name='John', last_name='Smith', pd_person_id=31, company=company2)
    #     deal2 = await Deal.create(
    #         name='Test deal',
    #         pd_deal_id=40,
    #         company=company2,
    #         contact=contact2,
    #         pipeline=pipeline,
    #         stage=stage,
    #         admin=self.admin,
    #     )
    #
    #     data = copy.deepcopy(basic_pd_org_data())
    #     data['previous'] = copy.deepcopy(data['data'])
    #     data['previous'].update(**{'123_hermes_id_456': f'{company.id},{company2.id}'})
    #     data['data'].update(**{'name': 'New test company'})
    #     r = await self.client.post(self.url, json=data)
    #     assert r.status_code == 200, r.json()
    #     company = await Company.get()
    #     assert company.name == 'New test company'
    #     contact_2 = await Contact.get(id=contact2.id)
    #     assert await contact_2.company == company
    #     deal_2 = await Deal.get(id=deal2.id)
    #     assert await deal_2.company == company
    #
    #     await build_custom_field_schema()

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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous'].update(hermes_id=company.id)
        data['data'].update(**{'123_source_456': 'Google'})
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()

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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous'].update(hermes_id=company.id)
        data['data'].update(**{'123_source_456': 'Google'})
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()

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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous'].update(hermes_id=company.id)
        data['data'].update(
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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous'].update(hermes_id=company.id)
        data['data'].update(
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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous'].update(hermes_id=company.id)
        data['data'].update(**{'name': 'New test company'})
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
        data['data']['hermes_id'] = company.id
        data['previous'] = copy.deepcopy(data['data'])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'Old test company'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_doesnt_exist(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(name='New test company')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New test company'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_no_hermes_id(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        await Company.create(name='Old test company', sales_person=self.admin, pd_org_id=20)
        data = copy.deepcopy(basic_pd_org_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(name='New test company')
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
        data['previous'] = data.pop('data')
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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous']['hermes_id'] = contact.id
        data['data'].update(name='Jessica Jones')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'Jessica Jones'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_with_null_date_fields(self, mock_request):
        """Test that updating persons with None/null date fields doesn't cause parsing errors"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(
            first_name='John',
            last_name='Doe',
            pd_person_id=30,
            company=company,
        )

        data = copy.deepcopy(basic_pd_person_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['previous']['234_hermes_id_567'] = contact.id
        data['data']['234_hermes_id_567'] = contact.id
        data['data'].update(name='Jane Doe')

        r = await self.client.post(self.url, json=data)
        # This should succeed without a ParseError
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.first_name == 'Jane'
        assert contact.last_name == 'Doe'

    ## TODO: Re-enable in #282
    # @mock.patch('app.pipedrive.api.session.request')
    # async def test_person_update_merged(self, mock_request):
    #     mock_request.side_effect = fake_pd_request(self.pipedrive)
    #
    #     stage = await Stage.create(pd_stage_id=50, name='Stage 1')
    #     pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
    #     company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
    #     contact = await Contact.create(first_name='John', last_name='Smith', company=company)
    #     contact_2 = await Contact.create(first_name='John', last_name='Smith', pd_person_id=31, company=company)
    #     deal2 = await Deal.create(
    #         name='Test deal',
    #         pd_deal_id=40,
    #         company=company,
    #         contact=contact_2,
    #         pipeline=pipeline,
    #         stage=stage,
    #         admin=self.admin,
    #     )
    #
    #     start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    #     meeting = await Meeting.create(
    #         company=company,
    #         contact=contact_2,
    #         meeting_type=Meeting.TYPE_SALES,
    #         start_time=start,
    #         end_time=start + timedelta(hours=1),
    #         admin=self.admin,
    #     )
    #
    #     data = copy.deepcopy(basic_pd_person_data())
    #     data['previous'] = copy.deepcopy(data['data'])
    #     data['previous'].update(**{'234_hermes_id_567': f'{contact.id},{contact_2.id}'})
    #     data['data'].update(name='Jessica Jones')
    #     r = await self.client.post(self.url, json=data)
    #     assert r.status_code == 200, r.json()
    #     contact = await Contact.get()
    #     assert contact.name == 'Jessica Jones'
    #     deal2 = await Deal.get(id=deal2.id)
    #     assert await deal2.contact == contact
    #     meeting2 = await Meeting.get(id=meeting.id)
    #     assert await meeting2.contact == contact

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_no_changes(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='John', last_name='Smith', pd_person_id=30, company=company)
        data = copy.deepcopy(basic_pd_person_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['previous']['hermes_id'] = contact.id
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
        data['previous'] = copy.deepcopy(data['data'])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'John Smith'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_doesnt_exist(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        data = copy.deepcopy(basic_pd_person_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(name='Brimstone')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.name == 'Brimstone'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_update_with_previous_without_name(self, mock_request):
        """Test that we handle previous data that doesn't include a name field."""
        mock_request.side_effect = fake_pd_request(self.pipedrive)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Matthew', last_name='Carty', pd_person_id=41953, company=company)

        # This simulates the actual webhook data from the error where previous only has obj_type and phones
        data = {
            'data': {
                'add_time': '2025-10-06T22:30:25Z',
                'emails': [{'label': 'work', 'primary': True, 'value': 'matthewjcarty@gmail.com'}],
                'first_name': 'Matthew',
                'id': 41953,
                'label': None,
                'label_ids': [],
                'last_name': 'Carty',
                'name': 'Matthew Carty',
                'org_id': 17410,
                'owner_id': 10,
                '234_hermes_id_567': contact.id,
            },
            'meta': {
                'action': 'change',
                'company_id': '11324733',
                'correlation_id': 'dac2a3d8-0220-4b6d-93ce-4cd080422032',
                'entity': 'person',
                'entity_id': '41953',
                'id': '3ad8a556-bcf0-46c3-93aa-8b1e9d829253',
                'is_bulk_edit': False,
                'timestamp': '2025-10-09T16:17:23.241Z',
                'type': 'general',
                'user_id': '15395742',
            },
            'previous': {
                'obj_type': 'person',
                'phones': [],
            },
        }
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        contact = await Contact.get()
        assert contact.first_name == 'Matthew'
        assert contact.last_name == 'Carty'

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
        data['data']['user_id'] = 999
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
        data['data']['stage_id'] = 999
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
        data['data']['pipeline_id'] = 999
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
        data['data']['person_id'] = 999
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
        data['previous'] = data.pop('data')
        data['previous']['hermes_id'] = deal.id
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Deal.exists()

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_delete_with_custom_fields(self, mock_add_task):
        """Test that delete events with custom fields (including signup_questionnaire) don't crash"""
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', company=company)
        deal = await Deal.create(
            name='Test deal',
            pd_deal_id=9161,
            company=company,
            contact=contact,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
        )

        # Create signup_questionnaire custom field
        await CustomField.create(
            linked_object_type='Deal',
            pd_field_id='1c68afb8974133b7f9d0c30fdbf1d39de2255399',
            machine_name='signup_questionnaire',
            name='Signup Questionnaire',
            field_type=CustomField.TYPE_STR,
        )
        await build_custom_field_schema()

        assert await Deal.exists()
        # This mimics the actual delete webhook from production where data is explicitly None
        data = {
            'data': None,
            'previous': {
                'id': 9161,
                'add_time': '2025-08-10T02:02:14Z',
                'currency': 'GBP',
                'expected_close_date': '2025-08-24',
                'hermes_id': deal.id,
                'custom_fields': {
                    '1c68afb8974133b7f9d0c30fdbf1d39de2255399': {
                        'type': 'text',
                        'value': "{'how-did-you-hear-about-us': 'Other'}",
                    },
                },
            },
            'meta': {
                'action': 'delete',
                'entity': 'deal',
                'entity_id': '9161',
            },
        }
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
        data['previous'] = copy.deepcopy(data['data'])
        data['previous']['hermes_id'] = deal.id
        data['data'].update(title='New test deal')
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
        data['data']['hermes_id'] = deal.id
        data['previous'] = copy.deepcopy(data['data'])
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
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(title='New test deal')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'New test deal'

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_update_partial_only_stage_changed(self, mock_add_task):
        """Test v2 webhook with only changed field (stage_id) in data and previous"""
        stage1 = await Stage.create(pd_stage_id=50, name='Stage 1')
        stage2 = await Stage.create(pd_stage_id=51, name='Stage 2')
        pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage1)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        deal = await Deal.create(
            name='Test deal',
            pd_deal_id=40,
            company=company,
            contact=contact,
            pipeline=pipeline,
            stage=stage1,
            admin=self.admin,
            status='open',
        )

        await build_custom_field_schema()

        # V2 webhook only sends changed fields
        data = {
            'data': {
                'id': 40,
                'stage_id': 51,
                'hermes_id': deal.id,
            },
            'previous': {
                'stage_id': 50,
                'hermes_id': deal.id,
            },
            'meta': {'action': 'change', 'entity': 'deal', 'version': '2.0'},
        }

        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert await deal.stage == stage2
        assert deal.name == 'Test deal'  # Unchanged
        assert await deal.company == company  # Unchanged

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_update_partial_multiple_fields(self, mock_add_task):
        """Test v2 webhook with multiple changed fields but not all fields"""
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        deal = await Deal.create(
            name='Old deal name',
            pd_deal_id=40,
            company=company,
            contact=contact,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
            status='open',
        )

        await build_custom_field_schema()

        # V2 webhook sends only changed fields
        data = {
            'data': {
                'id': 40,
                'title': 'New deal name',
                'status': 'won',
                'hermes_id': deal.id,
            },
            'previous': {
                'title': 'Old deal name',
                'status': 'open',
                'hermes_id': deal.id,
            },
            'meta': {'action': 'change', 'entity': 'deal', 'version': '2.0'},
        }

        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'New deal name'
        assert deal.status == 'won'
        assert await deal.stage == stage  # Unchanged
        assert await deal.pipeline == pipeline  # Unchanged

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_deal_update_with_null_date_fields(self, mock_add_task):
        """Test that updating deals with None/null date fields doesn't cause parsing errors"""
        stage = await Stage.create(pd_stage_id=50, name='Stage 1')
        pipeline = await Pipeline.create(pd_pipeline_id=60, name='Pipeline 1', dft_entry_stage=stage)
        company = await Company.create(name='Test company', pd_org_id=20, sales_person=self.admin)
        contact = await Contact.create(first_name='Brian', last_name='Blessed', pd_person_id=30, company=company)
        deal = await Deal.create(
            name='Test deal',
            pd_deal_id=40,
            company=company,
            contact=contact,
            pipeline=pipeline,
            stage=stage,
            admin=self.admin,
        )

        data = copy.deepcopy(basic_pd_deal_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['previous']['hermes_id'] = deal.id
        data['data']['hermes_id'] = deal.id
        data['data']['close_time'] = None
        data['data']['title'] = 'Updated deal'

        r = await self.client.post(self.url, json=data)
        # This should succeed without a ParseError
        assert r.status_code == 200, r.json()
        deal = await Deal.get()
        assert deal.name == 'Updated deal'

    @mock.patch('fastapi.BackgroundTasks.add_task')
    async def test_org_update_partial_only_name_changed(self, mock_add_task):
        """Test v2 webhook for org with only name field changed"""
        company = await Company.create(name='Old Company Name', pd_org_id=20, sales_person=self.admin)
        await build_custom_field_schema()

        # V2 webhook only sends changed field
        data = {
            'data': {
                'id': 20,
                'name': 'New Company Name',
                'hermes_id': company.id,
            },
            'previous': {
                'name': 'Old Company Name',
                'hermes_id': company.id,
            },
            'meta': {'action': 'change', 'entity': 'organization', 'version': '2.0'},
        }

        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        company = await Company.get()
        assert company.name == 'New Company Name'
        assert await company.sales_person == self.admin  # Unchanged

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
        data['previous'] = data.pop('data')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Pipeline.exists()

    async def test_pipeline_update(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Pipeline.create(name='Old Pipeline', pd_pipeline_id=60)
        data = copy.deepcopy(basic_pd_pipeline_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(name='New Pipeline')
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
        data['previous'] = copy.deepcopy(data['data'])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        pipeline = await Pipeline.get()
        assert pipeline.name == 'Old Pipeline'

    async def test_pipeline_update_doesnt_exist(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        data = copy.deepcopy(basic_pd_pipeline_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(name='New test pipeline')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        pipeline = await Pipeline.get()
        assert pipeline.name == 'New test pipeline'

    async def test_pipeline_update_with_null_fields(self):
        """Test that updating pipelines with None/null fields doesn't cause parsing errors"""
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Pipeline.create(name='Old Pipeline', pd_pipeline_id=60)
        data = copy.deepcopy(basic_pd_pipeline_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(name='New Pipeline', active=None)

        r = await self.client.post(self.url, json=data)
        # This should succeed without a ParseError
        assert r.status_code == 200, r.json()
        pipeline = await Pipeline.get()
        assert pipeline.name == 'New Pipeline'

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
        data['previous'] = data.pop('data')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert not await Stage.exists()

    async def test_stage_update(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Stage.create(name='Stage 1', pd_stage_id=50)
        data = copy.deepcopy(basic_pd_stage_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(name='New Stage')
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
        data['previous'] = copy.deepcopy(data['data'])
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        stage = await Stage.get()
        assert stage.name == 'Old Stage'

    async def test_stage_update_doesnt_exist(self):
        # They are created in the test setup
        await Pipeline.all().delete()
        await Stage.all().delete()

        data = copy.deepcopy(basic_pd_stage_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(name='New test stage')
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        stage = await Stage.get()
        assert stage.name == 'New test stage'

    async def test_stage_update_with_null_fields(self):
        """Test that updating stages with None/null fields doesn't cause parsing errors"""
        await Pipeline.all().delete()
        await Stage.all().delete()

        await Stage.create(name='Old Stage', pd_stage_id=50)
        data = copy.deepcopy(basic_pd_stage_data())
        data['previous'] = copy.deepcopy(data['data'])
        data['data'].update(name='New Stage', pipeline_id=None)

        r = await self.client.post(self.url, json=data)
        # This should succeed without a ParseError
        assert r.status_code == 200, r.json()
        stage = await Stage.get()
        assert stage.name == 'New Stage'

    ## TODO: Re-enable in #282
    # async def test_duplicate_hermes_ids(self):
    #     await Company.create(id=1, name='Old test company', sales_person=self.admin)
    #     await Company.create(id=2, name='Old test company', sales_person=self.admin)
    #
    #     data = copy.deepcopy(basic_pd_org_data())
    #     data['previous'] = copy.deepcopy(data['data'])
    #     data['data'].update({'123_hermes_id_456': '1, 2'})
    #     r = await self.client.post(self.url, json=data)
    #     assert r.status_code == 200
    #
    #     assert await Company.exists(id=1)
    #     assert not await Company.exists(id=2)

    # async def test_single_duplicate_hermes_ids(self):
    #     await Company.create(id=1, name='Old test company', sales_person=self.admin)
    #     data = copy.deepcopy(basic_pd_org_data())
    #     data['previous'] = copy.deepcopy(data['data'])
    #     data['data'].update({'123_hermes_id_456': '1'})
    #     r = await self.client.post(self.url, json=data)
    #     assert r.status_code == 200
    #
    #     assert await Company.exists(id=1)
    #
    # async def test_duplicate_hermes_ids_correct_format(self):
    #     await Company.create(id=1, name='Old test company', sales_person=self.admin)
    #
    #     data = copy.deepcopy(basic_pd_org_data())
    #     data['previous'] = copy.deepcopy(data['data'])
    #     data['data'].update({'123_hermes_id_456': 1})
    #     r = await self.client.post(self.url, json=data)
    #     assert r.status_code == 200
    #
    #     assert await Company.exists(id=1)

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_update_with_date_custom_field(self, mock_request):
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        await CustomField.create(
            linked_object_type='Company',
            pd_field_id='regression_test_date_field',
            hermes_field_name='card_saved_dt',
            name='Regression Test Date',
            machine_name='regression_test_date',
            field_type=CustomField.TYPE_DATE,
        )
        await build_custom_field_schema()

        company = await Company.create(name='Test Company', pd_org_id=9999, sales_person=self.admin, card_saved_dt=None)
        webhook_data = {
            'meta': {'action': 'change', 'entity': 'organization', 'entity_id': '9999'},
            'data': {
                'id': 9999,
                'name': 'Test Company',
                'owner_id': self.admin.pd_owner_id,
                '123_hermes_id_456': company.id,
                'regression_test_date_field': '2021-06-04',
            },
            'previous': {'name': 'Test Company', 'regression_test_date_field': None},
        }

        r = await self.client.post(self.url, json=webhook_data)
        assert r.status_code == 200, r.json()

        await company.refresh_from_db()
        assert company.card_saved_dt.date().isoformat() == '2021-06-04'

    async def test_activity_webhook(self):
        """Test that activity webhooks are ignored early without validation"""
        # Activities are calendar events that we create in Pipedrive but don't need to sync back
        data = {'meta': {'entity': 'activity'}, 'data': {'id': 123}}
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert r.json() == {'status': 'ok'}

    async def test_note_webhook(self):
        """Test that note webhooks are ignored early without validation"""
        # Notes are comments that users add to records in Pipedrive but we don't need to sync them back
        data = {'meta': {'entity': 'note'}, 'data': {'id': 456}}
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert r.json() == {'status': 'ok'}

    async def test_unknown_entity_webhook(self):
        """Test that unknown entity types are gracefully ignored"""
        # If Pipedrive adds new entity types, we should ignore them by default
        data = {'meta': {'entity': 'unknown_type'}, 'data': {'id': 789}}
        r = await self.client.post(self.url, json=data)
        assert r.status_code == 200, r.json()
        assert r.json() == {'status': 'ok'}

    @mock.patch('app.pipedrive.api.session.request')
    async def test_org_merged_hermes_id_webhook(self, mock_request):
        """Test that merged organizations with comma-separated hermes_ids are handled correctly"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        # Create two companies that exist in Hermes
        # Company 1 is linked to Pipedrive org 100 (the primary org after merge)
        company1 = await Company.create(name='Company 1', pd_org_id=100, sales_person=self.admin, tc2_agency_id=1001)
        # Company 2 was linked to Pipedrive org 200 (which got merged into org 100)
        company2 = await Company.create(name='Company 2', pd_org_id=200, sales_person=self.admin, tc2_agency_id=1002)

        # Add the merged org to the fake Pipedrive database (this represents the state after merge in Pipedrive)
        self.pipedrive.db['organizations'][100] = {
            'id': 100,
            'name': 'Merged Company',
            'owner_id': self.admin.pd_owner_id,
            '123_hermes_id_456': f'{company1.id}, {company2.id}',
        }

        # Simulate Pipedrive merging the organizations - hermes_id becomes comma-separated
        # Org 100 is the primary, so company1 should be the one that gets updated
        webhook_data = {
            'meta': {'action': 'change', 'entity': 'organization', 'entity_id': '100'},
            'data': {
                'id': 100,
                'name': 'Merged Company',
                'owner_id': self.admin.pd_owner_id,
                '123_hermes_id_456': f'{company1.id}, {company2.id}',  # Comma-separated IDs
            },
            'previous': {
                'name': 'Company 1',
                '123_hermes_id_456': company1.id,
            },
        }

        r = await self.client.post(self.url, json=webhook_data)
        assert r.status_code == 200, r.json()

        # Company 1 (linked to pd_org_id=100) should be updated with merged data
        company1_updated = await Company.get(id=company1.id)
        assert company1_updated.name == 'Merged Company'
        assert company1_updated.pd_org_id == 100

        # Company 2 should still exist (no deletion)
        company2_still_exists = await Company.filter(id=company2.id).exists()
        assert company2_still_exists

        # Verify Pipedrive was updated with just company1's hermes_id
        update_calls = [
            call
            for call in mock_request.call_args_list
            if call[1].get('method') == 'PUT' and 'organizations/100' in call[1].get('url', '')
        ]
        assert len(update_calls) >= 1, 'Pipedrive should be updated to fix hermes_id'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_person_merged_hermes_id_webhook(self, mock_request):
        """Test that merged persons with comma-separated hermes_ids are handled correctly"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        company = await Company.create(name='Company', pd_org_id=300, sales_person=self.admin)

        # Create two contacts that exist in Hermes
        # Contact 1 is linked to Pipedrive person 400 (the primary person after merge)
        contact1 = await Contact.create(
            first_name='John', last_name='Doe', email='john@example.com', pd_person_id=400, company=company
        )
        # Contact 2 was linked to Pipedrive person 500 (which got merged into person 400)
        contact2 = await Contact.create(
            first_name='Jane', last_name='Doe', email='jane@example.com', pd_person_id=500, company=company
        )

        # Add the merged person to the fake Pipedrive database
        self.pipedrive.db['persons'][400] = {
            'id': 400,
            'name': 'Jane Doe',
            'email': 'jane@example.com',
            'org_id': company.pd_org_id,
            'owner_id': self.admin.pd_owner_id,
            '234_hermes_id_567': f'{contact1.id}, {contact2.id}',
        }

        # Simulate Pipedrive merging the persons
        webhook_data = {
            'meta': {'action': 'change', 'entity': 'person', 'entity_id': '400'},
            'data': {
                'id': 400,
                'name': 'Jane Doe',
                'email': 'jane@example.com',
                'org_id': company.pd_org_id,
                'owner_id': self.admin.pd_owner_id,
                '234_hermes_id_567': f'{contact1.id}, {contact2.id}',
            },
            'previous': {
                'name': 'John Doe',
                '234_hermes_id_567': contact1.id,
            },
        }

        r = await self.client.post(self.url, json=webhook_data)
        assert r.status_code == 200, r.json()

        # Contact 1 (linked to pd_person_id=400) should be updated with merged data
        contact1_updated = await Contact.get(id=contact1.id)
        assert contact1_updated.first_name == 'Jane'
        assert contact1_updated.pd_person_id == 400

        # Contact 2 should still exist (no deletion)
        contact2_still_exists = await Contact.filter(id=contact2.id).exists()
        assert contact2_still_exists

    @mock.patch('app.pipedrive.api.session.request')
    async def test_deal_merged_hermes_id_webhook(self, mock_request):
        """Test that merged deals with comma-separated hermes_ids are handled correctly"""
        mock_request.side_effect = fake_pd_request(self.pipedrive)

        company = await Company.create(name='Company', pd_org_id=600, sales_person=self.admin)
        contact = await Contact.create(
            first_name='Test', last_name='User', email='test@example.com', pd_person_id=700, company=company
        )

        # Create two deals that exist in Hermes
        # Deal 1 is linked to Pipedrive deal 800 (the primary deal after merge)
        deal1 = await Deal.create(
            name='Deal 1',
            pd_deal_id=800,
            company=company,
            contact=contact,
            admin=self.admin,
            pipeline=self.pipeline,
            stage=self.stage,
        )
        # Deal 2 was linked to Pipedrive deal 900 (which got merged into deal 800)
        deal2 = await Deal.create(
            name='Deal 2',
            pd_deal_id=900,
            company=company,
            contact=contact,
            admin=self.admin,
            pipeline=self.pipeline,
            stage=self.stage,
        )

        # Add the merged deal to the fake Pipedrive database
        self.pipedrive.db['deals'][800] = {
            'id': 800,
            'title': 'Merged Deal',
            'org_id': company.pd_org_id,
            'person_id': contact.pd_person_id,
            'user_id': self.admin.pd_owner_id,
            'pipeline_id': self.pipeline.pd_pipeline_id,
            'stage_id': self.stage.pd_stage_id,
            '345_hermes_id_678': f'{deal1.id}, {deal2.id}',
        }

        # Simulate Pipedrive merging the deals
        webhook_data = {
            'meta': {'action': 'change', 'entity': 'deal', 'entity_id': '800'},
            'data': {
                'id': 800,
                'title': 'Merged Deal',
                'org_id': company.pd_org_id,
                'person_id': contact.pd_person_id,
                'user_id': self.admin.pd_owner_id,
                'pipeline_id': self.pipeline.pd_pipeline_id,
                'stage_id': self.stage.pd_stage_id,
                '345_hermes_id_678': f'{deal1.id}, {deal2.id}',
            },
            'previous': {
                'title': 'Deal 1',
                '345_hermes_id_678': deal1.id,
            },
        }

        r = await self.client.post(self.url, json=webhook_data)
        assert r.status_code == 200, r.json()

        # Deal 1 (linked to pd_deal_id=800) should be updated with merged data
        deal1_updated = await Deal.get(id=deal1.id)
        assert deal1_updated.name == 'Merged Deal'
        assert deal1_updated.pd_deal_id == 800

        # Deal 2 should still exist (no deletion)
        deal2_still_exists = await Deal.filter(id=deal2.id).exists()
        assert deal2_still_exists
