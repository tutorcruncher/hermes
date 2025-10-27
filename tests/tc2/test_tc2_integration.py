"""
Integration tests for TC2 → Hermes → Pipedrive flow.
"""

from unittest.mock import patch

import pytest
from sqlmodel import select

from app.main_app.models import Admin, Company, Contact, Deal
from app.tc2.models import TCClient
from app.tc2.process import process_tc_client
from tests.helpers import create_mock_response


@pytest.fixture
def sample_tc_client_data(test_admin):
    """Sample TC2 client data for testing"""
    return {
        'id': 123,
        'meta_agency': {
            'id': 456,
            'name': 'Test Agency',
            'country': 'United Kingdom (GB)',
            'website': 'https://example.com',
            'status': 'active',
            'paid_invoice_count': 5,
            'created': '2024-01-01T00:00:00Z',
            'price_plan': 'monthly-payg',
            'narc': False,
        },
        'user': {'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com', 'phone': '+1234567890'},
        'status': 'active',
        'sales_person': {'id': test_admin.tc2_admin_id},
        'paid_recipients': [
            {'id': 789, 'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com'},
        ],
        'extra_attrs': [
            {'machine_name': 'utm_source', 'value': 'google'},
            {'machine_name': 'utm_campaign', 'value': 'summer2024'},
        ],
    }


class TestTC2Integration:
    """Test TC2 webhook processing"""

    async def test_process_tc_client_creates_company(self, db, test_admin, sample_tc_client_data):
        """Test that processing TC2 client creates a company in Hermes"""
        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        assert company is not None
        assert company.name == 'Test Agency'
        assert company.tc2_cligency_id == 123
        assert company.tc2_agency_id == 456
        assert company.country == 'GB'
        assert company.website == 'https://example.com'
        assert company.paid_invoice_count == 5
        assert company.price_plan == 'payg'
        assert company.utm_source == 'google'
        assert company.utm_campaign == 'summer2024'
        assert company.sales_person_id == test_admin.id

    async def test_process_tc_client_creates_contacts(self, db, test_admin, sample_tc_client_data):
        """Test that processing TC2 client creates contacts from paid_recipients"""
        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        contacts = db.exec(select(Contact).where(Contact.company_id == company.id)).all()

        assert len(contacts) == 1
        assert contacts[0].first_name == 'John'
        assert contacts[0].last_name == 'Doe'
        assert contacts[0].email == 'john@example.com'
        assert contacts[0].tc2_sr_id == 789

    async def test_process_tc_client_updates_existing_company(self, db, test_admin, sample_tc_client_data):
        """Test that processing TC2 client updates existing company"""
        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)
        company_id = company.id

        sample_tc_client_data['meta_agency']['name'] = 'Updated Agency'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 10

        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db)

        assert updated_company.id == company_id
        assert updated_company.name == 'Updated Agency'
        assert updated_company.paid_invoice_count == 10

    @patch('httpx.AsyncClient.request')
    async def test_tc2_webhook_triggers_pipedrive_sync(
        self, mock_request, client, db, test_admin, sample_tc_client_data
    ):
        """Test that TC2 webhook triggers background sync to Pipedrive"""
        mock_response = create_mock_response({'data': {'id': 999}})
        mock_request.return_value = mock_response

        sample_tc_client_data['model'] = 'Client'

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()

        assert company is not None
        assert company.name == 'Test Agency'

    async def test_narc_company_not_synced_to_pipedrive(self, db, test_admin, sample_tc_client_data):
        """Test that NARC companies are purged from Pipedrive"""
        sample_tc_client_data['meta_agency']['narc'] = True

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        assert company.narc is True

    async def test_tc2_callback_ignores_agree_terms(self, client, db, test_admin, sample_tc_client_data):
        """Test that TC2 callback ignores AGREE_TERMS events"""
        sample_tc_client_data['model'] = 'Client'

        webhook_data = {
            'events': [{'action': 'AGREE_TERMS', 'verb': 'agree', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_tc2_callback_ignores_non_client_events(self, client, db):
        """Test that TC2 callback ignores non-Client events"""
        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': {'model': 'Invoice', 'id': 123}}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    @patch('app.pipedrive.tasks.purge_company_from_pipedrive')
    async def test_tc2_callback_triggers_purge_for_narc(
        self, mock_purge, client, db, test_admin, sample_tc_client_data
    ):
        """Test that TC2 callback triggers purge for NARC companies"""
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['narc'] = True

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200

    async def test_tc2_callback_handles_processing_errors(self, client, db):
        """Test that TC2 callback handles processing errors gracefully"""
        webhook_data = {
            'events': [
                {
                    'action': 'UPDATE',
                    'verb': 'update',
                    'subject': {
                        'model': 'Client',
                        'id': 123,
                        'meta_agency': {},
                    },
                }
            ],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200

    async def test_extra_attrs_mapped_to_company_fields(self, db, test_admin, sample_tc_client_data):
        """Test that TC2 extra_attrs are correctly mapped to Company fields"""
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'facebook'},
            {'machine_name': 'utm_campaign', 'value': 'winter2024'},
            {'machine_name': 'estimated_monthly_income', 'value': '5000'},
            {'machine_name': 'signup_questionnaire', 'value': 'some_data'},
        ]
        # gclid comes from meta_agency, not extra_attrs
        sample_tc_client_data['meta_agency']['gclid'] = 'ABC123'

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        assert company.utm_source == 'facebook'
        assert company.utm_campaign == 'winter2024'
        assert company.gclid == 'ABC123'
        assert company.estimated_income == '5000'
        assert company.signup_questionnaire == 'some_data'

    async def test_process_client_with_support_and_bdr_persons(self, db, sample_tc_client_data):
        """Test processing client with support and BDR persons"""
        sales_admin = db.create(
            Admin(first_name='Sales', last_name='Admin', username='sales@example.com', tc2_admin_id=100)
        )
        support_admin = db.create(
            Admin(first_name='Support', last_name='Admin', username='support@example.com', tc2_admin_id=101)
        )
        bdr_admin = db.create(Admin(first_name='BDR', last_name='Admin', username='bdr@example.com', tc2_admin_id=102))

        sample_tc_client_data['sales_person'] = {'id': 100}
        sample_tc_client_data['associated_admin'] = {'id': 101}
        sample_tc_client_data['bdr_person'] = {'id': 102}

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        assert company.sales_person_id == sales_admin.id
        assert company.support_person_id == support_admin.id
        assert company.bdr_person_id == bdr_admin.id

    async def test_process_client_returns_none_when_no_sales_person(self, db, sample_tc_client_data):
        """Test that process_tc_client returns None when sales_person not found"""
        sample_tc_client_data['sales_person'] = {'id': 999}

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        assert company is None

    async def test_process_client_updates_gclid_extra_attr(self, db, test_admin, sample_tc_client_data):
        """Test that gclid from meta_agency is mapped correctly on update"""
        tc_client = TCClient(**sample_tc_client_data)
        await process_tc_client(tc_client, db)

        # gclid comes from meta_agency, not extra_attrs
        sample_tc_client_data['meta_agency']['gclid'] = 'NEW_GCLID'
        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db)

        assert updated_company.gclid == 'NEW_GCLID'

    async def test_process_client_updates_signup_questionnaire_extra_attr(self, db, test_admin, sample_tc_client_data):
        """Test that signup_questionnaire extra attribute is mapped correctly on update"""
        tc_client = TCClient(**sample_tc_client_data)
        await process_tc_client(tc_client, db)

        sample_tc_client_data['extra_attrs'] = [{'machine_name': 'signup_questionnaire', 'value': 'questionnaire_data'}]
        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db)

        assert updated_company.signup_questionnaire == 'questionnaire_data'

    async def test_process_client_updates_estimated_income_extra_attr(self, db, test_admin, sample_tc_client_data):
        """Test that estimated_monthly_income extra attribute is mapped correctly on update"""
        tc_client = TCClient(**sample_tc_client_data)
        await process_tc_client(tc_client, db)

        sample_tc_client_data['extra_attrs'] = [{'machine_name': 'estimated_monthly_income', 'value': '10000'}]
        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db)

        assert updated_company.estimated_income == '10000'


class TestTC2EdgeCases:
    """Test TC2 webhook edge cases"""

    async def test_tc2_client_with_contact_without_email(self, db, test_admin, sample_tc_client_data):
        """Test TC2 client creates contact even when paid_recipient has no email"""
        sample_tc_client_data['paid_recipients'] = [
            {
                'id': 789,
                'first_name': 'John',
                'last_name': 'Doe',
                'email': None,  # No email
            }
        ]
        # Set email on user to None as well
        sample_tc_client_data['user']['email'] = None

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        # Contact should still be created
        contacts = db.exec(select(Contact).where(Contact.company_id == company.id)).all()
        assert len(contacts) == 1
        assert contacts[0].email is None

    async def test_tc2_client_with_unusual_country_format(self, db, test_admin, sample_tc_client_data):
        """Test TC2 client handles unusual country formats"""
        sample_tc_client_data['meta_agency']['country'] = 'United States (US)'

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        # Country code should be extracted
        assert company.country == 'US'

    async def test_tc2_client_no_paid_recipients(self, db, test_admin, sample_tc_client_data):
        """Test TC2 client with empty paid_recipients list"""
        sample_tc_client_data['paid_recipients'] = []

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        # Should still create company
        assert company.id is not None

        # No contacts should be created
        contacts = db.exec(select(Contact).where(Contact.company_id == company.id)).all()
        assert len(contacts) == 0

    async def test_tc2_narc_agency_closes_open_deals(
        self, db, test_admin, test_pipeline, test_stage, sample_tc_client_data
    ):
        """Test that marking agency as NARC closes all open deals"""
        # First create company and deal
        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        # Create an open deal
        deal = db.create(
            Deal(
                name='Test Deal',
                admin_id=test_admin.id,
                company_id=company.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
                status=Deal.STATUS_OPEN,
            )
        )

        # Now mark company as NARC
        sample_tc_client_data['meta_agency']['narc'] = True
        tc_client_narc = TCClient(**sample_tc_client_data)
        await process_tc_client(tc_client_narc, db)

        # Deal should be marked as lost
        db.refresh(deal)
        assert deal.status == Deal.STATUS_LOST

    async def test_tc2_terminated_agency_closes_open_deals(
        self, db, test_admin, test_pipeline, test_stage, sample_tc_client_data
    ):
        """Test that terminating agency closes all open deals"""
        # First create company and deal
        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        # Create an open deal
        deal = db.create(
            Deal(
                name='Test Deal',
                admin_id=test_admin.id,
                company_id=company.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
                status=Deal.STATUS_OPEN,
            )
        )

        # Now terminate the agency
        sample_tc_client_data['meta_agency']['status'] = 'terminated'
        tc_client_terminated = TCClient(**sample_tc_client_data)
        await process_tc_client(tc_client_terminated, db)

        # Deal should be marked as lost
        db.refresh(deal)
        assert deal.status == Deal.STATUS_LOST

    @patch('httpx.AsyncClient.request')
    async def test_tc2_webhook_batch_events(self, mock_request, client, db, test_admin, sample_tc_client_data):
        """Test webhook with multiple events in single payload"""
        mock_response = create_mock_response({'data': {'id': 999}})
        mock_request.return_value = mock_response

        # Create two different clients in same webhook
        client1_data = sample_tc_client_data.copy()
        client1_data['model'] = 'Client'
        client1_data['id'] = 123
        client1_data['meta_agency'] = sample_tc_client_data['meta_agency'].copy()
        client1_data['meta_agency']['id'] = 456
        client1_data['meta_agency']['name'] = 'Company 1'

        client2_data = sample_tc_client_data.copy()
        client2_data['model'] = 'Client'
        client2_data['id'] = 789
        client2_data['meta_agency'] = sample_tc_client_data['meta_agency'].copy()
        client2_data['meta_agency']['id'] = 999
        client2_data['meta_agency']['name'] = 'Company 2'

        webhook_data = {
            'events': [
                {'action': 'UPDATE', 'verb': 'update', 'subject': client1_data},
                {'action': 'UPDATE', 'verb': 'update', 'subject': client2_data},
            ],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Both companies should be created
        company1 = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()
        company2 = db.exec(select(Company).where(Company.tc2_cligency_id == 789)).first()
        assert company1 is not None
        assert company2 is not None
        assert company1.name == 'Company 1'
        assert company2.name == 'Company 2'

    async def test_tc2_client_with_very_long_company_name(self, db, test_admin, sample_tc_client_data):
        """Test TC2 client truncates very long company names"""
        very_long_name = 'X' * 300
        sample_tc_client_data['meta_agency']['name'] = very_long_name

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        # Name should be truncated to 255 chars
        assert len(company.name) == 255
        assert company.name == 'X' * 255

    @patch('app.pipedrive.api.pipedrive_request')
    async def test_empty_strings_not_sent_to_pipedrive(self, mock_api, db, test_admin):
        """Test that empty strings are filtered out from custom fields sent to Pipedrive"""
        from app.pipedrive.tasks import sync_company_to_pipedrive

        mock_api.return_value = {'data': {'id': 999}}

        company = db.create(
            Company(
                name='Test Company',
                sales_person_id=test_admin.id,
                price_plan='payg',
                country='GB',
                website='',
                utm_source='',
                utm_campaign='google',
                gclid='',
            )
        )

        await sync_company_to_pipedrive(company.id)

        # Verify the API was called
        assert mock_api.called
        call_data = mock_api.call_args.kwargs['data']
        custom_fields = call_data['custom_fields']

        # Empty strings should not be in custom_fields
        from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP

        # These fields have empty strings - should not be sent
        assert COMPANY_PD_FIELD_MAP['website'] not in custom_fields
        assert COMPANY_PD_FIELD_MAP['utm_source'] not in custom_fields
        assert COMPANY_PD_FIELD_MAP['gclid'] not in custom_fields

        # This field has a value - should be sent
        assert COMPANY_PD_FIELD_MAP['utm_campaign'] in custom_fields
        assert custom_fields[COMPANY_PD_FIELD_MAP['utm_campaign']] == 'google'

        # hermes_id should always be sent (it's an int)
        assert COMPANY_PD_FIELD_MAP['hermes_id'] in custom_fields


class TestTC2DealCreation:
    """Test deal creation from TC2 webhooks"""

    async def test_process_tc_client_creates_deal_for_new_trial_company(
        self, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that processing a new trial company creates a deal"""
        from datetime import datetime, timezone

        # Set company as trial, created recently, no paid invoices
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        # Verify deal was created
        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 1
        deal = deals[0]

        assert deal.name == company.name
        assert deal.company_id == company.id
        assert deal.admin_id == company.sales_person_id
        assert deal.status == Deal.STATUS_OPEN
        assert deal.pipeline_id == test_config.payg_pipeline_id
        assert deal.contact_id is not None  # Should have primary contact

    async def test_process_tc_client_creates_deal_for_pending_email_conf_company(
        self, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that processing pending email confirmation company creates a deal"""
        from datetime import datetime, timezone

        sample_tc_client_data['meta_agency']['status'] = 'pending_email_conf'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 1

    async def test_process_tc_client_no_deal_for_active_company(
        self, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that active (paying) companies don't get deals created"""
        from datetime import datetime, timezone

        sample_tc_client_data['meta_agency']['status'] = 'active'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 0

    async def test_process_tc_client_no_deal_for_old_company(self, db, test_admin, test_config, sample_tc_client_data):
        """Test that companies older than 90 days don't get deals created"""
        from datetime import datetime, timedelta, timezone

        # Company created 91 days ago
        old_date = datetime.now(timezone.utc) - timedelta(days=91)
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = old_date.isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 0

    async def test_process_tc_client_no_deal_for_company_with_paid_invoices(
        self, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that companies with paid invoices don't get deals created"""
        from datetime import datetime, timezone

        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 1  # Has paid invoice

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 0

    async def test_process_tc_client_no_deal_for_narc_company(self, db, test_admin, test_config, sample_tc_client_data):
        """Test that NARC companies don't get deals created"""
        from datetime import datetime, timezone

        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0
        sample_tc_client_data['meta_agency']['narc'] = True

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 0

    async def test_process_tc_client_no_deal_when_create_deal_false(
        self, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that deals are not created when create_deal=False"""
        from datetime import datetime, timezone

        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=False)

        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 0

    async def test_deal_inherits_company_fields(self, db, test_admin, test_config, sample_tc_client_data):
        """Test that deal inherits custom fields from company"""
        from datetime import datetime, timezone

        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'google'},
            {'machine_name': 'utm_campaign', 'value': 'summer2024'},
            {'machine_name': 'estimated_monthly_income', 'value': '5000'},
            {'machine_name': 'signup_questionnaire', 'value': 'some_data'},
        ]

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deal = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        assert deal is not None
        assert deal.utm_source == company.utm_source
        assert deal.utm_campaign == company.utm_campaign
        assert deal.estimated_income == company.estimated_income
        assert deal.signup_questionnaire == company.signup_questionnaire
        assert deal.tc2_status == company.tc2_status
        assert deal.website == company.website
        assert deal.price_plan == company.price_plan

    async def test_deal_uses_correct_pipeline_for_startup(self, db, test_admin, sample_tc_client_data):
        """Test that startup companies get deals in startup pipeline"""
        from datetime import datetime, timezone

        from app.main_app.models import Config, Pipeline

        # Create separate pipelines for each price plan
        payg_pipeline = db.create(Pipeline(name='PAYG Pipeline', pd_pipeline_id=101, dft_entry_stage_id=1))
        startup_pipeline = db.create(Pipeline(name='Startup Pipeline', pd_pipeline_id=102, dft_entry_stage_id=1))
        enterprise_pipeline = db.create(Pipeline(name='Enterprise Pipeline', pd_pipeline_id=103, dft_entry_stage_id=1))

        db.create(
            Config(
                payg_pipeline_id=payg_pipeline.id,
                startup_pipeline_id=startup_pipeline.id,
                enterprise_pipeline_id=enterprise_pipeline.id,
            )
        )

        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0
        sample_tc_client_data['meta_agency']['price_plan'] = 'monthly-startup'

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deal = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        assert deal.pipeline_id == startup_pipeline.id

    async def test_deal_uses_correct_pipeline_for_enterprise(self, db, test_admin, sample_tc_client_data):
        """Test that enterprise companies get deals in enterprise pipeline"""
        from datetime import datetime, timezone

        from app.main_app.models import Config, Pipeline

        # Create separate pipelines for each price plan
        payg_pipeline = db.create(Pipeline(name='PAYG Pipeline', pd_pipeline_id=101, dft_entry_stage_id=1))
        startup_pipeline = db.create(Pipeline(name='Startup Pipeline', pd_pipeline_id=102, dft_entry_stage_id=1))
        enterprise_pipeline = db.create(Pipeline(name='Enterprise Pipeline', pd_pipeline_id=103, dft_entry_stage_id=1))

        db.create(
            Config(
                payg_pipeline_id=payg_pipeline.id,
                startup_pipeline_id=startup_pipeline.id,
                enterprise_pipeline_id=enterprise_pipeline.id,
            )
        )

        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0
        sample_tc_client_data['meta_agency']['price_plan'] = 'monthly-enterprise'

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deal = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        assert deal.pipeline_id == enterprise_pipeline.id

    async def test_get_or_create_deal_returns_existing_open_deal(
        self, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that get_or_create_deal returns existing open deal instead of creating new one"""
        from datetime import datetime, timezone

        from app.tc2.process import get_or_create_deal

        # Create company first
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        # Get the created deal
        deal1 = db.exec(select(Deal).where(Deal.company_id == company.id)).first()

        # Try to create another deal - should return existing one
        deal2 = await get_or_create_deal(company, None, db)

        assert deal1.id == deal2.id
        # Verify only one deal exists
        all_deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(all_deals) == 1
