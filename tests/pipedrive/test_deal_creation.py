"""Tests for Pipedrive deal creation from webhooks"""

import pytest
from sqlmodel import select

from app.main_app.models import Deal
from app.pipedrive.field_mappings import DEAL_PD_FIELD_MAP


@pytest.mark.asyncio
class TestDealCreationFromPipedrive:
    """Test that deals created in Pipedrive are properly created in Hermes"""

    async def test_deal_created_with_all_required_fields(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test deal creation when all required foreign keys exist"""
        # Set up Pipedrive IDs for existing entities
        test_admin.pd_owner_id = 123
        test_company.pd_org_id = 456
        test_pipeline.pd_pipeline_id = 789
        test_stage.pd_stage_id = 101
        db.add(test_admin)
        db.add(test_company)
        db.add(test_pipeline)
        db.add(test_stage)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'added'},
            'data': {
                'id': 999,  # Pipedrive deal ID
                'title': 'New Deal from Pipedrive',
                'status': 'open',
                'owner_id': 123,  # Links to test_admin
                'org_id': 456,  # Links to test_company
                'pipeline_id': 789,  # Links to test_pipeline
                'stage_id': 101,  # Links to test_stage
                'person_id': None,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify deal was created in Hermes
        deal = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).first()
        assert deal is not None
        assert deal.name == 'New Deal from Pipedrive'
        assert deal.status == 'open'
        assert deal.admin_id == test_admin.id
        assert deal.company_id == test_company.id
        assert deal.pipeline_id == test_pipeline.id
        assert deal.stage_id == test_stage.id
        assert deal.contact_id is None

    async def test_deal_created_with_optional_contact(
        self, client, db, test_admin, test_company, test_pipeline, test_stage, test_contact
    ):
        """Test deal creation with optional contact linked"""
        # Set up Pipedrive IDs
        test_admin.pd_owner_id = 123
        test_company.pd_org_id = 456
        test_pipeline.pd_pipeline_id = 789
        test_stage.pd_stage_id = 101
        test_contact.pd_person_id = 202
        db.add(test_admin)
        db.add(test_company)
        db.add(test_pipeline)
        db.add(test_stage)
        db.add(test_contact)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'added'},
            'data': {
                'id': 999,
                'title': 'Deal with Contact',
                'status': 'open',
                'owner_id': 123,
                'org_id': 456,
                'pipeline_id': 789,
                'stage_id': 101,
                'person_id': 202,  # Links to test_contact
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200

        # Verify contact was linked
        deal = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).first()
        assert deal is not None
        assert deal.contact_id == test_contact.id

    async def test_deal_created_with_custom_fields(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test deal creation populates custom fields from Pipedrive v2 webhook"""
        # Set up Pipedrive IDs
        test_admin.pd_owner_id = 123
        test_company.pd_org_id = 456
        test_pipeline.pd_pipeline_id = 789
        test_stage.pd_stage_id = 101
        db.add(test_admin)
        db.add(test_company)
        db.add(test_pipeline)
        db.add(test_stage)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'added'},
            'data': {
                'id': 999,
                'title': 'Deal with Custom Fields',
                'status': 'open',
                'owner_id': 123,
                'org_id': 456,
                'pipeline_id': 789,
                'stage_id': 101,
                'custom_fields': {
                    DEAL_PD_FIELD_MAP['tc2_status']: {'type': 'varchar', 'value': 'active'},
                    DEAL_PD_FIELD_MAP['price_plan']: {'type': 'varchar', 'value': 'payg'},
                    DEAL_PD_FIELD_MAP['website']: {'type': 'varchar', 'value': 'https://example.com'},
                    DEAL_PD_FIELD_MAP['utm_source']: {'type': 'varchar', 'value': 'google'},
                    DEAL_PD_FIELD_MAP['utm_campaign']: {'type': 'varchar', 'value': 'spring2024'},
                    DEAL_PD_FIELD_MAP['paid_invoice_count']: {'type': 'int', 'value': 5},
                },
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200

        # Verify custom fields were populated
        deal = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).first()
        assert deal is not None
        assert deal.tc2_status == 'active'
        assert deal.price_plan == 'payg'
        assert deal.website == 'https://example.com'
        assert deal.utm_source == 'google'
        assert deal.utm_campaign == 'spring2024'
        assert deal.paid_invoice_count == 5

    async def test_deal_creation_fails_without_admin(self, client, db, test_company, test_pipeline, test_stage):
        """Test deal creation fails gracefully when admin not found"""
        test_company.pd_org_id = 456
        test_pipeline.pd_pipeline_id = 789
        test_stage.pd_stage_id = 101
        db.add(test_company)
        db.add(test_pipeline)
        db.add(test_stage)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'added'},
            'data': {
                'id': 999,
                'title': 'Deal without Admin',
                'status': 'open',
                'owner_id': 999,  # Non-existent admin
                'org_id': 456,
                'pipeline_id': 789,
                'stage_id': 101,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200  # Webhook still returns success

        # Verify deal was NOT created
        deal = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).first()
        assert deal is None

    async def test_deal_creation_fails_without_company(self, client, db, test_admin, test_pipeline, test_stage):
        """Test deal creation fails gracefully when company not found"""
        test_admin.pd_owner_id = 123
        test_pipeline.pd_pipeline_id = 789
        test_stage.pd_stage_id = 101
        db.add(test_admin)
        db.add(test_pipeline)
        db.add(test_stage)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'added'},
            'data': {
                'id': 999,
                'title': 'Deal without Company',
                'status': 'open',
                'owner_id': 123,
                'org_id': 999,  # Non-existent company
                'pipeline_id': 789,
                'stage_id': 101,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200

        # Verify deal was NOT created
        deal = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).first()
        assert deal is None

    async def test_deal_creation_fails_without_pipeline(self, client, db, test_admin, test_company, test_stage):
        """Test deal creation fails gracefully when pipeline not found"""
        test_admin.pd_owner_id = 123
        test_company.pd_org_id = 456
        test_stage.pd_stage_id = 101
        db.add(test_admin)
        db.add(test_company)
        db.add(test_stage)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'added'},
            'data': {
                'id': 999,
                'title': 'Deal without Pipeline',
                'status': 'open',
                'owner_id': 123,
                'org_id': 456,
                'pipeline_id': 999,  # Non-existent pipeline
                'stage_id': 101,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200

        # Verify deal was NOT created
        deal = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).first()
        assert deal is None

    async def test_deal_creation_fails_without_stage(self, client, db, test_admin, test_company, test_pipeline):
        """Test deal creation fails gracefully when stage not found"""
        test_admin.pd_owner_id = 123
        test_company.pd_org_id = 456
        test_pipeline.pd_pipeline_id = 789
        db.add(test_admin)
        db.add(test_company)
        db.add(test_pipeline)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'added'},
            'data': {
                'id': 999,
                'title': 'Deal without Stage',
                'status': 'open',
                'owner_id': 123,
                'org_id': 456,
                'pipeline_id': 789,
                'stage_id': 999,  # Non-existent stage
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200

        # Verify deal was NOT created
        deal = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).first()
        assert deal is None

    async def test_deal_update_still_works(self, client, db, test_admin, test_company, test_pipeline, test_stage):
        """Test that existing deal update functionality still works"""
        # Set up Pipedrive IDs
        test_admin.pd_owner_id = 123
        test_company.pd_org_id = 456
        test_pipeline.pd_pipeline_id = 789
        test_stage.pd_stage_id = 101
        db.add(test_admin)
        db.add(test_company)
        db.add(test_pipeline)
        db.add(test_stage)
        db.commit()

        # Create an existing deal
        existing_deal = Deal(
            pd_deal_id=999,
            name='Original Deal Name',
            status='open',
            admin_id=test_admin.id,
            company_id=test_company.id,
            pipeline_id=test_pipeline.id,
            stage_id=test_stage.id,
        )
        db.add(existing_deal)
        db.commit()
        db.refresh(existing_deal)

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 999,
                'title': 'Updated Deal Name',
                'status': 'won',
                'owner_id': 123,
                'org_id': 456,
                'pipeline_id': 789,
                'stage_id': 101,
                DEAL_PD_FIELD_MAP['hermes_id']: existing_deal.id,
            },
            'previous': {'title': 'Original Deal Name'},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200

        # Verify deal was updated (not created as duplicate)
        db.refresh(existing_deal)
        assert existing_deal.name == 'Updated Deal Name'
        assert existing_deal.status == 'won'

        # Verify only one deal with this pd_deal_id exists
        deals = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).all()
        assert len(deals) == 1

    async def test_deal_created_with_no_title_gets_default(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test deal creation with no title uses default name"""
        test_admin.pd_owner_id = 123
        test_company.pd_org_id = 456
        test_pipeline.pd_pipeline_id = 789
        test_stage.pd_stage_id = 101
        db.add(test_admin)
        db.add(test_company)
        db.add(test_pipeline)
        db.add(test_stage)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'added'},
            'data': {
                'id': 999,
                'title': None,  # No title provided
                'status': 'open',
                'owner_id': 123,
                'org_id': 456,
                'pipeline_id': 789,
                'stage_id': 101,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200

        # Verify deal was created with default name
        deal = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).first()
        assert deal is not None
        assert deal.name == 'Untitled Deal'

    async def test_deal_created_with_long_title_is_truncated(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test deal creation with very long title truncates to 255 chars"""
        test_admin.pd_owner_id = 123
        test_company.pd_org_id = 456
        test_pipeline.pd_pipeline_id = 789
        test_stage.pd_stage_id = 101
        db.add(test_admin)
        db.add(test_company)
        db.add(test_pipeline)
        db.add(test_stage)
        db.commit()

        very_long_title = 'A' * 300  # 300 characters

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'added'},
            'data': {
                'id': 999,
                'title': very_long_title,
                'status': 'open',
                'owner_id': 123,
                'org_id': 456,
                'pipeline_id': 789,
                'stage_id': 101,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200

        # Verify deal name was truncated to 255 characters
        deal = db.exec(select(Deal).where(Deal.pd_deal_id == 999)).first()
        assert deal is not None
        assert len(deal.name) == 255
        assert deal.name == 'A' * 255
