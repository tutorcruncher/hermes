"""
Tests for Pipedrive webhook endpoint.
"""

from app.main_app.models import Pipeline, Stage
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP


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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify company was updated
        db.refresh(test_company)
        assert test_company.name == 'Updated Name'
        assert test_company.paid_invoice_count == 15

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_person_no_data(self, client, db):
        """Test webhook for person with no data"""
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'deleted'},
            'data': None,
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_deal_no_data(self, client, db):
        """Test webhook for deal with no data"""
        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'deleted'},
            'data': None,
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_unknown_entity(self, client, db):
        """Test webhook with unknown entity type"""
        webhook_data = {
            'meta': {'entity': 'unknown', 'action': 'updated'},
            'data': {'id': 123},
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_invalid_data(self, client, db):
        """Test webhook with invalid data"""
        webhook_data = {
            'invalid': 'data',
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify company was updated
        db.refresh(test_company)
        assert test_company.name == 'Test Agency V2'
        assert test_company.paid_invoice_count == 10
        assert test_company.tc2_status == 'trial'

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
                'address_country': 'GB',
                COMPANY_PD_FIELD_MAP['paid_invoice_count']: 5,
                COMPANY_PD_FIELD_MAP['support_person_id']: support_admin.pd_owner_id,
                COMPANY_PD_FIELD_MAP['bdr_person_id']: bdr_admin.pd_owner_id,
                COMPANY_PD_FIELD_MAP['website']: 'https://example.com',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

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

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200

        # Verify contact was created
        contact = db.exec(select(Contact).where(Contact.pd_person_id == 888)).first()
        assert contact is not None
        assert contact.first_name == 'Test'
        assert contact.last_name == 'Person'
