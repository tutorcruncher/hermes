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
