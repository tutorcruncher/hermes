"""
Tests for Pipedrive merged entities with comma-separated hermes_ids.
"""

from sqlmodel import select

from app.main_app.models import Admin, Company, Contact, Deal, Pipeline
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP, CONTACT_PD_FIELD_MAP, DEAL_PD_FIELD_MAP


class TestPipedriveWebhookMergedEntities:
    """Test Pipedrive webhook handling for merged entities"""

    async def test_org_merged_with_comma_separated_hermes_ids(self, client, db, test_admin):
        """Test that merged organizations with comma-separated hermes_ids are handled"""
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

        # Company 2 should still exist (no deletion)
        db.refresh(company2)
        assert company2.id is not None

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

        # Contact 2 should still exist
        db.refresh(contact2)
        assert contact2.id is not None

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

    async def test_person_webhook_hermes_id_not_found(self, client, db):
        """Test person webhook with hermes_id that doesn't exist"""
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
        """Test organization webhook updates support and BDR person IDs"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Test Company',
                COMPANY_PD_FIELD_MAP['support_person_id']: 123,
                COMPANY_PD_FIELD_MAP['bdr_person_id']: 456,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        assert test_company.support_person_id == 123
        assert test_company.bdr_person_id == 456

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
