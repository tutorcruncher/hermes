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
            'current': {
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
            'current': {'id': 999, COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id, 'name': 'Updated Name'},
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
            'current': None,
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_person_with_previous(self, client, db):
        """Test webhook for person with previous data"""
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'current': {
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
            'current': None,
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_pipedrive_callback_deal_with_previous(self, client, db):
        """Test webhook for deal with previous data"""
        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'current': {
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

    async def test_pipedrive_callback_pipeline_creates_new(self, client, db):
        """Test webhook creates new pipeline"""
        webhook_data = {
            'meta': {'entity': 'pipeline', 'action': 'added'},
            'current': {
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
            'current': {
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
            'current': {
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
            'current': {
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
            'current': {'id': 123},
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
            'current': {
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
            'current': {
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
            'current': {
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
            'current': {
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
            'current': {
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
            'current': {
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
