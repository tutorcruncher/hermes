"""
Tests for Pipedrive webhook endpoint.
"""

from unittest.mock import patch

import pytest

from app.core.config import settings
from app.main_app.models import Company, Contact, Pipeline, Stage
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP, CONTACT_PD_FIELD_MAP
from app.pipedrive.tasks import sync_person
from tests.helpers import pd_webhook


class TestPipedriveWebhookAuth:
    """Test the HTTP Basic auth check on the Pipedrive webhook"""

    @staticmethod
    def org_webhook(company: Company) -> dict:
        """An organization update that renames the company"""
        return {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {'id': 999, COMPANY_PD_FIELD_MAP['hermes_id']: company.id, 'name': 'Updated Name'},
            'previous': {},
        }

    @pytest.mark.parametrize(
        'kwargs',
        [
            {},
            {'auth': (settings.pd_webhook_username, 'wrong-password')},
            {'auth': ('another-user', settings.pd_webhook_password)},
            {'headers': {'Authorization': f'Bearer {settings.pd_webhook_password}'}},
            {'headers': {'Authorization': 'Basic é'.encode()}},
        ],
    )
    async def test_webhook_without_valid_credentials_is_rejected(self, client, db, test_company, kwargs):
        """A webhook without the webhook's Basic auth is rejected and changes nothing"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()
        name = test_company.name

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=self.org_webhook(test_company), **kwargs)

        assert r.status_code == 403
        assert r.json() == {'status': 'error', 'message': 'Unauthorized'}
        db.refresh(test_company)
        assert test_company.name == name

    @patch('app.pipedrive.views.settings.pd_webhook_password', None)
    async def test_webhook_is_rejected_while_no_password_is_set(self, client, db, test_company):
        """Every webhook is rejected while no password is set"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()
        name = test_company.name

        r = client.post(
            client.app.url_path_for('pipedrive-callback'),
            json=self.org_webhook(test_company),
            auth=(settings.pd_webhook_username, ''),
        )

        assert r.status_code == 403
        assert r.json() == {'status': 'error', 'message': 'Unauthorized'}
        db.refresh(test_company)
        assert test_company.name == name

    @patch('app.pipedrive.views.settings.dev_mode', True)
    async def test_dev_mode_skips_the_auth_check(self, client, db, test_company):
        """dev_mode processes a webhook without the Basic auth"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=self.org_webhook(test_company))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}
        db.refresh(test_company)
        assert test_company.name == 'Updated Name'


class TestPipedriveWebhookEndpoint:
    """Test Pipedrive webhook endpoint"""

    async def test_pipedrive_callback_processes_organization(self, client, db, test_company):
        """Test that Pipedrive callback processes organization events"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Updated Name',
                COMPANY_PD_FIELD_MAP['paid_invoice_count']: 15,
            },
            'previous': {},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify company was updated
        db.refresh(test_company)
        assert test_company.name == 'Updated Name'
        assert test_company.paid_invoice_count == 15

    async def test_pipedrive_callback_does_not_overwrite_marketing_consent(self, client, db, test_company):
        """receive_marketing_emails is TC2-authoritative: an inbound Pipedrive org webhook must not change it."""
        test_company.pd_org_id = 999
        test_company.receive_marketing_emails = True
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Updated Name',
                COMPANY_PD_FIELD_MAP['receive_marketing_emails']: 'No',
            },
            'previous': {},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))
        assert r.status_code == 200

        db.refresh(test_company)
        assert test_company.receive_marketing_emails is True

    async def test_pipedrive_callback_does_not_overwrite_operate_as_ea(self, client, db, test_company):
        """operate_as_ea is TC2-authoritative: an inbound Pipedrive org webhook must not change it."""
        test_company.pd_org_id = 999
        test_company.operate_as_ea = True
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Updated Name',
                COMPANY_PD_FIELD_MAP['operate_as_ea']: 'No',
            },
            'previous': {},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))
        assert r.status_code == 200

        db.refresh(test_company)
        assert (test_company.name, test_company.operate_as_ea) == ('Updated Name', True)

    async def test_pipedrive_callback_ignores_tc2_status(self, client, db, test_company):
        """tc2_status is TC2-authoritative: an inbound Pipedrive org webhook must not change it."""
        test_company.pd_org_id = 999
        test_company.tc2_status = 'trial'
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 999,
                'name': 'Updated Name',
                'custom_fields': {
                    COMPANY_PD_FIELD_MAP['hermes_id']: {'type': 'varchar', 'value': str(test_company.id)},
                    COMPANY_PD_FIELD_MAP['tc2_status']: {'type': 'varchar', 'value': 'terminated'},
                },
            },
            'previous': {},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))
        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        assert test_company.name == 'Updated Name'
        assert test_company.tc2_status == 'trial'

    async def test_pipedrive_callback_does_not_overwrite_country(self, client, db, test_company):
        """The custom Country field is never read back: an org webhook carrying it must not change country."""
        test_company.pd_org_id = 999
        test_company.country = 'GB'
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 999,
                'name': 'Updated Name',
                'custom_fields': {
                    COMPANY_PD_FIELD_MAP['hermes_id']: {'type': 'varchar', 'value': str(test_company.id)},
                    COMPANY_PD_FIELD_MAP['country']: {'type': 'varchar', 'value': 'Canada'},
                },
            },
            'previous': {},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))
        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        assert test_company.name == 'Updated Name'
        assert test_company.country == 'GB'

    async def test_pipedrive_callback_updates_country_from_address(self, client, db, test_company):
        """A country sales set on the org address is saved to the company."""
        test_company.pd_org_id = 999
        test_company.country = 'GB'
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 999,
                'name': 'Updated Name',
                'address': {'value': '1 George St, Sydney', 'country': 'AU', 'locality': 'Sydney', 'postal_code': None},
                'custom_fields': {
                    COMPANY_PD_FIELD_MAP['hermes_id']: {'type': 'varchar', 'value': str(test_company.id)},
                },
            },
            'previous': {
                'address': {'value': 'GB', 'country': 'GB', 'locality': None, 'postal_code': None},
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))
        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        assert test_company.country == 'AU'

    async def test_pipedrive_callback_cuts_long_country(self, client, db, test_company):
        """A country longer than Company.country allows is cut to fit, and the rest of the org update is saved."""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 999,
                'name': 'Updated Name',
                'address': {'value': 'x', 'country': 'A' * 300, 'locality': None, 'postal_code': None},
                'custom_fields': {
                    COMPANY_PD_FIELD_MAP['hermes_id']: {'type': 'varchar', 'value': str(test_company.id)},
                },
            },
            'previous': {},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))
        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        assert (test_company.name, test_company.country) == ('Updated Name', 'A' * 255)

    @pytest.mark.parametrize(
        'address',
        [
            None,
            {'value': 'GB', 'country': None, 'locality': None, 'postal_code': None},
            {'value': 'GB', 'country': 826, 'locality': None, 'postal_code': None},
        ],
    )
    async def test_pipedrive_callback_keeps_country_without_address(self, client, db, test_company, address):
        """An org with no address, or an address with no text country, leaves the company's country as it is."""
        test_company.pd_org_id = 999
        test_company.country = 'GB'
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 999,
                'name': 'Updated Name',
                'address': address,
                'custom_fields': {
                    COMPANY_PD_FIELD_MAP['hermes_id']: {'type': 'varchar', 'value': str(test_company.id)},
                },
            },
            'previous': {},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))
        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        assert (test_company.name, test_company.country) == ('Updated Name', 'GB')

    async def test_pipedrive_callback_organization_with_previous(self, client, db, test_company):
        """Test webhook for organization with previous data"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {'id': 999, COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id, 'name': 'Updated Name'},
            'previous': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Old Name',
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_person_no_data(self, client, db):
        """Test webhook for person with no data"""
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'deleted'},
            'data': None,
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_person_with_previous(self, client, db):
        """Test webhook for person with previous data"""
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 123,
                'name': 'Updated Person',
                'email': ['updated@example.com'],
            },
            'previous': {
                'id': 123,
                'name': 'Test Person',
                'email': ['test@example.com'],
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_deal_no_data(self, client, db):
        """Test webhook for deal with no data"""
        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'deleted'},
            'data': None,
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_deal_with_previous(self, client, db):
        """Test webhook for deal with previous data"""
        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 123,
                'title': 'Updated Deal',
                'status': 'won',
            },
            'previous': {
                'id': 123,
                'title': 'Test Deal',
                'status': 'open',
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_pipeline_creates_new(self, client, db, test_stage):
        """Test webhook creates new pipeline"""
        webhook_data = {
            'meta': {'entity': 'pipeline', 'action': 'added'},
            'data': {
                'id': 999,
                'name': 'New Pipeline',
                'active': True,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify pipeline was created
        from sqlmodel import select

        pipeline = db.exec(select(Pipeline).where(Pipeline.pd_pipeline_id == 999)).first()
        assert pipeline is not None
        assert pipeline.name == 'New Pipeline'

    async def test_pipedrive_callback_pipeline_with_previous(self, client, db):
        """Test webhook for pipeline with previous data"""
        webhook_data = {
            'meta': {'entity': 'pipeline', 'action': 'updated'},
            'data': {
                'id': 123,
                'name': 'Updated Pipeline',
                'active': True,
            },
            'previous': {
                'id': 123,
                'name': 'Test Pipeline',
                'active': True,
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_stage_creates_new(self, client, db, test_pipeline):
        """Test webhook creates new stage"""
        webhook_data = {
            'meta': {'entity': 'stage', 'action': 'added'},
            'data': {
                'id': 999,
                'name': 'New Stage',
                'pipeline_id': test_pipeline.pd_pipeline_id,
                'active_flag': True,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify stage was created
        from sqlmodel import select

        stage = db.exec(select(Stage).where(Stage.pd_stage_id == 999)).first()
        assert stage is not None
        assert stage.name == 'New Stage'

    async def test_pipedrive_callback_stage_with_previous(self, client, db):
        """Test webhook for stage with previous data"""
        webhook_data = {
            'meta': {'entity': 'stage', 'action': 'updated'},
            'data': {
                'id': 123,
                'name': 'Updated Stage',
                'pipeline_id': 1,
                'active_flag': True,
            },
            'previous': {
                'id': 123,
                'name': 'Test Stage',
                'pipeline_id': 1,
                'active_flag': True,
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_unknown_entity(self, client, db):
        """Test webhook with unknown entity type"""
        webhook_data = {
            'meta': {'entity': 'unknown', 'action': 'updated'},
            'data': {'id': 123},
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_invalid_data(self, client, db):
        """Test webhook with invalid data"""
        webhook_data = {
            'invalid': 'data',
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200  # Endpoint accepts any dict and ignores invalid data
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_activity_event(self, client, db):
        """Test webhook for activity event"""
        webhook_data = {
            'meta': {'entity': 'activity', 'action': 'updated'},
            'data': {
                'id': 123,
                'subject': 'Test Activity',
                'done': True,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_organization_invalid_previous(self, client, db, test_company):
        """Test webhook with invalid previous data that causes validation error"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Updated Name',
            },
            'previous': {
                'id': 'invalid',  # Invalid ID type to trigger validation error
                'name': 'Old Name',
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_person_invalid_previous(self, client, db):
        """Test webhook for person with invalid previous data"""
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 123,
                'name': 'Updated Person',
                'email': ['updated@example.com'],
            },
            'previous': {
                'id': 123,
                'name': 'Test Person',
                'email': 'not-a-list',  # Invalid email type to trigger validation error
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_deal_invalid_previous(self, client, db):
        """Test webhook for deal with invalid previous data"""
        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 123,
                'title': 'Updated Deal',
                'status': 'won',
            },
            'previous': {
                'id': 'invalid',  # Invalid ID type
                'title': 'Test Deal',
                'status': 'open',
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_pipeline_invalid_previous(self, client, db):
        """Test webhook for pipeline with invalid previous data"""
        webhook_data = {
            'meta': {'entity': 'pipeline', 'action': 'updated'},
            'data': {
                'id': 123,
                'name': 'Updated Pipeline',
                'active': True,
            },
            'previous': {
                'id': 'invalid',  # Invalid ID type
                'name': 'Test Pipeline',
                'active': True,
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_stage_invalid_previous(self, client, db):
        """Test webhook for stage with invalid previous data"""
        webhook_data = {
            'meta': {'entity': 'stage', 'action': 'updated'},
            'data': {
                'id': 123,
                'name': 'Updated Stage',
                'pipeline_id': 1,
                'active_flag': True,
            },
            'previous': {
                'id': 'invalid',  # Invalid ID type
                'name': 'Test Stage',
                'pipeline_id': 1,
                'active_flag': True,
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_person_update_v2_format(self, client, db, test_contact):
        """Test Pipedrive v2 webhook updates contact with emails/phones format"""
        from app.pipedrive.field_mappings import CONTACT_PD_FIELD_MAP

        # Set up contact with pd_person_id
        test_contact.pd_person_id = 999
        test_contact.email = 'old@example.com'
        test_contact.phone = '+441234567890'
        db.add(test_contact)
        db.commit()

        # Pipedrive v2 webhook format uses 'data' field and 'emails'/'phones' arrays
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'change'},
            'data': {
                'id': 999,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                'name': 'Updated Name',
                'emails': [{'label': 'work', 'value': 'updated@example.com', 'primary': True}],
                'phones': [{'label': 'work', 'value': '+447700900123', 'primary': True}],
                'org_id': test_contact.company_id,
            },
            'previous': {
                'emails': [{'label': 'work', 'value': 'old@example.com', 'primary': True}],
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify contact was updated
        db.refresh(test_contact)
        assert test_contact.name == 'Updated Name'
        assert test_contact.email == 'updated@example.com'
        assert test_contact.phone == '+447700900123'

    async def test_pipedrive_callback_organization_v2_nested_custom_fields(self, client, db, test_company):
        """Test Pipedrive v2 webhook with nested custom_fields structure"""
        from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP

        test_company.pd_org_id = 888
        db.add(test_company)
        db.commit()

        # Real Pipedrive v2 webhook format with nested custom_fields
        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 888,
                'name': 'Test Agency V2',
                'custom_fields': {
                    COMPANY_PD_FIELD_MAP['hermes_id']: {'type': 'double', 'value': test_company.id},
                    COMPANY_PD_FIELD_MAP['paid_invoice_count']: {'type': 'double', 'value': 10},
                    COMPANY_PD_FIELD_MAP['tc2_status']: {'type': 'varchar', 'value': 'trial'},
                    COMPANY_PD_FIELD_MAP['price_plan']: {'type': 'varchar', 'value': 'startup'},
                },
            },
            'previous': {
                'custom_fields': {
                    COMPANY_PD_FIELD_MAP['price_plan']: {'type': 'varchar', 'value': 'payg'},
                },
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify company was updated
        db.refresh(test_company)
        assert test_company.name == 'Test Agency V2'
        assert test_company.paid_invoice_count == 10
        assert test_company.tc2_status == 'pending_email_conf'

    async def test_pipedrive_callback_organization_creation_with_bdr_and_support(self, client, db, test_admin):
        """Test creating organization with BDR and support person IDs"""
        from sqlmodel import select

        from app.main_app.models import Admin, Company

        # Create additional admins for BDR and support
        bdr_admin = db.create(
            Admin(
                first_name='BDR',
                last_name='Person',
                username='bdr@example.com',
                pd_owner_id=999,
                is_bdr_person=True,
            )
        )
        support_admin = db.create(
            Admin(
                first_name='Support',
                last_name='Person',
                username='support@example.com',
                pd_owner_id=888,
                is_support_person=True,
            )
        )

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'added'},
            'data': {
                'id': 777,
                'name': 'New Company with BDR',
                'owner_id': test_admin.pd_owner_id,
                'address': {'value': 'GB', 'country': 'GB', 'locality': None, 'postal_code': None},
                COMPANY_PD_FIELD_MAP['paid_invoice_count']: 5,
                COMPANY_PD_FIELD_MAP['support_person_id']: support_admin.pd_owner_id,
                COMPANY_PD_FIELD_MAP['bdr_person_id']: bdr_admin.pd_owner_id,
                COMPANY_PD_FIELD_MAP['website']: 'https://example.com',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify company was created with all fields
        company = db.exec(select(Company).where(Company.pd_org_id == 777)).first()
        assert company is not None
        assert company.sales_person_id == test_admin.id
        assert company.support_person_id == support_admin.id
        assert company.bdr_person_id == bdr_admin.id
        assert company.paid_invoice_count == 5
        assert company.website == 'https://example.com'
        assert company.country == 'GB'

    async def test_pipedrive_callback_person_creation(self, client, db, test_company):
        """Test creating person via webhook"""
        from sqlmodel import select

        from app.main_app.models import Contact

        test_company.pd_org_id = 123
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'added'},
            'data': {
                'id': 888,
                'name': 'Test Person',
                'email': ['test@example.com'],
                'org_id': test_company.pd_org_id,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(webhook_data))

        assert r.status_code == 200

        # Verify contact was created
        contact = db.exec(select(Contact).where(Contact.pd_person_id == 888)).first()
        assert contact is not None
        assert contact.first_name == 'Test'
        assert contact.last_name == 'Person'


def _lowercase_name_webhook(contact: Contact) -> dict:
    return {
        'meta': {'entity': 'person', 'action': 'change'},
        'data': {
            'id': contact.pd_person_id,
            CONTACT_PD_FIELD_MAP['hermes_id']: contact.id,
            'name': 'john Smith',
            'first_name': '',
            'last_name': 'john Smith',
        },
        'previous': {},
    }


class TestPipedriveLowercaseNameWebhook:
    """Pipedrive puts a name that starts lowercase ('john Smith') all in last_name with an empty first_name (#418)"""

    async def test_person_webhook_with_empty_first_name_splits_name(self, client, db, test_company):
        contact = db.create(Contact(first_name='john', last_name='Smith', pd_person_id=999, company_id=test_company.id))

        r = client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(_lowercase_name_webhook(contact)))

        assert r.status_code == 200
        db.refresh(contact)
        assert contact.first_name == 'john'
        assert contact.last_name == 'Smith'

    @patch('app.pipedrive.api.pipedrive_request')
    async def test_next_sync_does_not_repeat_first_name(self, mock_api, client, db, test_company):
        contact = db.create(Contact(first_name='john', last_name='Smith', pd_person_id=999, company_id=test_company.id))
        client.post(client.app.url_path_for('pipedrive-callback'), **pd_webhook(_lowercase_name_webhook(contact)))
        mock_api.return_value = {'data': {'id': 999, 'name': 'john Smith', 'first_name': '', 'last_name': 'john Smith'}}

        await sync_person(contact.id)

        sent_names = [
            c.kwargs['data']['name'] for c in mock_api.call_args_list if 'name' in (c.kwargs.get('data') or {})
        ]
        assert sent_names == []
