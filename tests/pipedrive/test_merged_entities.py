"""
Tests for Pipedrive merged entities with comma-separated hermes_ids.
"""

import logging
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from app.main_app.models import Admin, Company, Contact, Deal, Pipeline
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP, CONTACT_PD_FIELD_MAP, DEAL_PD_FIELD_MAP
from app.pipedrive.tasks import sync_company_to_pipedrive


class TestPipedriveWebhookMergedEntities:
    """Test Pipedrive webhook handling for merged entities"""

    async def test_org_merged_with_comma_separated_hermes_ids(self, client, db, test_admin):
        """Test that a merged org updates its own company and leaves the other listed company for its own sync"""
        # Create two companies
        company1 = db.create(Company(name='Company 1', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=100))
        company2 = db.create(Company(name='Company 2', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=200))

        # Simulate Pipedrive merging org 200 into org 100
        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 100,  # Primary org after merge
                COMPANY_PD_FIELD_MAP['hermes_id']: f'{company1.id}, {company2.id}',  # Comma-separated
                'name': 'Merged Company',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Company 1 should be updated with merged data
        db.refresh(company1)
        assert company1.name == 'Merged Company'
        assert company1.pd_org_id == 100

        # Company 2 is left as it is: its next sync finds its org gone and marks it deleted
        db.refresh(company2)
        assert company2.pd_org_id == 200
        assert company2.is_deleted is False

    async def test_person_merged_with_comma_separated_hermes_ids(self, client, db, test_company):
        """Test that merged persons with comma-separated hermes_ids are handled"""
        # Create two contacts
        contact1 = db.create(
            Contact(
                first_name='John',
                last_name='Doe',
                email='john@example.com',
                pd_person_id=400,
                company_id=test_company.id,
            )
        )
        contact2 = db.create(
            Contact(
                first_name='Jane',
                last_name='Doe',
                email='jane@example.com',
                pd_person_id=500,
                company_id=test_company.id,
            )
        )

        # Simulate Pipedrive merging person 500 into person 400
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 400,  # Primary person after merge
                CONTACT_PD_FIELD_MAP['hermes_id']: f'{contact1.id}, {contact2.id}',  # Comma-separated
                'name': 'Jane Doe',
                'email': ['jane@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Contact 1 should be updated with merged data
        db.refresh(contact1)
        assert contact1.first_name == 'Jane'
        assert contact1.pd_person_id == 400

        # Contact 2 should be marked as deleted
        db.refresh(contact2)
        assert contact2.pd_person_id is None
        assert contact2.is_deleted is True

    async def test_deal_merged_with_comma_separated_hermes_ids(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test that merged deals with comma-separated hermes_ids are handled"""
        # Create two deals
        deal1 = db.create(
            Deal(
                name='Deal 1',
                pd_deal_id=800,
                admin_id=test_admin.id,
                company_id=test_company.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
            )
        )
        deal2 = db.create(
            Deal(
                name='Deal 2',
                pd_deal_id=900,
                admin_id=test_admin.id,
                company_id=test_company.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
            )
        )

        # Simulate Pipedrive merging deal 900 into deal 800
        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 800,  # Primary deal after merge
                DEAL_PD_FIELD_MAP['hermes_id']: f'{deal1.id}, {deal2.id}',  # Comma-separated
                'title': 'Merged Deal',
                'status': 'open',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Deal 1 should be updated with merged data
        db.refresh(deal1)
        assert deal1.name == 'Merged Deal'
        assert deal1.pd_deal_id == 800

        # Deal 2 should still exist
        db.refresh(deal2)
        assert deal2.id is not None


class TestPipedriveWebhookEdgeCases:
    """Test Pipedrive webhook edge cases for full coverage"""

    async def test_org_webhook_no_id_or_hermes_id(self, client, db):
        """Test organization webhook with no hermes_id or id"""
        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                # No id or hermes_id
                'name': 'Test Org',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_org_webhook_hermes_id_not_found(self, client, db):
        """Test organization webhook with hermes_id that doesn't exist"""
        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: 999,  # Non-existent company
                'name': 'Test Org',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_org_webhook_merged_hermes_ids_not_found(self, client, db):
        """Test organization webhook with merged hermes_ids that Hermes has none of"""
        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: '99998, 99999',
                'name': 'Test Org',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}
        assert db.exec(select(Company)).all() == []

    async def test_person_webhook_no_id_or_hermes_id(self, client, db):
        """Test person webhook with no hermes_id or id"""
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                # No id or hermes_id
                'name': 'Test Person',
                'email': ['test@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_person_webhook_hermes_id_not_found(self, client, db, caplog):
        """Test that a person with no contact linked and a hermes_id no contact has is skipped with a warning"""
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 999,
                CONTACT_PD_FIELD_MAP['hermes_id']: 999,  # Non-existent contact
                'name': 'Test Person',
                'email': ['test@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}
        assert db.exec(select(Contact)).all() == []
        assert [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR] == []
        assert [rec.getMessage() for rec in caplog.records if rec.levelno == logging.WARNING] == [
            'Not updating from Pipedrive Person 999: no Contact is linked to it or has hermes_id 999'
        ]

    async def test_deal_webhook_no_id_or_hermes_id(self, client, db):
        """Test deal webhook with no hermes_id or id"""
        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                # No id or hermes_id
                'title': 'Test Deal',
                'status': 'open',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_deal_webhook_hermes_id_not_found(self, client, db):
        """Test deal webhook with hermes_id that doesn't exist"""
        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 999,
                DEAL_PD_FIELD_MAP['hermes_id']: 999,  # Non-existent deal
                'title': 'Test Deal',
                'status': 'open',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_org_webhook_with_date_fields(self, client, db, test_company):
        """Test organization webhook updates date fields"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Test Company',
                COMPANY_PD_FIELD_MAP['pay0_dt']: '2024-01-01',
                COMPANY_PD_FIELD_MAP['pay1_dt']: '2024-02-01',
                COMPANY_PD_FIELD_MAP['pay3_dt']: '2024-03-01',
                COMPANY_PD_FIELD_MAP['gclid_expiry_dt']: '2024-04-01',
                COMPANY_PD_FIELD_MAP['email_confirmed_dt']: '2024-05-01',
                COMPANY_PD_FIELD_MAP['card_saved_dt']: '2024-06-01',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        assert test_company.pay3_dt is not None
        assert test_company.card_saved_dt is not None

    async def test_org_webhook_with_support_and_bdr_person_ids(self, client, db, test_company):
        """Test organization webhook updates support and BDR person IDs from PD owner IDs"""
        from app.main_app.models import Admin

        # Create admins with specific PD owner IDs
        bdr_admin = db.create(
            Admin(
                first_name='BDR',
                last_name='Admin',
                username='bdr@example.com',
                pd_owner_id=456,
                is_bdr_person=True,
            )
        )
        support_admin = db.create(
            Admin(
                first_name='Support',
                last_name='Admin',
                username='support@example.com',
                pd_owner_id=123,
                is_support_person=True,
            )
        )

        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Test Company',
                # Send PD owner IDs, which will be converted to Hermes admin IDs
                COMPANY_PD_FIELD_MAP['support_person_id']: support_admin.pd_owner_id,
                COMPANY_PD_FIELD_MAP['bdr_person_id']: bdr_admin.pd_owner_id,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        # Verify Hermes admin IDs are stored
        assert test_company.support_person_id == support_admin.id
        assert test_company.bdr_person_id == bdr_admin.id

    async def test_org_webhook_changes_sales_person(self, client, db, test_company):
        """Test updating organization sales person"""
        from app.main_app.models import Admin

        # Create second admin
        new_admin = db.create(
            Admin(
                first_name='New',
                last_name='Admin',
                username='newadmin@example.com',
                pd_owner_id=777,
                is_sales_person=True,
            )
        )

        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Test Company',
                'owner_id': new_admin.pd_owner_id,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        assert test_company.sales_person_id == new_admin.id

    async def test_person_deletion_clears_pd_person_id(self, client, db, test_contact):
        """Test person deletion webhook clears pd_person_id"""
        test_contact.pd_person_id = 888
        db.add(test_contact)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'deleted'},
            'data': None,
            'previous': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                'name': 'Test Person',
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_contact)
        assert test_contact.pd_person_id is None
        assert test_contact.is_deleted is True

    async def test_person_webhook_with_name_update(self, client, db, test_contact):
        """Test person webhook updates name fields"""
        test_contact.pd_person_id = 888
        db.add(test_contact)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                'name': 'UpdatedFirst UpdatedLast',
                'email': ['updated@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_contact)
        assert test_contact.first_name == 'UpdatedFirst'
        assert test_contact.last_name == 'UpdatedLast'

    async def test_person_webhook_with_email_and_phone(self, client, db, test_contact):
        """Test person webhook updates email and phone"""
        test_contact.pd_person_id = 888
        db.add(test_contact)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                'name': 'Test Person',
                'email': ['new@example.com', 'second@example.com'],
                'phone': '+1234567890',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_contact)
        assert test_contact.email == 'new@example.com'
        assert test_contact.phone == '+1234567890'

    async def test_person_webhook_with_v2_email_phone_format(self, client, db, test_contact):
        """Test person webhook handles v2 format with email/phone as arrays of objects"""
        test_contact.pd_person_id = 888
        db.add(test_contact)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                'name': 'Test Person',
                'email': [
                    {'value': 'primary@example.com', 'label': 'work', 'primary': True},
                    {'value': 'secondary@example.com', 'label': 'home', 'primary': False},
                ],
                'phone': [
                    {'value': '+9876543210', 'label': 'work', 'primary': True},
                    {'value': '+1111111111', 'label': 'mobile', 'primary': False},
                ],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_contact)
        assert test_contact.email == 'primary@example.com'
        assert test_contact.phone == '+9876543210'

    async def test_person_webhook_with_null_phone(self, client, db, test_contact):
        """Test person webhook handles null phone"""
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
                'phone': None,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_contact)
        assert test_contact.phone is None

    async def test_person_webhook_with_phone_as_string_list(self, client, db, test_contact):
        """Test person webhook handles phone as list of strings (edge case)"""
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
                'phone': ['+9999999999', '+8888888888'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_contact)
        assert test_contact.phone == '+9999999999'

    async def test_person_webhook_links_to_organization(self, client, db, test_contact, test_company):
        """Test person webhook links to organization via org_id"""
        test_contact.pd_person_id = 888
        test_company.pd_org_id = 555
        db.add(test_contact)
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: test_contact.id,
                'name': 'Test Person',
                'email': ['test@example.com'],
                'org_id': 555,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_contact)
        assert test_contact.company_id == test_company.id

    async def test_deal_deletion_marks_as_deleted(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test deal deletion webhook marks deal as deleted"""
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
            'meta': {'entity': 'deal', 'action': 'deleted'},
            'data': None,
            'previous': {
                'id': 888,
                DEAL_PD_FIELD_MAP['hermes_id']: deal.id,
                'title': 'Test Deal',
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(deal)
        assert deal.status == Deal.STATUS_DELETED
        assert deal.pd_deal_id is None

    async def test_deal_webhook_updates_relationships(
        self, client, db, test_admin, test_company, test_contact, test_pipeline, test_stage
    ):
        """Test deal webhook updates all relationship fields"""
        # Create another admin to link to
        admin2 = db.create(Admin(first_name='Admin', last_name='Two', username='admin2@example.com', pd_owner_id=999))

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

        # Update pd_org_id, pd_person_id, pd_owner_id on related entities
        test_company.pd_org_id = 111
        test_contact.pd_person_id = 222
        db.add(test_company)
        db.add(test_contact)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 888,
                DEAL_PD_FIELD_MAP['hermes_id']: deal.id,
                'title': 'Updated Deal',
                'status': 'won',
                'user_id': 999,  # Links to admin2
                'org_id': 111,  # Links to test_company
                'person_id': 222,  # Links to test_contact
                'pipeline_id': test_pipeline.pd_pipeline_id,
                'stage_id': test_stage.pd_stage_id,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(deal)
        assert deal.admin_id == admin2.id
        assert deal.company_id == test_company.id
        assert deal.contact_id == test_contact.id

    async def test_pipeline_webhook_inactive_ignored(self, client, db):
        """Test inactive pipeline webhook is ignored"""
        webhook_data = {
            'meta': {'entity': 'pipeline', 'action': 'updated'},
            'data': {
                'id': 999,
                'name': 'Inactive Pipeline',
                'active': False,  # Inactive
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # Verify pipeline was not created
        pipeline = db.exec(select(Pipeline).where(Pipeline.pd_pipeline_id == 999)).first()
        assert pipeline is None

    async def test_pipeline_webhook_updates_existing(self, client, db, test_pipeline):
        """Test pipeline webhook updates existing pipeline"""
        test_pipeline.pd_pipeline_id = 999
        test_pipeline.name = 'Old Name'
        db.add(test_pipeline)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'pipeline', 'action': 'updated'},
            'data': {
                'id': 999,
                'name': 'Updated Pipeline Name',
                'active': True,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_pipeline)
        assert test_pipeline.name == 'Updated Pipeline Name'

    async def test_stage_webhook_updates_existing(self, client, db, test_stage):
        """Test stage webhook updates existing stage"""
        test_stage.pd_stage_id = 999
        test_stage.name = 'Old Name'
        db.add(test_stage)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'stage', 'action': 'updated'},
            'data': {
                'id': 999,
                'name': 'Updated Stage Name',
                'pipeline_id': 1,
                'active_flag': True,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_stage)
        assert test_stage.name == 'Updated Stage Name'

    async def test_stage_deletion_ignored(self, client, db):
        """Test stage deletion webhook is ignored (returns None)"""
        webhook_data = {
            'meta': {'entity': 'stage', 'action': 'deleted'},
            'data': None,  # Deleted
            'previous': {
                'id': 999,
                'name': 'Deleted Stage',
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

    async def test_org_webhook_with_tc2_cligency_url_in_field_map(self, client, db, test_company):
        """Test that tc2_cligency_url in field map doesn't cause setter error"""
        test_company.pd_org_id = 999
        test_company.tc2_cligency_id = 12345
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Test Company',
                COMPANY_PD_FIELD_MAP['tc2_cligency_url']: 'https://secure.tutorcruncher.com/clients/12345/',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        # tc2_cligency_url is a computed property, so it shouldn't be set
        # It should still be computed from tc2_cligency_id
        assert test_company.tc2_cligency_url == 'https://secure.tutorcruncher.com/clients/12345/'

    async def test_deal_webhook_with_tc2_cligency_url_in_field_map(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test that tc2_cligency_url in deal field map doesn't cause setter error"""
        test_company.tc2_cligency_id = 12345
        db.add(test_company)
        db.commit()

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
                'title': 'Updated Deal',
                'status': 'open',
                DEAL_PD_FIELD_MAP['tc2_cligency_url']: 'https://secure.tutorcruncher.com/clients/12345/',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(deal)
        # tc2_cligency_url should be set on Deal (it's a regular field, not a property)
        assert deal.tc2_cligency_url == 'https://secure.tutorcruncher.com/clients/12345/'

    async def test_deal_created_with_null_tc2_cligency_url(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test that deals can be created with NULL tc2_cligency_url and it gets populated by webhook"""
        # Create a deal with NULL tc2_cligency_url (like migration does)
        deal = Deal(
            name='Test Deal',
            pd_deal_id=999,
            admin_id=test_admin.id,
            company_id=test_company.id,
            pipeline_id=test_pipeline.id,
            stage_id=test_stage.id,
            tc2_cligency_url=None,  # NULL initially
        )
        db.add(deal)
        db.commit()

        assert deal.tc2_cligency_url is None

        # Now Pipedrive sends webhook to update it
        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'updated'},
            'data': {
                'id': 999,
                DEAL_PD_FIELD_MAP['hermes_id']: deal.id,
                'title': 'Test Deal',
                'status': 'open',
                DEAL_PD_FIELD_MAP['tc2_cligency_url']: 'https://secure.tutorcruncher.com/clients/99999/',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(deal)
        # tc2_cligency_url should now be populated by Pipedrive
        assert deal.tc2_cligency_url == 'https://secure.tutorcruncher.com/clients/99999/'


class TestPipedrivePersonMergeDeletion:
    """Test person merge scenarios with deletion"""

    async def test_person_merge_marks_loser_deleted(self, client, db, test_company):
        """Test that merged loser contacts are marked as deleted"""
        contact1 = db.create(
            Contact(
                first_name='John',
                last_name='Winner',
                email='john@example.com',
                pd_person_id=400,
                company_id=test_company.id,
            )
        )
        contact2 = db.create(
            Contact(
                first_name='John',
                last_name='Loser',
                email='john.loser@example.com',
                pd_person_id=500,
                company_id=test_company.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: f'{contact1.id}, {contact2.id}',
                'name': 'John Winner',
                'email': ['john@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(contact1)
        assert contact1.first_name == 'John'
        assert contact1.pd_person_id == 400
        assert contact1.is_deleted is False

        db.refresh(contact2)
        assert contact2.pd_person_id is None
        assert contact2.is_deleted is True

    async def test_person_merge_loser_only_processed_once(self, client, db, test_company):
        """Test that merged losers are only marked deleted once, not on subsequent callbacks"""
        contact1 = db.create(
            Contact(
                first_name='John',
                last_name='Winner',
                email='john@example.com',
                pd_person_id=400,
                company_id=test_company.id,
            )
        )
        contact2 = db.create(
            Contact(
                first_name='John',
                last_name='Loser',
                email='john.loser@example.com',
                pd_person_id=500,
                company_id=test_company.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: f'{contact1.id}, {contact2.id}',
                'name': 'John Winner',
                'email': ['john@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)
        assert r.status_code == 200

        db.refresh(contact2)
        assert contact2.is_deleted is True
        assert contact2.pd_person_id is None

        # Send the same merge webhook again (e.g. another update to the winner)
        webhook_data['data']['name'] = 'John Updated'
        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)
        assert r.status_code == 200

        db.refresh(contact1)
        assert contact1.first_name == 'John'

        db.refresh(contact2)
        assert contact2.is_deleted is True
        assert contact2.pd_person_id is None

    async def test_person_merge_with_multiple_losers(self, client, db, test_company):
        """Test that merging three contacts marks both losers as deleted"""
        contact1 = db.create(
            Contact(
                first_name='John',
                last_name='Winner',
                email='john@example.com',
                pd_person_id=400,
                company_id=test_company.id,
            )
        )
        contact2 = db.create(
            Contact(
                first_name='John',
                last_name='Loser1',
                email='john.loser1@example.com',
                pd_person_id=500,
                company_id=test_company.id,
            )
        )
        contact3 = db.create(
            Contact(
                first_name='John',
                last_name='Loser2',
                email='john.loser2@example.com',
                pd_person_id=600,
                company_id=test_company.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: f'{contact1.id}, {contact2.id}, {contact3.id}',
                'name': 'John Winner',
                'email': ['john@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(contact1)
        assert contact1.pd_person_id == 400
        assert contact1.is_deleted is False

        db.refresh(contact2)
        assert contact2.pd_person_id is None
        assert contact2.is_deleted is True

        db.refresh(contact3)
        assert contact3.pd_person_id is None
        assert contact3.is_deleted is True

    async def test_person_merge_with_missing_winner_keeps_existing_contact(self, client, db, test_company):
        """Test that a merged hermes_id led by an id Hermes doesn't have updates the contact linked to the person"""
        contact1 = db.create(
            Contact(
                first_name='John',
                last_name='Winner',
                email='john@example.com',
                pd_person_id=400,
                company_id=test_company.id,
            )
        )
        contact2 = db.create(
            Contact(
                first_name='John',
                last_name='Loser',
                email='john.loser@example.com',
                pd_person_id=500,
                company_id=test_company.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'change'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: f'99999, {contact1.id}, {contact2.id}',
                'name': 'Jane Winner',
                'email': ['john@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(contact1)
        assert contact1.first_name == 'Jane'
        assert contact1.pd_person_id == 400
        assert contact1.is_deleted is False

        db.refresh(contact2)
        assert contact2.pd_person_id is None
        assert contact2.is_deleted is True

    async def test_person_merge_updates_org_link(self, client, db, test_admin):
        """Test merge where winner gets new org_id, verify company_id is updated"""
        company1 = db.create(Company(name='Company 1', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=100))
        company2 = db.create(Company(name='Company 2', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=200))

        contact1 = db.create(
            Contact(
                first_name='John',
                last_name='Winner',
                email='john@example.com',
                pd_person_id=400,
                company_id=company1.id,
            )
        )
        contact2 = db.create(
            Contact(
                first_name='John',
                last_name='Loser',
                email='john.loser@example.com',
                pd_person_id=500,
                company_id=company2.id,
            )
        )

        # Merge webhook where winner is now associated with company2's org
        webhook_data = {
            'meta': {'entity': 'person', 'action': 'updated'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: f'{contact1.id}, {contact2.id}',
                'name': 'John Winner',
                'email': ['john@example.com'],
                'org_id': 200,  # Now linked to company2's org
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(contact1)
        assert contact1.company_id == company2.id
        assert contact1.is_deleted is False

        db.refresh(contact2)
        assert contact2.pd_person_id is None
        assert contact2.is_deleted is True

    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_person_merge_leaves_deleted_contact_deleted(
        self,
        mock_get_org,
        mock_update_org,
        mock_get_person,
        mock_update_person,
        mock_create_person,
        client,
        db,
        test_admin,
    ):
        """
        Test that a merged hermes_id listing a deleted contact before the linked one updates the linked one, and the
        deleted one, which has no Pipedrive id, stays deleted so the company sync doesn't create a duplicate person
        """
        company = db.create(Company(name='Company', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=100))
        deleted = db.create(
            Contact(
                first_name='John',
                last_name='Deleted',
                email='john@example.com',
                pd_person_id=None,
                is_deleted=True,
                company_id=company.id,
            )
        )
        linked = db.create(
            Contact(
                first_name='John',
                last_name='Linked',
                email='john@example.com',
                pd_person_id=400,
                company_id=company.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'change'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: f'99999, {deleted.id}, {linked.id}',
                'name': 'Jane Merged',
                'email': ['john@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(linked)
        assert (linked.first_name, linked.last_name, linked.pd_person_id, linked.is_deleted) == (
            'Jane',
            'Merged',
            400,
            False,
        )
        db.refresh(deleted)
        assert (deleted.first_name, deleted.last_name, deleted.pd_person_id, deleted.is_deleted) == (
            'John',
            'Deleted',
            None,
            True,
        )

        mock_get_org.return_value = {'data': {'id': 100, 'name': 'Company'}}
        mock_get_person.return_value = {'data': {'id': 400}}

        await sync_company_to_pipedrive(company.id)

        mock_get_person.assert_called_once_with(400)
        mock_create_person.assert_not_called()

    async def test_person_merge_with_only_deleted_contacts_updates_nothing(self, client, db, test_company):
        """Test that a merged hermes_id listing only deleted contacts leaves them deleted and unchanged"""
        deleted = db.create(
            Contact(
                first_name='John',
                last_name='Deleted',
                email='john@example.com',
                pd_person_id=None,
                is_deleted=True,
                company_id=test_company.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'change'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: f'99999, {deleted.id}',
                'name': 'Jane Merged',
                'email': ['john@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(deleted)
        assert (deleted.first_name, deleted.last_name, deleted.pd_person_id, deleted.is_deleted) == (
            'John',
            'Deleted',
            None,
            True,
        )
        assert db.exec(select(Contact)).all() == [deleted]

    async def test_person_merge_updates_linked_contact_not_listed(self, client, db, test_company):
        """Test that a merged person updates the contact linked to it even when its hermes_id lists only others"""
        listed = [
            db.create(
                Contact(
                    first_name='John',
                    last_name=f'Listed {i}',
                    email=f'john{i}@example.com',
                    pd_person_id=None,
                    is_deleted=True,
                    company_id=test_company.id,
                )
            )
            for i in range(2)
        ]
        linked = db.create(
            Contact(
                first_name='John',
                last_name='Linked',
                email='john@example.com',
                pd_person_id=400,
                company_id=test_company.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'change'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: f'{listed[0].id}, {listed[1].id}',
                'name': 'Jane Merged',
                'email': ['john@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(linked)
        assert (linked.first_name, linked.last_name, linked.pd_person_id, linked.is_deleted) == (
            'Jane',
            'Merged',
            400,
            False,
        )
        for contact in listed:
            db.refresh(contact)
            assert (contact.first_name, contact.pd_person_id, contact.is_deleted) == ('John', None, True)

    async def test_person_update_leaves_deleted_contact_deleted(self, client, db, test_company):
        """Test that a person update for a deleted contact, which has no Pipedrive id, doesn't bring it back"""
        contact = db.create(
            Contact(
                first_name='John',
                last_name='Deleted',
                email='john@example.com',
                pd_person_id=None,
                is_deleted=True,
                company_id=test_company.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'change'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: contact.id,
                'name': 'Jane Restored',
                'email': ['john@example.com'],
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(contact)
        assert (contact.pd_person_id, contact.is_deleted) == (None, True)

    async def test_person_deletion_marks_as_deleted(self, client, db, test_company):
        """Test that deletion webhook sets is_deleted=True on Contact"""
        contact = db.create(
            Contact(
                first_name='John',
                last_name='Doe',
                email='john@example.com',
                pd_person_id=888,
                company_id=test_company.id,
            )
        )

        webhook_data = {
            'meta': {'entity': 'person', 'action': 'deleted'},
            'data': None,
            'previous': {
                'id': 888,
                CONTACT_PD_FIELD_MAP['hermes_id']: contact.id,
                'name': 'John Doe',
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(contact)
        assert contact.pd_person_id is None
        assert contact.is_deleted is True

    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_organisation', new_callable=AsyncMock)
    async def test_tc2_callback_does_not_sync_deleted_contact(
        self, mock_update_org, mock_get_org, mock_create_person, client, db, test_admin
    ):
        """Test that TC2 callback does not recreate a merged-deleted contact in Pipedrive"""
        company = db.create(
            Company(
                name='Test Company',
                sales_person_id=test_admin.id,
                price_plan='payg',
                pd_org_id=100,
                tc2_cligency_id=9999,
                tc2_agency_id=8888,
            )
        )
        # Winner contact - still active
        db.create(
            Contact(
                first_name='John',
                last_name='Winner',
                email='john@example.com',
                pd_person_id=400,
                company_id=company.id,
            )
        )
        # Loser contact - marked as deleted from a merge
        loser = db.create(
            Contact(
                first_name='John',
                last_name='Loser',
                email='john.loser@example.com',
                pd_person_id=None,
                is_deleted=True,
                company_id=company.id,
            )
        )

        mock_get_org.return_value = {
            'data': {'id': 100, 'name': 'Test Company', COMPANY_PD_FIELD_MAP['paid_invoice_count']: '0'}
        }

        # TC2 sends a webhook for this company
        webhook_data = {
            'events': [
                {
                    'action': 'UPDATE',
                    'verb': 'EDITED_A_CLIENT',
                    'subject': {
                        'model': 'Client',
                        'id': 9999,
                        'meta_agency': {
                            'id': 8888,
                            'name': 'Test Company',
                            'status': 'active',
                            'country': 'United Kingdom (GB)',
                            'website': 'https://example.com',
                            'paid_invoice_count': 0,
                            'created': '2024-01-01T00:00:00Z',
                            'price_plan': 'monthly-payg',
                            'narc': False,
                            'pay0_dt': None,
                            'pay1_dt': None,
                            'pay3_dt': None,
                            'card_saved_dt': None,
                            'email_confirmed_dt': None,
                            'gclid': None,
                            'gclid_expiry_dt': None,
                        },
                        'user': {
                            'first_name': 'John',
                            'last_name': 'Doe',
                            'email': 'john@example.com',
                            'phone': '+1234567890',
                        },
                        'status': 'active',
                        'sales_person': {'id': test_admin.tc2_admin_id},
                        'paid_recipients': [],
                        'extra_attrs': [],
                    },
                }
            ]
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        # create_person should not have been called for the deleted loser contact
        mock_create_person.assert_not_called()

        # Loser should still be deleted
        db.refresh(loser)
        assert loser.is_deleted is True
        assert loser.pd_person_id is None


def _org_custom_fields(**values) -> dict:
    """Org custom fields in the nested form Pipedrive v2 webhooks send them"""
    return {COMPANY_PD_FIELD_MAP[f]: {'type': 'varchar', 'value': v} for f, v in values.items()}


JOINED_ORG_VALUES = {
    'price_plan': 'startup, payg',
    'tc2_status': 'pending_email_conf, trial, terminated',
    'website': 'https://first.example.com, https://second.example.com',
    'utm_source': 'direct, none',
    'utm_campaign': 'global tutorcruncher brand, none',
    'estimated_income': '£0 - £50,000, just starting out',
    'signup_questionnaire': '{"how-did-you-hear-about-us": ["Other"]}, {"how-did-you-hear-about-us": ["Google"]}',
    'paid_invoice_count': '3, 15',
    'signup_email': 'first@example.com, second@example.com',
    'signup_phone': '+447700900001, +447700900002',
    'gclid': 'first-gclid, second-gclid',
}


def _company_values(company: Company) -> tuple:
    """The company fields an org webhook can change"""
    return (
        company.name,
        company.price_plan,
        company.tc2_status,
        company.website,
        company.utm_source,
        company.utm_campaign,
        company.estimated_income,
        company.signup_questionnaire,
        company.paid_invoice_count,
        company.signup_email,
        company.signup_phone,
        company.gclid,
    )


class TestPipedriveWebhookMergeJoinedValues:
    """Pipedrive joins merged orgs' custom field values with ', ', and Hermes must not copy them onto the company"""

    def _create_company(self, db, test_admin, name: str, pd_org_id: int) -> Company:
        return db.create(
            Company(
                name=name,
                sales_person_id=test_admin.id,
                pd_org_id=pd_org_id,
                price_plan='startup',
                tc2_status='trial',
                website='https://first.example.com',
                utm_source='google',
                utm_campaign='global tutorcruncher brand',
                estimated_income='£0 - £50,000',
                signup_questionnaire='{"how-did-you-hear-about-us": ["Other"]}',
                paid_invoice_count=3,
                signup_email='first@example.com',
                signup_phone='+447700900001',
                gclid='first-gclid',
            )
        )

    async def test_merged_org_keeps_company_values(self, client, db, test_admin):
        """Test that a merged org's joined values leave the winner company's values as they were"""
        company1 = self._create_company(db, test_admin, 'Company 1', 100)
        company2 = self._create_company(db, test_admin, 'Company 2', 200)

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 100,
                'name': 'Merged Company',
                'custom_fields': _org_custom_fields(hermes_id=f'{company1.id}, {company2.id}', **JOINED_ORG_VALUES),
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(company1)
        assert _company_values(company1) == (
            'Merged Company',
            'startup',
            'trial',
            'https://first.example.com',
            'google',
            'global tutorcruncher brand',
            '£0 - £50,000',
            '{"how-did-you-hear-about-us": ["Other"]}',
            3,
            'first@example.com',
            '+447700900001',
            'first-gclid',
        )

    async def test_joined_values_with_single_hermes_id_keep_company_values(self, client, db, test_admin):
        """Test that joined values are ignored after Hermes has already set the org's hermes_id back to one id"""
        company = self._create_company(db, test_admin, 'Company 1', 100)

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 100,
                'name': 'Renamed Company',
                'custom_fields': _org_custom_fields(hermes_id=str(company.id), **JOINED_ORG_VALUES),
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(company)
        assert _company_values(company) == (
            'Renamed Company',
            'startup',
            'trial',
            'https://first.example.com',
            'google',
            'global tutorcruncher brand',
            '£0 - £50,000',
            '{"how-did-you-hear-about-us": ["Other"]}',
            3,
            'first@example.com',
            '+447700900001',
            'first-gclid',
        )

    async def test_single_values_with_commas_are_copied(self, client, db, test_admin):
        """Test that one org's own values that contain commas are still copied onto the company"""
        company = self._create_company(db, test_admin, 'Company 1', 100)

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 100,
                'name': 'Company 1',
                'custom_fields': _org_custom_fields(
                    hermes_id=str(company.id),
                    price_plan='enterprise',
                    estimated_income='£50,000 - £150,000',
                    signup_questionnaire='{"how-did-you-hear-about-us": ["Other"], "lessons": ["Entirely remote"]}',
                    paid_invoice_count='15',
                ),
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(company)
        assert _company_values(company) == (
            'Company 1',
            'enterprise',
            'trial',
            'https://first.example.com',
            'google',
            'global tutorcruncher brand',
            '£50,000 - £150,000',
            '{"how-did-you-hear-about-us": ["Other"], "lessons": ["Entirely remote"]}',
            15,
            'first@example.com',
            '+447700900001',
            'first-gclid',
        )

    async def test_joined_paid_invoice_count_does_not_drop_webhook(self, client, db, test_admin):
        """Test that a joined paid_invoice_count no longer stops the rest of the org update"""
        company = self._create_company(db, test_admin, 'Company 1', 100)

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 100,
                'name': 'Renamed Company',
                'custom_fields': _org_custom_fields(hermes_id=str(company.id), paid_invoice_count='50, 35, 41'),
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(company)
        assert (company.name, company.paid_invoice_count) == ('Renamed Company', 3)

    async def test_joined_paid_invoice_count_in_previous_does_not_drop_webhook(self, client, db, test_admin):
        """Test that overwriting a joined paid_invoice_count in Pipedrive updates the company"""
        company = self._create_company(db, test_admin, 'Company 1', 100)

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {
                'id': 100,
                'name': 'Company 1',
                'custom_fields': _org_custom_fields(hermes_id=str(company.id), paid_invoice_count='7'),
            },
            'previous': {'custom_fields': _org_custom_fields(paid_invoice_count='6, 13')},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(company)
        assert company.paid_invoice_count == 7

    async def test_new_org_with_joined_values_gets_defaults(self, client, db, test_admin):
        """Test that a new org's joined values are left out, so the new company gets the default values"""
        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'create'},
            'data': {
                'id': 777,
                'name': 'New Company',
                'owner_id': test_admin.pd_owner_id,
                'custom_fields': _org_custom_fields(
                    price_plan='startup, payg',
                    tc2_status='pending_email_conf, trial, terminated',
                    paid_invoice_count='4, 63',
                    website='https://first.example.com, https://second.example.com',
                ),
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        company = db.exec(select(Company).where(Company.pd_org_id == 777)).one()
        assert (company.name, company.price_plan, company.tc2_status, company.paid_invoice_count, company.website) == (
            'New Company',
            'payg',
            'pending_email_conf',
            0,
            None,
        )


def _deal_custom_fields(**values) -> dict:
    """Deal custom fields in the nested form Pipedrive v2 webhooks send them"""
    return {DEAL_PD_FIELD_MAP[f]: {'type': 'varchar', 'value': v} for f, v in values.items()}


JOINED_DEAL_VALUES = {
    'price_plan': 'startup, payg',
    'tc2_status': 'pending_email_conf, trial',
    'website': 'https://first.example.com, https://second.example.com',
    'utm_source': 'direct, none',
    'utm_campaign': 'global tutorcruncher brand, none',
    'estimated_income': '£0 - £50,000, just starting out',
    'signup_questionnaire': "{'how-did-you-hear-about-us': 'Other'}, {'how-did-you-hear-about-us': 'Google'}",
    'tc2_cligency_url': 'https://secure.tutorcruncher.com/clients/1/, https://secure.tutorcruncher.com/clients/2/',
    'paid_invoice_count': '3, 15',
}


def _deal_values(deal: Deal) -> tuple:
    """The deal fields a deal webhook can change"""
    return (
        deal.name,
        deal.status,
        deal.price_plan,
        deal.tc2_status,
        deal.website,
        deal.utm_source,
        deal.utm_campaign,
        deal.estimated_income,
        deal.signup_questionnaire,
        deal.tc2_cligency_url,
        deal.paid_invoice_count,
    )


class TestPipedriveWebhookMergeJoinedDealValues:
    """Pipedrive joins merged deals' custom field values with ', ', and Hermes must not copy them onto the deal"""

    def _create_deal(self, db, test_admin, test_company, test_pipeline, test_stage, name: str, pd_deal_id: int) -> Deal:
        """A deal with no joined values and no utm values"""
        return db.create(
            Deal(
                name=name,
                pd_deal_id=pd_deal_id,
                admin_id=test_admin.id,
                company_id=test_company.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
                price_plan='payg',
                tc2_status='trial',
                website='https://first.example.com',
                estimated_income='£0 - £50,000',
                signup_questionnaire="{'how-did-you-hear-about-us': 'Other'}",
                tc2_cligency_url='https://secure.tutorcruncher.com/clients/1/',
                paid_invoice_count=3,
            )
        )

    async def test_merged_deal_keeps_deal_values(self, client, db, test_admin, test_company, test_pipeline, test_stage):
        """Test that a merged deal's joined values leave the deal's values as they were, and the rest still updates"""
        deal1 = self._create_deal(db, test_admin, test_company, test_pipeline, test_stage, 'Deal 1', 800)
        deal2 = self._create_deal(db, test_admin, test_company, test_pipeline, test_stage, 'Deal 2', 900)

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'change'},
            'data': {
                'id': 800,
                'title': 'Merged Deal',
                'status': 'won',
                'custom_fields': _deal_custom_fields(hermes_id=f'{deal1.id}, {deal2.id}', **JOINED_DEAL_VALUES),
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(deal1)
        assert _deal_values(deal1) == (
            'Merged Deal',
            Deal.STATUS_WON,
            'payg',
            'trial',
            'https://first.example.com',
            None,
            None,
            '£0 - £50,000',
            "{'how-did-you-hear-about-us': 'Other'}",
            'https://secure.tutorcruncher.com/clients/1/',
            3,
        )

    async def test_joined_paid_invoice_count_does_not_drop_deal_webhook(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test that a joined paid_invoice_count, now or before the change, doesn't stop the rest of the deal update"""
        deal = self._create_deal(db, test_admin, test_company, test_pipeline, test_stage, 'Deal 1', 800)

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'change'},
            'data': {
                'id': 800,
                'title': 'Deal 1',
                'status': 'won',
                'custom_fields': _deal_custom_fields(hermes_id=str(deal.id), paid_invoice_count='50, 35'),
            },
            'previous': {'status': 'open', 'custom_fields': _deal_custom_fields(paid_invoice_count='6, 13')},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(deal)
        assert (deal.status, deal.paid_invoice_count) == (Deal.STATUS_WON, 3)

    async def test_single_deal_values_are_copied(self, client, db, test_admin, test_company, test_pipeline, test_stage):
        """Test that one deal's own values are copied, including commas and a questionnaire stored as a Python dict"""
        deal = self._create_deal(db, test_admin, test_company, test_pipeline, test_stage, 'Deal 1', 800)

        webhook_data = {
            'meta': {'entity': 'deal', 'action': 'change'},
            'data': {
                'id': 800,
                'title': 'Deal 1',
                'status': 'open',
                'custom_fields': _deal_custom_fields(
                    hermes_id=str(deal.id),
                    price_plan='enterprise',
                    utm_source='google',
                    estimated_income='£50,000 - £150,000',
                    signup_questionnaire="{'how-did-you-hear-about-us': 'Other', 'lessons': 'Entirely remote'}",
                    tc2_cligency_url='https://secure.tutorcruncher.com/clients/2/',
                    paid_invoice_count='15',
                ),
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(deal)
        assert _deal_values(deal) == (
            'Deal 1',
            Deal.STATUS_OPEN,
            'enterprise',
            'trial',
            'https://first.example.com',
            'google',
            None,
            '£50,000 - £150,000',
            "{'how-did-you-hear-about-us': 'Other', 'lessons': 'Entirely remote'}",
            'https://secure.tutorcruncher.com/clients/2/',
            15,
        )


class TestPipedriveWebhookPipedriveLink:
    """
    A merged org's hermes_id can list ids that are no Hermes company's or another live company's, so org and deal
    webhooks use the record Hermes links to the Pipedrive id, and never delete the other listed records
    """

    def _org_webhook(self, name: str, hermes_id: str) -> dict:
        return {
            'meta': {'entity': 'organization', 'action': 'change'},
            'data': {'id': 100, 'name': name, 'custom_fields': _org_custom_fields(hermes_id=hermes_id)},
            'previous': None,
        }

    def _deal_webhook(self, title: str, hermes_id: str) -> dict:
        return {
            'meta': {'entity': 'deal', 'action': 'change'},
            'data': {
                'id': 800,
                'title': title,
                'status': 'open',
                'custom_fields': _deal_custom_fields(hermes_id=hermes_id),
            },
            'previous': None,
        }

    async def test_merged_org_updates_linked_company(self, client, db, test_admin):
        """Test that the company linked to the org is updated, not the companies its hermes_id lists"""
        kwargs = {'sales_person_id': test_admin.id, 'price_plan': 'payg'}
        linked = db.create(Company(name='Prominent Education', pd_org_id=100, **kwargs))
        other_org = db.create(Company(name='LoopLearners', pd_org_id=300, **kwargs))
        unlinked = db.create(Company(name='Unlinked', **kwargs))

        webhook_data = self._org_webhook('Prominent Education Ltd', f'99999, {other_org.id}, {unlinked.id}')
        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        for company in (linked, other_org, unlinked):
            db.refresh(company)
        assert [(c.name, c.pd_org_id, c.is_deleted) for c in (linked, other_org, unlinked)] == [
            ('Prominent Education Ltd', 100, False),
            ('LoopLearners', 300, False),
            ('Unlinked', None, False),
        ]

    async def test_org_with_no_linked_company_skips_company_of_another_org(self, client, db, test_admin):
        """Test that with no company linked to the org, a listed company linked to another org is left alone"""
        other_org = db.create(Company(name='Edulinx', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=300))

        r = client.post(
            client.app.url_path_for('pipedrive-callback'),
            json=self._org_webhook('WeAre Education Ltd', f'{other_org.id}, 99999'),
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(other_org)
        assert (other_org.name, other_org.pd_org_id, other_org.is_deleted) == ('Edulinx', 300, False)
        assert db.exec(select(Company)).all() == [other_org]

    async def test_merged_org_brings_back_deleted_company(self, client, db, test_admin):
        """
        Test that a company the org lists first, deleted when its own org was merged away, is linked to the surviving
        org and brought back
        """
        kwargs = {'sales_person_id': test_admin.id, 'price_plan': 'payg'}
        deleted = db.create(Company(name='Price Education Limited', is_deleted=True, **kwargs))
        other_org = db.create(Company(name='Other', pd_org_id=300, **kwargs))

        r = client.post(
            client.app.url_path_for('pipedrive-callback'),
            json=self._org_webhook('Price Education Ltd', f'{deleted.id}, {other_org.id}'),
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        for company in (deleted, other_org):
            db.refresh(company)
        assert [(c.name, c.pd_org_id, c.is_deleted) for c in (deleted, other_org)] == [
            ('Price Education Ltd', 100, False),
            ('Other', 300, False),
        ]

    @pytest.mark.parametrize('is_deleted', [True, False])
    async def test_org_skips_narc_company(self, is_deleted, client, db, test_admin):
        """Test that a NARC company is never linked to the org, as its next TC2 update would delete the org"""
        company = db.create(
            Company(
                name='Narc Tuition', sales_person_id=test_admin.id, price_plan='payg', narc=True, is_deleted=is_deleted
            )
        )

        r = client.post(
            client.app.url_path_for('pipedrive-callback'), json=self._org_webhook('Narc Tuition Ltd', str(company.id))
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(company)
        assert (company.name, company.pd_org_id, company.is_deleted) == ('Narc Tuition', None, is_deleted)

    async def test_org_links_unlinked_company_by_hermes_id(self, client, db, test_admin):
        """Test that with no company linked to the org, its hermes_id company with no pd_org_id is linked to it"""
        company = db.create(Company(name='Believe Tuition', sales_person_id=test_admin.id, price_plan='payg'))

        r = client.post(
            client.app.url_path_for('pipedrive-callback'),
            json=self._org_webhook('Believe Tuition Ltd', str(company.id)),
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(company)
        assert (company.name, company.pd_org_id, company.is_deleted) == ('Believe Tuition Ltd', 100, False)

    async def test_merged_org_links_listed_company_with_tc2_client(self, client, db, test_admin):
        """
        Test that with no company linked to the org, the listed company with a TC2 client is linked and brought back
        rather than the first listed one, so the org gets the TC2 client's updates
        """
        kwargs = {'sales_person_id': test_admin.id, 'price_plan': 'payg', 'is_deleted': True}
        pd_only = db.create(Company(name='Tuition Extra Group', **kwargs))
        tc2_client = db.create(Company(name='Tuition Extra', tc2_cligency_id=5238897, **kwargs))

        r = client.post(
            client.app.url_path_for('pipedrive-callback'),
            json=self._org_webhook('Tuition Extra Group Ltd', f'{pd_only.id}, {tc2_client.id}'),
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        for company in (pd_only, tc2_client):
            db.refresh(company)
        assert [(c.name, c.pd_org_id, c.is_deleted) for c in (pd_only, tc2_client)] == [
            ('Tuition Extra Group', None, True),
            ('Tuition Extra Group Ltd', 100, False),
        ]

    async def test_merged_org_waits_for_tc2_client_linked_to_old_org(self, client, db, test_admin):
        """
        Test that while the listed company with a TC2 client is still linked to its merged-away org, no company is linked
        to the org, so the first listed company can't take the link from it
        """
        kwargs = {'sales_person_id': test_admin.id, 'price_plan': 'payg'}
        pd_only = db.create(Company(name='TutorGNV', **kwargs))
        tc2_client = db.create(Company(name='TutorGNV, LLC', tc2_cligency_id=5350249, pd_org_id=300, **kwargs))

        r = client.post(
            client.app.url_path_for('pipedrive-callback'),
            json=self._org_webhook('TutorGNV Ltd', f'{pd_only.id}, {tc2_client.id}'),
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        for company in (pd_only, tc2_client):
            db.refresh(company)
        assert [(c.name, c.pd_org_id, c.is_deleted) for c in (pd_only, tc2_client)] == [
            ('TutorGNV', None, False),
            ('TutorGNV, LLC', 300, False),
        ]

    @pytest.mark.parametrize('is_deleted, unsynced_status', [(True, Deal.STATUS_DELETED), (False, Deal.STATUS_OPEN)])
    async def test_brought_back_company_deletes_deals_never_in_pipedrive(
        self, is_deleted, unsynced_status, client, db, test_admin, test_pipeline, test_stage
    ):
        """
        Test that linking a deleted company marks deleted its open deals that never reached Pipedrive, so its next sync
        doesn't create them, while a live company's deals and the company's other deals are left as they are
        """
        company = db.create(
            Company(name='On Point Tutoring', sales_person_id=test_admin.id, price_plan='payg', is_deleted=is_deleted)
        )
        kwargs = {
            'company_id': company.id,
            'admin_id': test_admin.id,
            'pipeline_id': test_pipeline.id,
            'stage_id': test_stage.id,
        }
        unsynced = db.create(Deal(name='Unsynced', **kwargs))
        synced = db.create(Deal(name='Synced', pd_deal_id=800, **kwargs))
        lost = db.create(Deal(name='Lost', status=Deal.STATUS_LOST, **kwargs))

        r = client.post(
            client.app.url_path_for('pipedrive-callback'), json=self._org_webhook('On Point Tutoring', str(company.id))
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        for obj in (company, unsynced, synced, lost):
            db.refresh(obj)
        assert (company.pd_org_id, company.is_deleted) == (100, False)
        assert [(d.name, d.status) for d in (unsynced, synced, lost)] == [
            ('Unsynced', unsynced_status),
            ('Synced', Deal.STATUS_OPEN),
            ('Lost', Deal.STATUS_LOST),
        ]

    async def test_deal_on_merged_org_is_added_once_org_links_company(
        self, client, db, test_admin, test_pipeline, test_stage, caplog
    ):
        """
        Test that a deal on a merged org is skipped while no company is linked to the org, and added on its next change
        once the org's webhook has linked its company
        """
        company = db.create(
            Company(name='Tuition Extra Group', sales_person_id=test_admin.id, price_plan='payg', is_deleted=True)
        )
        deal_webhook = {
            'meta': {'entity': 'deal', 'action': 'change'},
            'data': {
                'id': 800,
                'title': 'Tuition Extra Group deal',
                'status': 'open',
                'owner_id': test_admin.pd_owner_id,
                'org_id': 100,
                'pipeline_id': test_pipeline.pd_pipeline_id,
                'stage_id': test_stage.pd_stage_id,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook)
        assert r.status_code == 200
        assert db.exec(select(Deal)).all() == []

        client.post(
            client.app.url_path_for('pipedrive-callback'),
            json=self._org_webhook('Tuition Extra Group', f'{company.id}, 99999'),
        )
        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deal_webhook)

        assert r.status_code == 200
        deal = db.exec(select(Deal)).one()
        assert (deal.pd_deal_id, deal.company_id) == (800, company.id)
        assert [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR] == []

    async def test_deal_webhook_skips_deleted_deal(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """
        Test that a deleted deal stays deleted: brought back without pd_deal_id, its next sync would create a
        duplicate deal
        """
        deal = db.create(
            Deal(
                name='Deal 1',
                status=Deal.STATUS_DELETED,
                admin_id=test_admin.id,
                company_id=test_company.id,
                pipeline_id=test_pipeline.id,
                stage_id=test_stage.id,
            )
        )

        r = client.post(
            client.app.url_path_for('pipedrive-callback'), json=self._deal_webhook('Deal 1 reopened', str(deal.id))
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(deal)
        assert (deal.name, deal.status, deal.pd_deal_id) == ('Deal 1', Deal.STATUS_DELETED, None)

    async def test_deal_webhook_updates_linked_deal(
        self, client, db, test_admin, test_company, test_pipeline, test_stage
    ):
        """Test that the deal linked to the Pipedrive deal is updated, not the deal its hermes_id names"""
        kwargs = {
            'admin_id': test_admin.id,
            'company_id': test_company.id,
            'pipeline_id': test_pipeline.id,
            'stage_id': test_stage.id,
        }
        linked = db.create(Deal(name='Deal 1', pd_deal_id=800, **kwargs))
        other = db.create(Deal(name='Deal 2', pd_deal_id=900, **kwargs))

        r = client.post(
            client.app.url_path_for('pipedrive-callback'), json=self._deal_webhook('Deal 1 renamed', str(other.id))
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        for deal in (linked, other):
            db.refresh(deal)
        assert [(d.name, d.pd_deal_id) for d in (linked, other)] == [('Deal 1 renamed', 800), ('Deal 2', 900)]


class TestPipedrivePersonPipedriveLink:
    """A person's hermes_id can name no contact or another one, so person webhooks use the contact linked to them"""

    def _person_webhook(self, name: str, hermes_id: int | str) -> dict:
        return {
            'meta': {'entity': 'person', 'action': 'change'},
            'data': {
                'id': 400,
                CONTACT_PD_FIELD_MAP['hermes_id']: hermes_id,
                'name': name,
                'email': ['john@example.com'],
            },
            'previous': None,
        }

    async def test_person_with_unknown_hermes_id_updates_linked_contact(self, client, db, test_company, caplog):
        """Test that the contact linked to the person is updated when its hermes_id names no contact"""
        contact = db.create(
            Contact(
                first_name='John',
                last_name='Linked',
                email='john@example.com',
                pd_person_id=400,
                company_id=test_company.id,
            )
        )

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=self._person_webhook('Jane Linked', 99999))

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(contact)
        assert (contact.first_name, contact.last_name, contact.pd_person_id, contact.is_deleted) == (
            'Jane',
            'Linked',
            400,
            False,
        )
        assert [rec.getMessage() for rec in caplog.records if rec.levelno >= logging.ERROR] == []

    async def test_person_updates_linked_contact_not_its_hermes_id_contact(self, client, db, test_company):
        """Test that the contact linked to the person is updated, not the other contact its hermes_id names"""
        kwargs = {'email': 'john@example.com', 'company_id': test_company.id}
        linked = db.create(Contact(first_name='John', last_name='Linked', pd_person_id=400, **kwargs))
        other = db.create(Contact(first_name='John', last_name='Other', pd_person_id=500, **kwargs))

        r = client.post(
            client.app.url_path_for('pipedrive-callback'), json=self._person_webhook('Jane Linked', str(other.id))
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        for contact in (linked, other):
            db.refresh(contact)
        assert [(c.first_name, c.last_name, c.pd_person_id, c.is_deleted) for c in (linked, other)] == [
            ('Jane', 'Linked', 400, False),
            ('John', 'Other', 500, False),
        ]

    async def test_merged_person_updates_linked_contact_and_deletes_other_listed(self, client, db, test_company):
        """
        Test that a merged person updates the contact linked to it, even when its hermes_id lists another live contact
        first, and the other listed contact is marked deleted
        """
        kwargs = {'email': 'john@example.com', 'company_id': test_company.id}
        other = db.create(Contact(first_name='John', last_name='Other', pd_person_id=500, **kwargs))
        linked = db.create(Contact(first_name='John', last_name='Linked', pd_person_id=400, **kwargs))

        r = client.post(
            client.app.url_path_for('pipedrive-callback'),
            json=self._person_webhook('Jane Merged', f'{other.id}, {linked.id}'),
        )

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        for contact in (linked, other):
            db.refresh(contact)
        assert [(c.first_name, c.last_name, c.pd_person_id, c.is_deleted) for c in (linked, other)] == [
            ('Jane', 'Merged', 400, False),
            ('John', 'Other', None, True),
        ]
