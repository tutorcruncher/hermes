"""
Tests for Pipedrive webhooks with null/missing fields.
"""

from datetime import date

from app.main_app.models import Deal
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP, CONTACT_PD_FIELD_MAP, DEAL_PD_FIELD_MAP


class TestPipedriveWebhookNullFields:
    """Test Pipedrive webhooks with null/missing fields"""

    async def test_org_webhook_with_null_date_fields(self, client, db, test_company):
        """Test organization webhook with null date fields doesn't override existing dates"""
        test_company.pd_org_id = 999
        test_company.pay0_dt = date(2024, 1, 1)
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Test Company',
                COMPANY_PD_FIELD_MAP['pay0_dt']: None,  # Explicitly null
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # pay0_dt should remain unchanged when null is sent
        db.refresh(test_company)
        assert test_company.pay0_dt is not None

    async def test_person_webhook_with_no_name(self, client, db, test_contact):
        """Test person webhook with no name field"""
        test_contact.pd_person_id = 888
        db.add(test_contact)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                # No name field
                'email': ['test@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_person_webhook_with_empty_email_list(self, client, db, test_contact):
        """Test person webhook with empty email list"""
        test_contact.pd_person_id = 888
        db.add(test_contact)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                'name': 'Test Person',
                'email': [],  # Empty list
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_deal_webhook_with_no_title(self, client, db, test_admin, test_company, test_pipeline, test_stage):
        """Test deal webhook with no title preserves existing name"""
        deal = db.create(
            Deal(
                name='Original Deal',
                pd_deal_id=888,
                admin_id=test_admin.id,
                company_id=test_company.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 888,
                DEAL_PD_FIELD_MAP['hermes_id']: deal.id,
                # No title field
                'status': 'open',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Name should remain unchanged
        db.refresh(deal)
        assert deal.name == 'Original Deal'

    async def test_deal_webhook_with_no_status(self, client, db, test_admin, test_company, test_pipeline, test_stage):
        """Test deal webhook with no status preserves existing status"""
        deal = db.create(
            Deal(
                name='Test Deal',
                pd_deal_id=888,
                admin_id=test_admin.id,
                company_id=test_company.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
                status='open',
            )
        )

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 888,
                DEAL_PD_FIELD_MAP['hermes_id']: deal.id,
                'title': 'Updated Deal',
                # No status field
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Status should remain unchanged
        db.refresh(deal)
        assert deal.status == 'open'

    async def test_pipeline_webhook_with_no_name(self, client, db, test_pipeline):
        """Test pipeline webhook with no name preserves existing name"""
        test_pipeline.pd_pipeline_id = 999
        test_pipeline.name = 'Original Pipeline'
        db.add(test_pipeline)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'pipeline', 'action': 'updated'},
            'data': {
                'id': 999,
                # No name field
                'active': True,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Name should remain unchanged
        db.refresh(test_pipeline)
        assert test_pipeline.name == 'Original Pipeline'

    async def test_stage_webhook_with_no_name(self, client, db, test_stage):
        """Test stage webhook with no name preserves existing name"""
        test_stage.pd_stage_id = 999
        test_stage.name = 'Original Stage'
        db.add(test_stage)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'stage', 'action': 'updated'},
            'data': {
                'id': 999,
                # No name field
                'pipeline_id': 1,
                'active_flag': True,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Name should remain unchanged
        db.refresh(test_stage)
        assert test_stage.name == 'Original Stage'

    async def test_org_webhook_updating_owner_to_nonexistent_admin(self, client, db, test_company):
        """Test organization webhook with owner_id that doesn't exist in Hermes"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Test Company',
                'owner_id': 9999,  # Doesn't exist in Hermes
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # sales_person_id should remain unchanged
        db.refresh(test_company)
        assert test_company.sales_person_id == test_company.sales_person_id

    async def test_person_webhook_with_nonexistent_org_id(self, client, db, test_contact):
        """Test person webhook with org_id that doesn't exist in Hermes"""
        test_contact.pd_person_id = 888
        db.add(test_contact)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                'name': 'Test Person',
                'email': ['test@example.com'],
                'org_id': 9999,  # Doesn't exist
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # company_id should remain unchanged
        db.refresh(test_contact)
        assert test_contact.company_id == test_contact.company_id

    async def test_deal_webhook_with_nonexistent_relationships(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test deal webhook with user_id, org_id, person_id that don't exist"""
        deal = db.create(
            Deal(
                name='Test Deal',
                pd_deal_id=888,
                admin_id=test_admin.id,
                company_id=test_company.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 888,
                DEAL_PD_FIELD_MAP['hermes_id']: deal.id,
                'title': 'Test Deal',
                'status': 'open',
                'user_id': 9999,  # Doesn't exist
                'org_id': 9999,  # Doesn't exist
                'person_id': 9999,  # Doesn't exist
                'pipeline_id': 9999,  # Doesn't exist
                'stage_id': 9999,  # Doesn't exist
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Relationships should remain unchanged
        db.refresh(deal)
        assert deal.admin_id == test_admin.id
        assert deal.company_id == test_company.id

    async def test_org_with_very_long_name_truncated(self, client, db, test_company):
        """Test organization webhook truncates very long names to 255 chars"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        very_long_name = 'A' * 300  # 300 characters

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': very_long_name,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        # Name should be truncated to 255 chars
        assert len(test_company.name) == 255
        assert test_company.name == 'A' * 255

    async def test_person_with_very_long_name_truncated(self, client, db, test_contact):
        """Test person webhook truncates very long names to 255 chars"""
        test_contact.pd_person_id = 888
        db.add(test_contact)
        db.commit()

        very_long_name = 'FirstName' * 40 + ' ' + 'LastName' * 40  # > 255 chars

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                'name': very_long_name,
                'email': ['test@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_contact)
        # Names should be truncated to 255 chars
        assert len(test_contact.first_name) <= 255 if test_contact.first_name else True
        assert len(test_contact.last_name) <= 255
