"""
Tests for Pipedrive deletion webhooks and recreation prevention.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from app.main_app.models import Company
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP


@pytest.fixture
def sample_tc_webhook_data(test_admin, db):
    """Sample TC2 webhook data for testing"""

    def _make_webhook(tc2_cligency_id=9999, tc2_agency_id=8888):
        company = db.exec(select(Company).where(Company.tc2_cligency_id == tc2_cligency_id)).one_or_none()

        return {
            'events': [
                {
                    'action': 'UPDATE',
                    'subject': {
                        'model': 'Client',
                        'id': tc2_cligency_id,
                        'meta_agency': {
                            'id': tc2_agency_id,
                            'name': company.name if company else 'Test Company',
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
                        'paid_recipients': [
                            {'id': 789, 'first_name': 'John', 'last_name': 'Doe', 'email': 'john@example.com'},
                        ],
                        'extra_attrs': [],
                    },
                }
            ]
        }

    return _make_webhook


class TestPipedriveOrganizationDeletion:
    """Test Pipedrive organization deletion webhooks"""

    async def test_deletion_webhook_marks_company_deleted(self, client, db, test_company):
        """Test that deletion webhook clears pd_org_id and sets is_deleted=True"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'deleted'},
            'data': None,
            'previous': {
                'id': 999,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': test_company.name,
            },
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(test_company)
        assert test_company.pd_org_id is None
        assert test_company.is_deleted is True

    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    async def test_tc2_callback_after_deletion_does_not_recreate(
        self, mock_create_deal, mock_create_person, mock_create_org, client, db, test_company, sample_tc_webhook_data
    ):
        """Test that TC2 callback after deletion does not recreate org in Pipedrive"""
        test_company.tc2_cligency_id = 1001
        test_company.tc2_agency_id = 2001
        test_company.pd_org_id = None
        test_company.is_deleted = True
        db.add(test_company)
        db.commit()

        webhook_data = sample_tc_webhook_data(tc2_cligency_id=1001, tc2_agency_id=2001)
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        mock_create_org.assert_not_called()
        mock_create_person.assert_not_called()
        mock_create_deal.assert_not_called()

    @patch('app.pipedrive.tasks.api.update_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_tc2_callback_after_deletion_does_not_update(
        self, mock_get_org, mock_update_org, client, db, test_company, sample_tc_webhook_data
    ):
        """Test that TC2 callback after deletion does not update org fields in Pipedrive"""
        test_company.tc2_cligency_id = 1002
        test_company.tc2_agency_id = 2002
        test_company.pd_org_id = 999
        test_company.is_deleted = True
        db.add(test_company)
        db.commit()

        mock_get_org.return_value = {
            'data': {'id': 999, 'name': 'Old Name', COMPANY_PD_FIELD_MAP['paid_invoice_count']: 5}
        }

        webhook_data = sample_tc_webhook_data(tc2_cligency_id=1002, tc2_agency_id=2002)
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        mock_get_org.assert_not_called()
        mock_update_org.assert_not_called()

    async def test_deletion_then_update_webhook_stays_deleted(self, client, db, test_company, test_admin):
        """Test that update webhook after deletion doesn't clear is_deleted flag"""
        test_company.tc2_cligency_id = 1003
        test_company.tc2_agency_id = 2003
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        deletion_webhook = {
            'meta': {'entity': 'organization', 'action': 'deleted'},
            'data': None,
            'previous': {'id': 999, COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id, 'name': test_company.name},
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=deletion_webhook)
        assert r.status_code == 200

        db.refresh(test_company)
        assert test_company.is_deleted is True
        assert test_company.pd_org_id is None

        update_webhook = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 1000,
                COMPANY_PD_FIELD_MAP['hermes_id']: test_company.id,
                'name': 'Updated Name',
                'owner_id': test_admin.pd_owner_id,
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=update_webhook)
        assert r.status_code == 200

        db.refresh(test_company)
        assert test_company.name == 'Updated Name'
        assert test_company.pd_org_id == 1000
        assert test_company.is_deleted is False

    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    async def test_normal_flow_recreates_on_404(
        self, mock_create_org, client, db, test_company, sample_tc_webhook_data
    ):
        """Test normal flow: org with pd_org_id but NOT deleted recreates on 404"""
        test_company.tc2_cligency_id = 1004
        test_company.tc2_agency_id = 2004
        test_company.pd_org_id = 999
        test_company.is_deleted = False
        db.add(test_company)
        db.commit()

        mock_create_org.return_value = {'data': {'id': 1001}}

        webhook_data = sample_tc_webhook_data(tc2_cligency_id=1004, tc2_agency_id=2004)
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200

        mock_create_org.assert_called_once()

        db.refresh(test_company)
        assert test_company.pd_org_id == 1001
        assert test_company.is_deleted is False

    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    async def test_normal_flow_creates_new_org(self, mock_create_org, client, db, test_company, sample_tc_webhook_data):
        """Test normal flow: company without pd_org_id and NOT deleted creates new org"""
        test_company.tc2_cligency_id = 1005
        test_company.tc2_agency_id = 2005
        test_company.pd_org_id = None
        test_company.is_deleted = False
        db.add(test_company)
        db.commit()

        mock_create_org.return_value = {'data': {'id': 2000}}

        webhook_data = sample_tc_webhook_data(tc2_cligency_id=1005, tc2_agency_id=2005)
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200

        mock_create_org.assert_called_once()

        db.refresh(test_company)
        assert test_company.pd_org_id == 2000
        assert test_company.is_deleted is False


class TestPipedriveOrganizationMergeDeletion:
    """Test organization merge scenarios with deletion"""

    async def test_merge_marks_loser_deleted(self, client, db, test_admin):
        """Test that merged loser orgs are marked as deleted"""
        company1 = db.create(Company(name='Company 1', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=100))
        company2 = db.create(Company(name='Company 2', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=200))

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 100,
                COMPANY_PD_FIELD_MAP['hermes_id']: f'{company1.id}, {company2.id}',
                'name': 'Merged Company',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        db.refresh(company1)
        assert company1.name == 'Merged Company'
        assert company1.pd_org_id == 100
        assert company1.is_deleted is False

        db.refresh(company2)
        assert company2.pd_org_id is None
        assert company2.is_deleted is True

    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    async def test_merged_loser_not_recreated_on_tc2_callback(
        self, mock_create_org, client, db, test_admin, sample_tc_webhook_data
    ):
        """Test that merged loser companies are not recreated by TC2 callbacks"""
        company = db.create(
            Company(
                name='Loser Company',
                sales_person_id=test_admin.id,
                price_plan='payg',
                pd_org_id=None,
                is_deleted=True,
                tc2_cligency_id=1006,
                tc2_agency_id=2006,
            )
        )

        webhook_data = sample_tc_webhook_data(tc2_cligency_id=1006, tc2_agency_id=2006)
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200

        mock_create_org.assert_not_called()

        db.refresh(company)
        assert company.pd_org_id is None
        assert company.is_deleted is True

    async def test_merge_loser_only_processed_once(self, client, db, test_admin):
        """Test that merged losers are only marked deleted once, not on subsequent callbacks"""
        company1 = db.create(Company(name='Company 1', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=100))
        company2 = db.create(Company(name='Company 2', sales_person_id=test_admin.id, price_plan='payg', pd_org_id=200))

        webhook_data = {
            'meta': {'entity': 'organization', 'action': 'updated'},
            'data': {
                'id': 100,
                COMPANY_PD_FIELD_MAP['hermes_id']: f'{company1.id}, {company2.id}',
                'name': 'Merged Company',
            },
            'previous': None,
        }

        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)
        assert r.status_code == 200

        db.refresh(company2)
        assert company2.is_deleted is True
        assert company2.pd_org_id is None

        webhook_data['data']['name'] = 'Updated Merged Company'
        r = client.post(client.app.url_path_for('pipedrive-callback'), json=webhook_data)
        assert r.status_code == 200

        db.refresh(company1)
        assert company1.name == 'Updated Merged Company'

        db.refresh(company2)
        assert company2.is_deleted is True
        assert company2.pd_org_id is None


class TestNewCompanyCreationFlow:
    """Test that new companies are created with is_deleted=False and sync properly"""

    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    async def test_tc2_callback_creates_new_company_not_deleted(
        self, mock_create_deal, mock_create_person, mock_create_org, client, db, test_admin
    ):
        """Test TC2 callback creates new company with is_deleted=False"""
        webhook_data = {
            'events': [
                {
                    'action': 'CREATE',
                    'subject': {
                        'model': 'Client',
                        'id': 999,
                        'meta_agency': {
                            'id': 888,
                            'name': 'New Signup Company',
                            'status': 'trial',
                            'country': 'United Kingdom (GB)',
                            'website': 'https://newsignup.com',
                            'paid_invoice_count': 0,
                            'created': '2024-01-01T00:00:00Z',
                            'price_plan': 'monthly-payg',
                            'narc': False,
                        },
                        'user': {
                            'first_name': 'New',
                            'last_name': 'User',
                            'email': 'new@newsignup.com',
                            'phone': '+1234567890',
                        },
                        'status': 'trial',
                        'sales_person': {'id': test_admin.tc2_admin_id},
                        'paid_recipients': [
                            {'id': 777, 'first_name': 'New', 'last_name': 'User', 'email': 'new@newsignup.com'},
                        ],
                        'extra_attrs': [],
                    },
                }
            ]
        }

        mock_create_org.return_value = {'data': {'id': 3000}}
        mock_create_person.return_value = {'data': {'id': 4000}}
        mock_create_deal.return_value = {'data': {'id': 5000}}

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        from sqlmodel import select

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 999)).one()

        assert company.name == 'New Signup Company'
        assert company.is_deleted is False
        assert company.pd_org_id == 3000
        assert company.tc2_status == 'trial'

        mock_create_org.assert_called_once()
        mock_create_person.assert_called_once()

    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_tc2_callback_updates_existing_company_preserves_not_deleted(
        self,
        mock_get_org,
        mock_update_org,
        mock_create_org,
        client,
        db,
        test_admin,
        test_company,
        sample_tc_webhook_data,
    ):
        """Test TC2 callback updating existing company preserves is_deleted=False"""
        test_company.tc2_cligency_id = 1007
        test_company.tc2_agency_id = 2007
        test_company.pd_org_id = 1500
        test_company.is_deleted = False
        test_company.paid_invoice_count = 5
        db.add(test_company)
        db.commit()

        webhook_data = sample_tc_webhook_data(tc2_cligency_id=1007, tc2_agency_id=2007)
        webhook_data['events'][0]['subject']['meta_agency']['paid_invoice_count'] = 10

        mock_get_org.return_value = {
            'data': {
                'id': 1500,
                'name': test_company.name,
                COMPANY_PD_FIELD_MAP['paid_invoice_count']: 5,
            }
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200

        db.refresh(test_company)
        assert test_company.is_deleted is False
        assert test_company.paid_invoice_count == 10
        assert test_company.pd_org_id == 1500

        mock_get_org.assert_called_once()
        mock_update_org.assert_called_once()

    async def test_company_model_defaults_is_deleted_false(self, db, test_admin):
        """Test that Company model defaults is_deleted to False"""
        company = Company(
            name='Test Default Company',
            sales_person_id=test_admin.id,
            tc2_cligency_id=12345,
            tc2_agency_id=54321,
        )

        db.add(company)
        db.commit()
        db.refresh(company)

        assert company.is_deleted is False

    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    async def test_first_time_sync_creates_org_for_non_deleted_company(
        self, mock_create_org, client, db, test_admin, sample_tc_webhook_data
    ):
        """Test that first-time sync creates org in Pipedrive for non-deleted companies"""
        company = db.create(
            Company(
                name='Never Synced Company',
                sales_person_id=test_admin.id,
                tc2_cligency_id=1008,
                tc2_agency_id=2008,
                pd_org_id=None,
                is_deleted=False,
            )
        )

        mock_create_org.return_value = {'data': {'id': 6000}}

        webhook_data = sample_tc_webhook_data(tc2_cligency_id=1008, tc2_agency_id=2008)
        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200

        mock_create_org.assert_called_once()

        db.refresh(company)
        assert company.pd_org_id == 6000
        assert company.is_deleted is False
