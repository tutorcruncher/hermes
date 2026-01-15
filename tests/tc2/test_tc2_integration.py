"""
Integration tests for TC2 → Hermes → Pipedrive flow.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlmodel import select

from app.main_app.models import Admin, Company, Config, Contact, Deal, Meeting, Pipeline, Stage
from app.pipedrive.tasks import sync_company_to_pipedrive
from app.tc2.models import TCClient
from app.tc2.process import process_tc_client
from tests.helpers import create_mock_gcal_resource, create_mock_response


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
        """Test that processing TC2 client updates only syncable fields for existing company"""
        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)
        company_id = company.id
        original_name = company.name

        sample_tc_client_data['meta_agency']['name'] = 'Updated Agency'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 10
        sample_tc_client_data['meta_agency']['price_plan'] = 'startup'

        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db)

        assert updated_company.id == company_id
        assert updated_company.name == original_name  # name is NOT syncable
        assert updated_company.paid_invoice_count == 10  # paid_invoice_count IS syncable
        assert updated_company.price_plan == 'startup'  # price_plan IS syncable

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
        """Test that signup_questionnaire extra attribute IS updated for existing company (syncable field)"""
        sample_tc_client_data['extra_attrs'] = [{'machine_name': 'signup_questionnaire', 'value': 'initial_data'}]
        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        assert company.signup_questionnaire == 'initial_data'

        sample_tc_client_data['extra_attrs'] = [{'machine_name': 'signup_questionnaire', 'value': 'updated_data'}]
        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db)

        assert updated_company.signup_questionnaire == 'updated_data'  # IS updated (syncable field)

    async def test_process_client_updates_estimated_income_extra_attr(self, db, test_admin, sample_tc_client_data):
        """Test that estimated_monthly_income extra attribute IS updated for existing company (syncable field)"""
        sample_tc_client_data['extra_attrs'] = [{'machine_name': 'estimated_monthly_income', 'value': '5000'}]
        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        assert company.estimated_income == '5000'

        sample_tc_client_data['extra_attrs'] = [{'machine_name': 'estimated_monthly_income', 'value': '10000'}]
        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db)

        assert updated_company.estimated_income == '10000'  # IS updated (syncable field)


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

    async def test_existing_company_with_no_paid_recipients_and_deal_creation(
        self, db, test_admin, sample_tc_client_data
    ):
        """Test updating existing company with empty paid_recipients when deal creation criteria met"""
        # Create company first with paid_recipients and deal creation criteria
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)
        assert company is not None
        assert company.tc2_status == 'trial'

        # Get the created contact
        contacts = db.exec(select(Contact).where(Contact.company_id == company.id)).all()
        assert len(contacts) == 1

        # Now update the same company with empty paid_recipients (like real TC2 webhook)
        sample_tc_client_data['paid_recipients'] = []
        sample_tc_client_data['meta_agency']['status'] = 'live'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 1

        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db, create_deal=True)

        # Should not crash and should update successfully
        assert updated_company is not None
        assert updated_company.id == company.id
        assert updated_company.tc2_status == 'live'
        assert updated_company.paid_invoice_count == 1

        # Contacts should remain unchanged
        contacts_after = db.exec(select(Contact).where(Contact.company_id == company.id)).all()
        assert len(contacts_after) == 1

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

    @patch('httpx.AsyncClient.request')
    async def test_contact_without_email_syncs_to_pipedrive_successfully(
        self, mock_request, client, db, test_admin, sample_tc_client_data
    ):
        """Test that contact without email can be synced to Pipedrive without validation errors"""
        mock_response = create_mock_response({'data': {'id': 999}})
        mock_request.return_value = mock_response

        # Create contact without email
        sample_tc_client_data['paid_recipients'] = [
            {
                'id': 789,
                'first_name': 'John',
                'last_name': 'Doe',
                'email': None,  # No email
            }
        ]
        sample_tc_client_data['user']['email'] = None
        sample_tc_client_data['model'] = 'Client'

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        # This should not raise any errors
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify contact was created
        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()
        contacts = db.exec(select(Contact).where(Contact.company_id == company.id)).all()
        assert len(contacts) == 1
        assert contacts[0].email is None

        # Verify the Pipedrive API request did NOT include 'emails' field
        if mock_request.called:
            for call in mock_request.call_args_list:
                if 'persons' in str(call):
                    call_data = call.kwargs.get('json', {})
                    # emails field should not be present when email is None
                    assert 'emails' not in call_data or call_data.get('emails') is None

    @patch('httpx.AsyncClient.request')
    async def test_contact_without_phone_syncs_to_pipedrive_successfully(
        self, mock_request, client, db, test_admin, sample_tc_client_data
    ):
        """Test that contact without phone can be synced to Pipedrive without validation errors"""
        mock_response = create_mock_response({'data': {'id': 999}})
        mock_request.return_value = mock_response

        # Create contact without phone
        sample_tc_client_data['paid_recipients'] = [
            {
                'id': 789,
                'first_name': 'Jane',
                'last_name': 'Smith',
                'email': 'jane@example.com',
            }
        ]
        sample_tc_client_data['user']['phone'] = None
        sample_tc_client_data['model'] = 'Client'

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        # This should not raise any errors
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify contact was created
        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()
        contacts = db.exec(select(Contact).where(Contact.company_id == company.id)).all()
        assert len(contacts) == 1
        assert contacts[0].phone is None
        assert contacts[0].email == 'jane@example.com'

    @patch('httpx.AsyncClient.request')
    async def test_contact_with_empty_string_email_syncs_to_pipedrive(
        self, mock_request, client, db, test_admin, sample_tc_client_data
    ):
        """Test that contact with empty string email is handled correctly"""
        mock_response = create_mock_response({'data': {'id': 999}})
        mock_request.return_value = mock_response

        # Create contact with empty string email
        sample_tc_client_data['paid_recipients'] = [
            {
                'id': 789,
                'first_name': 'Bob',
                'last_name': 'Jones',
                'email': '',  # Empty string
            }
        ]
        sample_tc_client_data['user']['email'] = ''
        sample_tc_client_data['model'] = 'Client'

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        # This should not raise any errors
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify contact was created
        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()
        contacts = db.exec(select(Contact).where(Contact.company_id == company.id)).all()
        assert len(contacts) == 1

    @patch('app.pipedrive.api.pipedrive_request')
    async def test_contact_to_person_data_excludes_empty_email_and_phone(self, mock_api, db, test_admin):
        """Test that _contact_to_person_data excludes emails/phones fields when empty"""
        from app.pipedrive.tasks import sync_person

        mock_api.return_value = {'data': {'id': 999}}

        # Create company first
        company = db.create(Company(name='Test Company', sales_person_id=test_admin.id, price_plan='payg'))

        # Create contact without email and phone
        contact = db.create(Contact(first_name='Test', last_name='User', email=None, phone=None, company_id=company.id))

        await sync_person(contact.id)

        # Verify the API was called
        assert mock_api.called
        call_data = mock_api.call_args.kwargs['data']

        # emails and phones fields should NOT be present
        assert 'emails' not in call_data
        assert 'phones' not in call_data
        assert call_data['name'] == 'Test User'

    @patch('app.pipedrive.api.pipedrive_request')
    async def test_contact_to_person_data_includes_valid_email_and_phone(self, mock_api, db, test_admin):
        """Test that _contact_to_person_data includes emails/phones fields when valid"""
        from app.pipedrive.tasks import sync_person

        mock_api.return_value = {'data': {'id': 999}}

        # Create company first
        company = db.create(Company(name='Test Company', sales_person_id=test_admin.id, price_plan='payg'))

        # Create contact with email and phone
        contact = db.create(
            Contact(
                first_name='Test',
                last_name='User',
                email='test@example.com',
                phone='+1234567890',
                company_id=company.id,
            )
        )

        await sync_person(contact.id)

        # Verify the API was called
        assert mock_api.called
        call_data = mock_api.call_args.kwargs['data']

        # emails and phones fields SHOULD be present with correct structure
        assert 'emails' in call_data
        assert call_data['emails'] == [{'value': 'test@example.com', 'label': 'work', 'primary': True}]
        assert 'phones' in call_data
        assert call_data['phones'] == [{'value': '+1234567890', 'label': 'work', 'primary': True}]


class TestTC2DealCreation:
    """Test deal creation from TC2 webhooks"""

    async def test_process_tc_client_creates_deal_for_new_trial_company(
        self, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that processing a new trial company creates a deal"""

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

        sample_tc_client_data['meta_agency']['status'] = 'active'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 0

    async def test_process_tc_client_no_deal_for_old_company(self, db, test_admin, test_config, sample_tc_client_data):
        """Test that companies older than 90 days don't get deals created"""
        from datetime import timedelta

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

        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 1  # Has paid invoice

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 0

    async def test_process_tc_client_no_deal_for_narc_company(self, db, test_admin, test_config, sample_tc_client_data):
        """Test that NARC companies don't get deals created"""

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

        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=False)

        deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(deals) == 0

    async def test_deal_inherits_company_fields(self, db, test_admin, test_config, sample_tc_client_data):
        """Test that deal inherits custom fields from company"""

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

        # Create stage first
        stage = db.create(Stage(name='Test Stage', pd_stage_id=999))

        # Create separate pipelines for each price plan
        payg_pipeline = db.create(Pipeline(name='PAYG Pipeline', pd_pipeline_id=101, dft_entry_stage_id=stage.id))
        startup_pipeline = db.create(Pipeline(name='Startup Pipeline', pd_pipeline_id=102, dft_entry_stage_id=stage.id))
        enterprise_pipeline = db.create(
            Pipeline(name='Enterprise Pipeline', pd_pipeline_id=103, dft_entry_stage_id=stage.id)
        )

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

        # Create stage first
        stage = db.create(Stage(name='Test Stage', pd_stage_id=999))

        # Create separate pipelines for each price plan
        payg_pipeline = db.create(Pipeline(name='PAYG Pipeline', pd_pipeline_id=101, dft_entry_stage_id=stage.id))
        startup_pipeline = db.create(Pipeline(name='Startup Pipeline', pd_pipeline_id=102, dft_entry_stage_id=stage.id))
        enterprise_pipeline = db.create(
            Pipeline(name='Enterprise Pipeline', pd_pipeline_id=103, dft_entry_stage_id=stage.id)
        )

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

    async def test_get_or_create_deal_returns_existing_lost_deal(
        self, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that get_or_create_deal returns existing lost deal instead of creating new one"""

        from app.tc2.process import get_or_create_deal

        # Create company first
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        # Get the created deal and mark it as lost
        deal1 = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        deal1.status = Deal.STATUS_LOST
        db.add(deal1)
        db.commit()
        db.refresh(deal1)

        # Try to create another deal - should return existing lost deal, not create new one
        deal2 = await get_or_create_deal(company, None, db)

        assert deal1.id == deal2.id
        assert deal2.status == Deal.STATUS_LOST
        # Verify only one deal exists
        all_deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(all_deals) == 1

    @patch('app.pipedrive.api.pipedrive_request')
    async def test_tc2_webhook_does_not_reopen_lost_deals(
        self, mock_api, client, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that TC2 webhook does not create new deals or reopen lost deals in Pipedrive"""

        mock_api.return_value = {'data': {'id': 999}}

        # Create company with deal via webhook
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()
        deal = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        assert deal is not None
        assert deal.status == Deal.STATUS_OPEN

        # Mark deal as lost (simulating Pipedrive webhook)
        deal.status = Deal.STATUS_LOST
        db.add(deal)
        db.commit()

        # Send another TC2 webhook (like 3-hourly job would)
        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        # Should still have only one deal, and it should still be lost
        all_deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(all_deals) == 1
        assert all_deals[0].status == Deal.STATUS_LOST

    async def test_get_or_create_deal_returns_existing_won_deal(
        self, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test that get_or_create_deal returns existing won deal instead of creating new one"""

        from app.tc2.process import get_or_create_deal

        # Create company and deal
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)

        # Mark deal as won
        deal1 = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        deal1.status = Deal.STATUS_WON
        db.add(deal1)
        db.commit()
        db.refresh(deal1)

        # Try to create another deal - should return existing won deal
        deal2 = await get_or_create_deal(company, None, db)

        assert deal1.id == deal2.id
        assert deal2.status == Deal.STATUS_WON
        # Verify only one deal exists
        all_deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(all_deals) == 1

    async def test_update_company_extra_attrs_can_be_set_initially(self, db, test_admin, sample_tc_client_data):
        """Test that extra_attrs fields are set on creation and updated for existing company (now syncable)"""
        # Create company without extra_attrs
        sample_tc_client_data['extra_attrs'] = []

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        # Fields should be None
        assert company.utm_source is None
        assert company.utm_campaign is None
        assert company.estimated_income is None

        # Now TC2 sends update WITH extra_attrs - they WILL update (syncable fields)
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'facebook'},
            {'machine_name': 'utm_campaign', 'value': 'winter2024'},
            {'machine_name': 'estimated_monthly_income', 'value': '10000'},
        ]

        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db)

        # Values SHOULD be updated (syncable fields)
        assert updated_company.utm_source == 'facebook'
        assert updated_company.utm_campaign == 'winter2024'
        assert updated_company.estimated_income == '10000'

    async def test_update_company_support_bdr_stay_none_if_never_set(self, db, sample_tc_client_data):
        """Test that support_person_id and bdr_person_id stay None if never provided"""
        # Create only sales admin
        sales_admin = db.create(
            Admin(first_name='Sales', last_name='Admin', username='sales@example.com', tc2_admin_id=100)
        )

        # Create company WITHOUT support_person and bdr_person
        sample_tc_client_data['sales_person'] = {'id': 100}
        sample_tc_client_data.pop('associated_admin', None)
        sample_tc_client_data.pop('bdr_person', None)

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db)

        assert company.sales_person_id == sales_admin.id
        assert company.support_person_id is None
        assert company.bdr_person_id is None

        # TC2 sends another update still WITHOUT support_person and bdr_person
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 5

        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db)

        # They should still be None (not set to anything)
        assert updated_company.support_person_id is None
        assert updated_company.bdr_person_id is None
        assert updated_company.paid_invoice_count == 5

    async def test_webhook_with_no_paid_recipients(self, client, db, test_admin, sample_tc_client_data):
        """Test that webhook with no paid_recipients doesn't crash when trying to create deal"""
        # Create company first with recipients
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        tc_client = TCClient(**sample_tc_client_data)
        company = await process_tc_client(tc_client, db, create_deal=True)
        assert company is not None

        # Now send update webhook with empty paid_recipients (like the real webhook)
        sample_tc_client_data['paid_recipients'] = []
        sample_tc_client_data['meta_agency']['status'] = 'live'

        tc_client = TCClient(**sample_tc_client_data)
        updated_company = await process_tc_client(tc_client, db, create_deal=True)

        # Should not crash and should update successfully
        assert updated_company is not None
        assert updated_company.tc2_status == 'live'


class TestTC2SyncableFields:
    """Test TC2 syncable fields via webhook endpoint"""

    async def test_new_company_creation_sets_all_fields_and_contact(
        self, client, db, test_admin, sample_tc_client_data
    ):
        """Test that creating a new company via webhook sets all fields correctly including contact"""

        # Prepare webhook data with all fields
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['name'] = 'New Test Company'
        sample_tc_client_data['meta_agency']['country'] = 'GB'
        sample_tc_client_data['meta_agency']['website'] = 'https://testcompany.com'
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['price_plan'] = 'payg'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0
        sample_tc_client_data['meta_agency']['narc'] = False
        sample_tc_client_data['meta_agency']['pay0_dt'] = '2025-11-01T10:00:00Z'
        sample_tc_client_data['meta_agency']['pay1_dt'] = None
        sample_tc_client_data['meta_agency']['pay3_dt'] = None
        sample_tc_client_data['meta_agency']['card_saved_dt'] = '2025-11-02T12:00:00Z'
        sample_tc_client_data['meta_agency']['email_confirmed_dt'] = '2025-11-01T09:00:00Z'
        sample_tc_client_data['meta_agency']['gclid'] = 'test_gclid_123'
        sample_tc_client_data['meta_agency']['gclid_expiry_dt'] = '2025-12-01T00:00:00Z'
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'google'},
            {'machine_name': 'utm_campaign', 'value': 'summer2024'},
            {'machine_name': 'estimated_monthly_income', 'value': '5000'},
            {'machine_name': 'signup_questionnaire', 'value': 'questionnaire_data'},
        ]
        sample_tc_client_data['paid_recipients'] = [
            {'id': 789, 'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com'},
        ]

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        # Verify company was created with all fields
        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Core fields
        assert company.name == 'New Test Company'
        assert company.tc2_agency_id == 456
        assert company.tc2_cligency_id == 123
        assert company.country == 'GB'
        assert company.website == 'https://testcompany.com'
        assert company.sales_person_id == test_admin.id

        # Syncable fields
        assert company.tc2_status == 'trial'
        assert company.price_plan == 'payg'
        assert company.paid_invoice_count == 0
        assert company.narc is False
        assert company.pay0_dt == datetime(2025, 11, 1, 10)
        assert company.pay1_dt is None
        assert company.pay3_dt is None
        assert company.card_saved_dt == datetime(2025, 11, 2, 12)
        assert company.email_confirmed_dt == datetime(2025, 11, 1, 9)
        assert company.gclid == 'test_gclid_123'
        assert company.gclid_expiry_dt == datetime(2025, 12, 1, 0)
        assert company.signup_questionnaire == 'questionnaire_data'
        assert company.utm_source == 'google'
        assert company.utm_campaign == 'summer2024'
        assert company.estimated_income == '5000'

        # Verify contact was created
        contact = db.exec(select(Contact).where(Contact.company_id == company.id)).one()
        assert contact.tc2_sr_id == 789
        assert contact.first_name == 'John'
        assert contact.last_name == 'Doe'
        assert contact.email == 'john@example.com'
        assert contact.company_id == company.id

        # Now send UPDATE webhook with changed syncable and non-syncable fields
        sample_tc_client_data['meta_agency']['name'] = 'Changed Company Name'
        sample_tc_client_data['meta_agency']['country'] = 'US'
        sample_tc_client_data['meta_agency']['website'] = 'https://changed-website.com'
        sample_tc_client_data['meta_agency']['status'] = 'active'
        sample_tc_client_data['meta_agency']['price_plan'] = 'monthly-startup'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 5
        sample_tc_client_data['meta_agency']['narc'] = True
        sample_tc_client_data['meta_agency']['pay0_dt'] = '2025-10-01T08:00:00Z'
        sample_tc_client_data['meta_agency']['pay1_dt'] = '2025-10-15T10:00:00Z'
        sample_tc_client_data['meta_agency']['pay3_dt'] = '2025-11-15T14:00:00Z'
        sample_tc_client_data['meta_agency']['card_saved_dt'] = '2025-10-02T09:00:00Z'
        sample_tc_client_data['meta_agency']['email_confirmed_dt'] = '2025-09-25T11:00:00Z'
        sample_tc_client_data['meta_agency']['gclid'] = 'new_gclid_456'
        sample_tc_client_data['meta_agency']['gclid_expiry_dt'] = '2026-01-01T00:00:00Z'
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'facebook'},
            {'machine_name': 'utm_campaign', 'value': 'winter2025'},
            {'machine_name': 'estimated_monthly_income', 'value': '10000'},
            {'machine_name': 'signup_questionnaire', 'value': 'new_questionnaire_data'},
        ]

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567900,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        updated_company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Non-syncable fields should NOT change
        assert updated_company.name == 'New Test Company'
        assert updated_company.country == 'GB'
        assert updated_company.website == 'https://testcompany.com'

        # Syncable fields SHOULD change
        assert updated_company.tc2_status == 'active'
        assert updated_company.price_plan == 'startup'
        assert updated_company.paid_invoice_count == 5
        assert updated_company.narc is True
        assert updated_company.pay0_dt == datetime(2025, 10, 1, 8)
        assert updated_company.pay1_dt == datetime(2025, 10, 15, 10)
        assert updated_company.pay3_dt == datetime(2025, 11, 15, 14)
        assert updated_company.card_saved_dt == datetime(2025, 10, 2, 9)
        assert updated_company.email_confirmed_dt == datetime(2025, 9, 25, 11)
        assert updated_company.gclid == 'new_gclid_456'
        assert updated_company.gclid_expiry_dt == datetime(2026, 1, 1, 0)
        assert updated_company.signup_questionnaire == 'new_questionnaire_data'
        assert updated_company.utm_source == 'facebook'
        assert updated_company.utm_campaign == 'winter2025'
        assert updated_company.estimated_income == '10000'

    async def test_syncable_fields_updated_on_existing_company(self, client, db, test_admin, sample_tc_client_data):
        """Test that only syncable fields are updated when webhook processes existing company"""
        # Create initial company via webhook
        sample_tc_client_data['model'] = 'Client'
        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()
        original_name = company.name
        original_country = company.country
        original_website = company.website

        # Update with changed syncable and non-syncable fields
        sample_tc_client_data['meta_agency']['name'] = 'Changed Name'
        sample_tc_client_data['meta_agency']['country'] = 'United States (US)'
        sample_tc_client_data['meta_agency']['website'] = 'https://changed.com'
        sample_tc_client_data['meta_agency']['price_plan'] = 'monthly-startup'
        sample_tc_client_data['meta_agency']['pay0_dt'] = '2024-06-01T00:00:00Z'
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['narc'] = True

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        updated_company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Non-syncable fields should NOT change
        assert updated_company.name == original_name
        assert updated_company.country == original_country
        assert updated_company.website == original_website

        # Syncable fields SHOULD change
        assert updated_company.price_plan == 'startup'
        assert updated_company.pay0_dt is not None
        assert updated_company.tc2_status == 'trial'
        assert updated_company.narc is True

    async def test_all_syncable_fields_update(self, client, db, test_admin, sample_tc_client_data):
        """Test that all fields in COMPANY_SYNCABLE_FIELDS are properly updated"""
        # Create company
        sample_tc_client_data['model'] = 'Client'
        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        # Update all syncable fields
        sample_tc_client_data['meta_agency']['pay0_dt'] = '2024-01-15T00:00:00Z'
        sample_tc_client_data['meta_agency']['pay1_dt'] = '2024-02-15T00:00:00Z'
        sample_tc_client_data['meta_agency']['pay3_dt'] = '2024-03-15T00:00:00Z'
        sample_tc_client_data['meta_agency']['card_saved_dt'] = '2024-01-10T00:00:00Z'
        sample_tc_client_data['meta_agency']['price_plan'] = 'enterprise'
        sample_tc_client_data['meta_agency']['email_confirmed_dt'] = '2024-01-05T00:00:00Z'
        sample_tc_client_data['meta_agency']['gclid'] = 'test_gclid_123'
        sample_tc_client_data['meta_agency']['gclid_expiry_dt'] = '2024-02-05T00:00:00Z'
        sample_tc_client_data['meta_agency']['status'] = 'suspended'
        sample_tc_client_data['meta_agency']['narc'] = True

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Verify all syncable fields updated
        assert company.pay0_dt is not None
        assert company.pay1_dt is not None
        assert company.pay3_dt is not None
        assert company.card_saved_dt is not None
        assert company.price_plan == 'enterprise'
        assert company.email_confirmed_dt is not None
        assert company.gclid == 'test_gclid_123'
        assert company.gclid_expiry_dt is not None
        assert company.tc2_status == 'suspended'
        assert company.narc is True

    async def test_non_syncable_fields_never_update(self, client, db, test_admin, sample_tc_client_data):
        """Test that non-syncable fields are never updated for existing companies"""
        # Create company with initial values
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 5
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'initial_source'},
            {'machine_name': 'utm_campaign', 'value': 'initial_campaign'},
            {'machine_name': 'signup_questionnaire', 'value': 'initial_questionnaire'},
            {'machine_name': 'estimated_monthly_income', 'value': '5000'},
        ]

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()
        assert company.paid_invoice_count == 5
        assert company.utm_source == 'initial_source'
        assert company.utm_campaign == 'initial_campaign'
        assert company.signup_questionnaire == 'initial_questionnaire'
        assert company.estimated_income == '5000'

        # Try to update non-syncable fields (and one syncable field for comparison)
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 100  # This IS syncable
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'changed_source'},
            {'machine_name': 'utm_campaign', 'value': 'changed_campaign'},
            {'machine_name': 'signup_questionnaire', 'value': 'changed_questionnaire'},
            {'machine_name': 'estimated_monthly_income', 'value': '50000'},
        ]

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        updated_company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Syncable fields should update
        assert updated_company.paid_invoice_count == 100  # IS syncable - should update
        assert updated_company.signup_questionnaire == 'changed_questionnaire'  # IS syncable - should update
        assert updated_company.utm_source == 'changed_source'  # IS syncable - should update
        assert updated_company.utm_campaign == 'changed_campaign'  # IS syncable - should update
        assert updated_company.estimated_income == '50000'  # IS syncable - should update

    async def test_contacts_not_updated_for_existing_company(self, client, db, test_admin, sample_tc_client_data):
        """Test that contacts are not updated when company already exists"""
        # Create company with initial contact
        sample_tc_client_data['model'] = 'Client'
        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        contact = db.exec(select(Contact).where(Contact.tc2_sr_id == 789)).one()
        assert contact.first_name == 'John'
        assert contact.last_name == 'Doe'
        assert contact.email == 'john@example.com'

        # Update contact info in TC2 webhook
        sample_tc_client_data['paid_recipients'] = [
            {'id': 789, 'first_name': 'Jane', 'last_name': 'Smith', 'email': 'jane@example.com'},
        ]
        sample_tc_client_data['user']['email'] = 'jane@example.com'

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        # Contact should NOT be updated
        updated_contact = db.exec(select(Contact).where(Contact.tc2_sr_id == 789)).one()
        assert updated_contact.first_name == 'John'
        assert updated_contact.last_name == 'Doe'
        assert updated_contact.email == 'john@example.com'

    async def test_new_contacts_not_created_for_existing_company(self, client, db, test_admin, sample_tc_client_data):
        """Test that new contacts are not created when processing existing company"""
        # Create company with one contact
        sample_tc_client_data['model'] = 'Client'
        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        contacts = db.exec(select(Contact)).all()
        assert len(contacts) == 1

        # Add new recipient in TC2 webhook
        sample_tc_client_data['paid_recipients'] = [
            {'id': 789, 'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com'},
            {'id': 999, 'first_name': 'New', 'last_name': 'Person', 'email': 'new@example.com'},
        ]

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        # Should still only have 1 contact (new one not created)
        contacts = db.exec(select(Contact)).all()
        assert len(contacts) == 1
        assert contacts[0].tc2_sr_id == 789

    async def test_admin_relationships_not_updated_for_existing_company(self, client, db, sample_tc_client_data):
        """Test that admin relationships are not updated for existing companies"""
        # Create admins
        sales_admin = db.create(
            Admin(first_name='Sales', last_name='Person', username='sales@example.com', tc2_admin_id=100)
        )
        new_sales_admin = db.create(
            Admin(first_name='New', last_name='Sales', username='newsales@example.com', tc2_admin_id=200)
        )

        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['sales_person'] = {'id': sales_admin.tc2_admin_id}

        # Create company
        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()
        assert company.sales_person_id == sales_admin.id

        # Update to different sales person
        sample_tc_client_data['sales_person'] = {'id': new_sales_admin.tc2_admin_id}

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        # Sales person should NOT be updated
        updated_company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()
        assert updated_company.sales_person_id == sales_admin.id

    async def test_narc_company_closes_open_deals(self, client, db, test_admin, sample_tc_client_data):
        """Test that marking company as NARC closes all open deals"""

        # Create stage and pipeline for deal creation
        stage = db.create(Stage(name='Test Stage', pd_stage_id=999))
        pipeline = db.create(Pipeline(name='Test Pipeline', pd_pipeline_id=101, dft_entry_stage_id=stage.id))
        db.create(
            Config(
                payg_pipeline_id=pipeline.id,
                startup_pipeline_id=pipeline.id,
                enterprise_pipeline_id=pipeline.id,
            )
        )

        # Create company with deal
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0
        sample_tc_client_data['meta_agency']['created'] = '2025-11-01T00:00:00Z'

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()
        deals = db.exec(select(Deal).where(Deal.company_id == company.id, Deal.status == Deal.STATUS_OPEN)).all()
        assert len(deals) > 0

        # Mark as NARC
        sample_tc_client_data['meta_agency']['narc'] = True

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        # All deals should be closed
        open_deals = db.exec(select(Deal).where(Deal.company_id == company.id, Deal.status == Deal.STATUS_OPEN)).all()
        assert len(open_deals) == 0

        lost_deals = db.exec(select(Deal).where(Deal.company_id == company.id, Deal.status == Deal.STATUS_LOST)).all()
        assert len(lost_deals) > 0

    async def test_missing_fields_in_update_webhook_doesnt_break(self, client, db, test_admin, sample_tc_client_data):
        """Test that missing syncable fields in TC2 webhook don't break existing company update"""
        # Create company with all fields populated
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['price_plan'] = 'payg'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 5
        sample_tc_client_data['meta_agency']['narc'] = False
        sample_tc_client_data['meta_agency']['pay0_dt'] = '2025-11-01T10:00:00Z'
        sample_tc_client_data['meta_agency']['card_saved_dt'] = '2025-11-02T12:00:00Z'
        sample_tc_client_data['meta_agency']['gclid'] = 'original_gclid'
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'google'},
            {'machine_name': 'signup_questionnaire', 'value': 'initial_questionnaire'},
        ]

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()
        assert company.tc2_status == 'trial'
        assert company.paid_invoice_count == 5
        assert company.gclid == 'original_gclid'
        assert company.utm_source == 'google'
        assert company.signup_questionnaire == 'initial_questionnaire'

        # Now send update with MISSING optional fields (gclid, extra_attrs)
        sample_tc_client_data['meta_agency']['status'] = 'active'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 10
        sample_tc_client_data['meta_agency']['gclid'] = None  # TC2 might send None
        sample_tc_client_data['meta_agency']['gclid_expiry_dt'] = None
        sample_tc_client_data['extra_attrs'] = []  # No extra attrs in this update

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        updated_company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Syncable fields should update even when None
        assert updated_company.tc2_status == 'active'
        assert updated_company.paid_invoice_count == 10
        assert updated_company.gclid is None  # Set to None

        # Fields not in update extra_attrs should keep their values
        assert updated_company.utm_source == 'google'  # Not in extra_attrs, keeps original
        assert updated_company.signup_questionnaire == 'initial_questionnaire'  # Not in extra_attrs, keeps original

    @patch('app.pipedrive.api.pipedrive_request')
    async def test_updated_company_is_compatible_with_pipedrive_sync(
        self, mock_api, client, db, test_admin, sample_tc_client_data
    ):
        """Test that company updated via webhook can be synced to Pipedrive without errors"""
        # Mock all Pipedrive API calls (including background tasks)
        mock_api.return_value = {'data': {'id': 999}}

        # Create company
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['price_plan'] = 'payg'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 5
        sample_tc_client_data['meta_agency']['gclid'] = 'test_gclid'
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'google'},
            {'machine_name': 'signup_questionnaire', 'value': 'test_questionnaire'},
        ]

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        assert db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Now update via webhook
        sample_tc_client_data['meta_agency']['status'] = 'active'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 10
        sample_tc_client_data['extra_attrs'] = [
            {'machine_name': 'utm_source', 'value': 'facebook'},
        ]

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        updated_company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Reset mock to track only the explicit sync call
        mock_api.reset_mock()

        # Verify company can be synced to Pipedrive
        await sync_company_to_pipedrive(updated_company.id)

        # Verify API was called multiple times (organization, person, etc.)
        assert mock_api.called
        assert mock_api.call_count >= 1

        # Find the organization call (could be POST or PATCH)
        org_call = None
        for call in mock_api.call_args_list:
            first_arg = call.args[0] if call.args else call.kwargs.get('url', '')
            method = call.kwargs.get('method', '')
            # Check for organization endpoint (either 'organizations' POST or 'organizations/{id}' PATCH)
            if 'organizations' in first_arg and method in ('POST', 'PATCH'):
                org_call = call
                break

        assert org_call is not None, 'Organization API call should have been made'
        call_data = org_call.kwargs['data']

        # Verify all required fields are present
        assert 'name' in call_data
        assert 'owner_id' in call_data
        assert call_data['name'] == updated_company.name

        # Verify custom fields are properly formatted
        assert 'custom_fields' in call_data
        custom_fields = call_data['custom_fields']

        # All custom field values should be serializable (not causing errors)
        assert isinstance(custom_fields, dict)

        # Verify updated syncable fields are in the payload
        from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP

        pd_field_id = COMPANY_PD_FIELD_MAP['tc2_status']
        assert pd_field_id in custom_fields
        assert custom_fields[pd_field_id] == 'active'

    async def test_signup_questionnaire_from_meta_agency_new_company(self, client, db, test_admin, sample_tc_client_data):
        """Test that signup_questionnaire dict from meta_agency is stored as JSON string for new company"""
        import json

        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['signup_questionnaire'] = {
            'how-did-you-hear-about-us': 'Search engine (Google, Bing, etc.)',
            'are-lessons-mostly-remote-or-in-person': 'Mostly in-person',
            'how-do-you-currently-match-your-students-to-tutors': 'Students can view a list of Tutors',
            'do-you-provide-mostly-one-to-one-lessons-or-group-classes': 'Entirely one to one',
            'how-many-students-are-currently-actively-using-your-service': 5,
            'do-you-take-payment-from-clients-upfront-or-after-the-lesson-takes-place': 'Entirely upfront',
        }

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Verify signup_questionnaire is stored as JSON string
        assert company.signup_questionnaire is not None
        assert isinstance(company.signup_questionnaire, str)

        # Verify it can be parsed back to the original dict
        parsed = json.loads(company.signup_questionnaire)
        assert parsed['how-did-you-hear-about-us'] == 'Search engine (Google, Bing, etc.)'
        assert parsed['how-many-students-are-currently-actively-using-your-service'] == 5

    async def test_signup_questionnaire_from_meta_agency_existing_company(
        self, client, db, test_admin, sample_tc_client_data
    ):
        """Test that signup_questionnaire dict from meta_agency updates existing company"""
        import json

        # Create company without signup_questionnaire
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['signup_questionnaire'] = None

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()
        assert company.signup_questionnaire is None

        # Now update with signup_questionnaire dict
        sample_tc_client_data['meta_agency']['signup_questionnaire'] = {
            'how-did-you-hear-about-us': 'Word of mouth',
            'how-many-students-are-currently-actively-using-your-service': 10,
        }

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        db.expire_all()
        updated_company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Verify signup_questionnaire is updated and stored as JSON string
        assert updated_company.signup_questionnaire is not None
        parsed = json.loads(updated_company.signup_questionnaire)
        assert parsed['how-did-you-hear-about-us'] == 'Word of mouth'
        assert parsed['how-many-students-are-currently-actively-using-your-service'] == 10

    @patch('app.pipedrive.api.pipedrive_request')
    async def test_signup_questionnaire_sent_to_pipedrive(self, mock_api, client, db, test_admin, sample_tc_client_data):
        """Test that signup_questionnaire JSON is correctly sent to Pipedrive"""
        import json

        from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP

        mock_api.return_value = {'data': {'id': 999}}

        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['signup_questionnaire'] = {
            'how-did-you-hear-about-us': 'Search engine',
            'students-count': 25,
        }

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).one()

        # Reset mock to track only the explicit sync call
        mock_api.reset_mock()

        # Sync to Pipedrive
        await sync_company_to_pipedrive(company.id)

        # Find the organization call
        org_call = None
        for call in mock_api.call_args_list:
            first_arg = call.args[0] if call.args else call.kwargs.get('url', '')
            method = call.kwargs.get('method', '')
            if 'organizations' in first_arg and method in ('POST', 'PATCH'):
                org_call = call
                break

        assert org_call is not None, 'Organization API call should have been made'
        call_data = org_call.kwargs['data']

        # Verify signup_questionnaire is in custom_fields as JSON string
        custom_fields = call_data['custom_fields']
        pd_field_id = COMPANY_PD_FIELD_MAP['signup_questionnaire']
        assert pd_field_id in custom_fields

        # Verify the value is a JSON string that can be parsed
        signup_q_value = custom_fields[pd_field_id]
        assert isinstance(signup_q_value, str)
        parsed = json.loads(signup_q_value)
        assert parsed['how-did-you-hear-about-us'] == 'Search engine'
        assert parsed['students-count'] == 25


class TestGetOrCreateDealConsolidation:
    """Test consolidated get_or_create_deal function with filters"""

    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    @patch('fastapi.BackgroundTasks.add_task')
    @patch('httpx.AsyncClient.request')
    async def test_callbooker_flow_with_multiple_deals_gets_only_open_deal(
        self, mock_request, mock_add_task, mock_gcal_builder, client, db, test_admin, test_config
    ):
        """Test callbooker flow gets OPEN deal when multiple deals exist (uses status filter)"""
        from tests.helpers import create_mock_response

        mock_gcal_builder.return_value = create_mock_gcal_resource(test_admin.email)

        mock_response = create_mock_response({'data': {'id': 999}})
        mock_request.return_value = mock_response

        # Create company with sales person
        company = db.create(
            Company(name='Test Company', sales_person_id=test_admin.id, price_plan='payg', country='GB')
        )

        # Create contact
        contact = db.create(Contact(first_name='John', last_name='Doe', email='john@test.com', company_id=company.id))

        # Create two deals - one LOST, one OPEN
        lost_deal = db.create(
            Deal(
                name='Lost Deal',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_LOST,
            )
        )

        open_deal = db.create(
            Deal(
                name='Open Deal',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_OPEN,
            )
        )

        # Book a sales call via callbooker (end-to-end)
        r = client.post(
            client.app.url_path_for('book-sales-call'),
            json={
                'admin_id': test_admin.id,
                'name': 'John Doe',
                'email': 'john@test.com',
                'company_id': company.id,
                'company_name': 'Test Company',
                'website': 'https://test.com',
                'country': 'GB',
                'estimated_income': 1000,
                'currency': 'GBP',
                'price_plan': 'payg',
                'meeting_dt': '2026-07-03T09:00:00Z',
            },
        )

        assert r.status_code == 200

        # Verify meeting was created and linked to OPEN deal (not lost)
        meeting = db.exec(select(Meeting).where(Meeting.company_id == company.id)).first()
        assert meeting is not None
        assert meeting.deal_id == open_deal.id  # Should be linked to open deal, not lost_deal
        assert meeting.admin_id == test_admin.id
        assert meeting.contact_id == contact.id
        assert meeting.meeting_type == Meeting.TYPE_SALES

        # Verify no new deals were created
        all_deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(all_deals) == 2  # Still only 2 deals

        # Verify the deals are still the same ones
        deal_ids = {d.id for d in all_deals}
        assert deal_ids == {lost_deal.id, open_deal.id}

    @patch('httpx.AsyncClient.request')
    async def test_tc2_flow_with_multiple_deals_gets_first_deal(
        self, mock_request, client, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test TC2 flow gets first deal regardless of status (no status filter)"""
        from tests.helpers import create_mock_response

        mock_response = create_mock_response({'data': {'id': 999}})
        mock_request.return_value = mock_response

        # Create company first without deal
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['status'] = 'active'  # Won't create deal
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 10

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()

        # Manually create two deals - one LOST, one WON
        lost_deal = db.create(
            Deal(
                name='Lost Deal',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_LOST,
            )
        )

        won_deal = db.create(
            Deal(
                name='Won Deal',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_WON,
            )
        )

        # Now send TC2 webhook that would trigger deal creation
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        # Verify no new deal was created (TC2 found existing one)
        all_deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(all_deals) == 2  # Still only 2 deals

        # Verify the deals are still the same ones (no duplicates)
        deal_ids = {d.id for d in all_deals}
        assert deal_ids == {lost_deal.id, won_deal.id}

        # TC2 should have found first deal (lost_deal) since no status filter
        first_deal = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        assert first_deal.id == lost_deal.id

    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    @patch('fastapi.BackgroundTasks.add_task')
    async def test_callbooker_flow_creates_new_open_deal_when_only_lost_deals_exist(
        self, mock_add_task, mock_gcal_builder, client, db, test_admin, test_config
    ):
        """Test callbooker creates new deal when only LOST deals exist (status filter finds nothing)"""

        mock_gcal_builder.return_value = create_mock_gcal_resource(test_admin.email)

        # Create company
        company = db.create(
            Company(name='Test Company', sales_person_id=test_admin.id, price_plan='payg', country='GB')
        )

        # Create contact
        contact = db.create(Contact(first_name='John', last_name='Doe', email='john@test.com', company_id=company.id))

        # Create only LOST deal
        lost_deal = db.create(
            Deal(
                name='Lost Deal',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_LOST,
            )
        )

        # Book sales call
        r = client.post(
            client.app.url_path_for('book-sales-call'),
            json={
                'admin_id': test_admin.id,
                'name': 'John Doe',
                'email': 'john@test.com',
                'company_id': company.id,
                'company_name': 'Test Company',
                'website': 'https://test.com',
                'country': 'GB',
                'estimated_income': 1000,
                'currency': 'GBP',
                'price_plan': 'payg',
                'meeting_dt': '2026-07-03T09:00:00Z',
            },
        )

        assert r.status_code == 200

        # Verify new OPEN deal was created
        all_deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(all_deals) == 2  # Lost + new Open

        open_deals = [d for d in all_deals if d.status == Deal.STATUS_OPEN]
        assert len(open_deals) == 1

        new_deal = open_deals[0]
        assert new_deal.id != lost_deal.id  # It's a NEW deal
        assert new_deal.status == Deal.STATUS_OPEN
        assert new_deal.company_id == company.id
        assert new_deal.admin_id == test_admin.id
        assert new_deal.pipeline_id == test_config.payg_pipeline_id
        assert new_deal.name == company.name
        assert new_deal.contact_id == contact.id

        meeting = db.exec(select(Meeting).where(Meeting.company_id == company.id)).first()
        assert meeting.deal_id == new_deal.id
        assert meeting.admin_id == test_admin.id
        assert meeting.contact_id == contact.id

    @patch('httpx.AsyncClient.request')
    async def test_tc2_webhook_does_not_create_duplicate_when_multiple_deals_exist(
        self, mock_request, client, db, test_admin, test_config, sample_tc_client_data
    ):
        """Test TC2 webhook returns existing deal when multiple deals exist (avoids MultipleResultsFound error)"""
        from tests.helpers import create_mock_response

        mock_response = create_mock_response({'data': {'id': 999}})
        mock_request.return_value = mock_response

        # Create company via TC2 webhook
        sample_tc_client_data['model'] = 'Client'
        sample_tc_client_data['meta_agency']['status'] = 'active'
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 5

        webhook_data = {
            'events': [{'action': 'CREATE', 'verb': 'create', 'subject': sample_tc_client_data}],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()

        # Manually create multiple deals with different statuses
        deal1 = db.create(
            Deal(
                name='Deal 1',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_OPEN,
            )
        )

        deal2 = db.create(
            Deal(
                name='Deal 2',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_LOST,
            )
        )

        deal3 = db.create(
            Deal(
                name='Deal 3',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_WON,
            )
        )

        # Send TC2 webhook that would trigger deal creation
        sample_tc_client_data['meta_agency']['status'] = 'trial'
        sample_tc_client_data['meta_agency']['created'] = datetime.now(timezone.utc).isoformat()
        sample_tc_client_data['meta_agency']['paid_invoice_count'] = 0

        webhook_data = {
            'events': [{'action': 'UPDATE', 'verb': 'update', 'subject': sample_tc_client_data}],
            '_request_time': 1234567891,
        }

        # This should NOT crash with MultipleResultsFound error
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert r.status_code == 200

        # Verify no additional deals were created
        all_deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(all_deals) == 3  # Still only 3 deals

        # Verify the deals are still the same ones (no duplicates)
        deal_ids = {d.id for d in all_deals}
        assert deal_ids == {deal1.id, deal2.id, deal3.id}

        # Verify statuses remain unchanged
        db.refresh(deal1)
        db.refresh(deal2)
        db.refresh(deal3)
        assert deal1.status == Deal.STATUS_OPEN
        assert deal2.status == Deal.STATUS_LOST
        assert deal3.status == Deal.STATUS_WON

    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    @patch('fastapi.BackgroundTasks.add_task')
    async def test_callbooker_multiple_open_deals_returns_first_open(
        self, mock_add_task, mock_gcal_builder, client, db, test_admin, test_config
    ):
        """Test callbooker returns first OPEN deal when multiple OPEN deals exist"""

        mock_gcal_builder.return_value = create_mock_gcal_resource(test_admin.email)

        # Create company
        company = db.create(
            Company(name='Test Company', sales_person_id=test_admin.id, price_plan='payg', country='GB')
        )

        # Create contact
        contact = db.create(Contact(first_name='John', last_name='Doe', email='john@test.com', company_id=company.id))

        # Create multiple OPEN deals
        open_deal1 = db.create(
            Deal(
                name='Open Deal 1',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_OPEN,
            )
        )

        open_deal2 = db.create(
            Deal(
                name='Open Deal 2',
                company_id=company.id,
                admin_id=test_admin.id,
                pipeline_id=test_config.payg_pipeline_id,
                stage_id=1,
                status=Deal.STATUS_OPEN,
            )
        )

        # Book sales call
        r = client.post(
            client.app.url_path_for('book-sales-call'),
            json={
                'admin_id': test_admin.id,
                'name': 'John Doe',
                'email': 'john@test.com',
                'company_id': company.id,
                'company_name': 'Test Company',
                'website': 'https://test.com',
                'country': 'GB',
                'estimated_income': 1000,
                'currency': 'GBP',
                'price_plan': 'payg',
                'meeting_dt': '2026-07-03T09:00:00Z',
            },
        )

        assert r.status_code == 200

        # Verify meeting linked to first open deal, no new deal created
        meeting = db.exec(select(Meeting).where(Meeting.company_id == company.id)).first()
        assert meeting.deal_id == open_deal1.id  # Linked to FIRST open deal, not second
        assert meeting.admin_id == test_admin.id
        assert meeting.contact_id == contact.id
        assert meeting.meeting_type == Meeting.TYPE_SALES

        all_deals = db.exec(select(Deal).where(Deal.company_id == company.id)).all()
        assert len(all_deals) == 2  # Still only 2 deals

        # Verify the deals are still the same ones (no duplicates)
        deal_ids = {d.id for d in all_deals}
        assert deal_ids == {open_deal1.id, open_deal2.id}

        # Verify both are still open
        db.refresh(open_deal1)
        db.refresh(open_deal2)
        assert open_deal1.status == Deal.STATUS_OPEN
        assert open_deal2.status == Deal.STATUS_OPEN
