"""
Tests for Pipedrive sync tasks.
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.main_app.models import Company, Deal
from app.pipedrive.field_mappings import DEAL_PD_FIELD_MAP
from app.pipedrive.tasks import (
    _deal_to_pd_data,
    _meeting_to_activity_data,
    partial_sync_deal_from_company,
    sync_company_to_pipedrive,
    sync_deal,
    sync_meeting_to_pipedrive,
    sync_organization,
    sync_person,
)


class SessionMock:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *args):
        return None


class MockGCalResource:
    def __init__(self, admin_username=None):
        self.admin_username = admin_username

    def freebusy(self):
        return self

    def query(self, body):
        self.body = body
        return self

    def execute(self):
        if self.admin_username:
            return {'calendars': {self.admin_username: {'busy': []}}}
        return {'calendars': {}}

    def events(self):
        return self

    def insert(self, *args, **kwargs):
        return self


class TestSyncCompanyToPipedrive:
    """Test sync_company_to_pipedrive task"""

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.sync_organization', new_callable=AsyncMock)
    async def test_sync_company_not_found(self, mock_sync_org, mock_get_session, db):
        """Test syncing non-existent company logs warning"""
        mock_get_session.return_value = db

        await sync_company_to_pipedrive(999999)

        # Should log warning, not call sync functions
        mock_sync_org.assert_not_called()


class TestSyncOrganization:
    """Test sync_organization function"""

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    async def test_sync_organization_does_not_hold_session_during_api_call(
        self, mock_create, mock_get_session, db, test_company
    ):
        """Test that sync_organization closes DB session before making API calls"""

        session_open = []

        class SessionTracker:
            def __enter__(self):
                session_open.append(True)
                return db

            def __exit__(self, *args):
                session_open.pop()
                return False

        def check_session_during_api_call(*args, **kwargs):
            assert len(session_open) == 0, 'API call was made while database session was still open'
            return {'data': {'id': 888}}

        mock_get_session.return_value = SessionTracker()
        mock_create.side_effect = check_session_during_api_call

        await sync_organization(test_company.id)

        assert len(session_open) == 0

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    async def test_sync_organization_raises_on_create_failure(self, mock_create, mock_get_session, db, test_company):
        """Test that sync_organization raises exception when organization creation fails"""
        mock_get_session.return_value = SessionMock(db)
        mock_create.side_effect = Exception('Pipedrive API error: validation failed')

        with pytest.raises(Exception, match='Pipedrive API error: validation failed'):
            await sync_organization(test_company.id)

        mock_create.assert_called_once()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_sync_organization_raises_on_update_failure_non_404(
        self, mock_get, mock_get_session, db, test_company
    ):
        """Test that sync_organization raises exception when update fails with non-404 error"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = Exception('Pipedrive API error: 400 Bad Request')

        with pytest.raises(Exception, match='400 Bad Request'):
            await sync_organization(test_company.id)

        mock_get.assert_called_once()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_sync_organization_recreates_on_404(self, mock_get, mock_create, mock_get_session, db, test_company):
        """Test that sync_organization recreates organization when getting 404 on update"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = Exception('404 Not Found')
        mock_create.return_value = {'data': {'id': 1000}}

        await sync_organization(test_company.id)

        mock_get.assert_called_once()
        mock_create.assert_called_once()

        db.refresh(test_company)
        assert test_company.pd_org_id == 1000

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    async def test_sync_organization_success_create(self, mock_create, mock_get_session, db, test_company):
        """Test successful organization creation"""

        mock_get_session.return_value = SessionMock(db)
        mock_create.return_value = {'data': {'id': 888}}

        await sync_organization(test_company.id)

        mock_create.assert_called_once()
        db.refresh(test_company)
        assert test_company.pd_org_id == 888

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_sync_organization_success_update(self, mock_get, mock_update, mock_get_session, db, test_company):
        """Test successful organization update"""
        test_company.pd_org_id = 999
        test_company.name = 'Old Name'
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.return_value = {'data': {'id': 999, 'name': 'Old Name'}}
        mock_update.return_value = {'data': {'id': 999, 'name': 'New Name'}}

        test_company.name = 'New Name'
        db.add(test_company)
        db.commit()

        await sync_organization(test_company.id)

        mock_get.assert_called_once_with(999)
        mock_update.assert_called_once()


class TestSyncPerson:
    """Test sync_person function"""

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    async def test_sync_person_update_404_then_create(self, mock_get, mock_create, mock_get_session, db, test_contact):
        """Test person update getting 404 then creates new"""
        test_contact.pd_person_id = 999
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = Exception('404 Not Found')
        mock_create.return_value = {'data': {'id': 1111}}

        await sync_person(test_contact.id)

        db.refresh(test_contact)
        assert test_contact.pd_person_id == 1111

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    async def test_sync_person_update_non_404_error(self, mock_get, mock_get_session, db, test_contact):
        """Test person update with non-404 error logs but doesn't clear ID"""
        test_contact.pd_person_id = 999
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = Exception('500 Server Error')

        await sync_person(test_contact.id)

        db.refresh(test_contact)
        assert test_contact.pd_person_id == 999

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    async def test_sync_person_create_failure(self, mock_create, mock_get_session, db, test_contact):
        """Test person creation failure logs error"""
        test_contact.pd_person_id = None
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_create.side_effect = Exception('API Error')

        await sync_person(test_contact.id)

        db.refresh(test_contact)
        assert test_contact.pd_person_id is None

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    async def test_sync_person_create_success(self, mock_create, mock_get_session, db, test_contact):
        """Test creating new person"""
        test_contact.pd_person_id = None
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_create.return_value = {'data': {'id': 2222}}

        await sync_person(test_contact.id)

        db.refresh(test_contact)
        assert test_contact.pd_person_id == 2222


class TestSyncDeal:
    """Test sync_deal function"""

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_deal', new_callable=AsyncMock)
    async def test_sync_deal_update_404_keeps_pd_id(self, mock_get, mock_create, mock_get_session, db, test_deal):
        """Test deal update getting 404 preserves existing pd_deal_id"""
        test_deal.pd_deal_id = 999
        db.add(test_deal)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = Exception('404 Not Found')

        await sync_deal(test_deal.id)

        db.refresh(test_deal)
        assert test_deal.pd_deal_id == 999
        mock_create.assert_not_called()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_deal', new_callable=AsyncMock)
    async def test_sync_deal_does_not_reopen_closed_deal(self, mock_get, mock_update, mock_get_session, db, test_deal):
        """Test that sync_deal skips updates if remote deal is no longer open"""
        test_deal.pd_deal_id = 999
        db.add(test_deal)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.return_value = {'data': {'status': 'won'}}

        await sync_deal(test_deal.id)

        mock_update.assert_not_called()
        db.refresh(test_deal)
        assert test_deal.pd_deal_id == 999

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.get_deal', new_callable=AsyncMock)
    async def test_sync_deal_update_non_404_error(self, mock_get, mock_get_session, db, test_deal):
        """Test deal update with non-404 error logs but doesn't clear ID"""
        test_deal.pd_deal_id = 999
        db.add(test_deal)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = Exception('500 Server Error')

        await sync_deal(test_deal.id)

        db.refresh(test_deal)
        assert test_deal.pd_deal_id == 999

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    async def test_sync_deal_create_failure(self, mock_create, mock_get_session, db, test_deal):
        """Test deal creation failure logs error"""
        test_deal.pd_deal_id = None
        db.add(test_deal)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_create.side_effect = Exception('API Error')

        await sync_deal(test_deal.id)

        db.refresh(test_deal)
        assert test_deal.pd_deal_id is None

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    async def test_sync_deal_create_success(self, mock_create, mock_get_session, db, test_deal):
        """Test creating new deal"""
        test_deal.pd_deal_id = None
        db.add(test_deal)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_create.return_value = {'data': {'id': 4444}}

        await sync_deal(test_deal.id)

        db.refresh(test_deal)
        assert test_deal.pd_deal_id == 4444

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_callbooker_deleted_deal_not_synced_to_pipedrive(
        self,
        mock_gcal,
        mock_bg_task,
        mock_create_person,
        mock_create_org,
        mock_update_deal,
        mock_create_deal,
        client,
        db,
        test_admin,
        test_pipeline,
        test_stage,
        test_config,
    ):
        from pytz import utc

        mock_gcal.return_value = MockGCalResource(test_admin.username)
        mock_create_org.return_value = {'data': {'id': 7777}}
        mock_create_person.return_value = {'data': {'id': 8888}}
        mock_create_deal.return_value = {'data': {'id': 9999}}

        # Book a sales call which creates a deal
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': datetime(2026, 7, 3, 9, tzinfo=utc).isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)
        assert r.status_code == 200

        # Get the created company and deal
        company = db.exec(select(Company).where(Company.name == 'Test Company')).first()
        assert company is not None

        deal = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        assert deal is not None
        assert deal.pd_deal_id is None
        assert deal.status == Deal.STATUS_OPEN

        # Manually mark the deal as deleted (no pd_deal_id)
        deal.status = Deal.STATUS_DELETED
        db.add(deal)
        db.commit()
        db.refresh(deal)

        # Reset mocks
        mock_create_deal.reset_mock()

        # Now trigger company sync which should filter out deleted deals
        await sync_company_to_pipedrive(company.id)

        # Verify create_deal was NOT called for deleted deal
        mock_create_deal.assert_not_called()

    @patch('app.pipedrive.tasks.sync_organization', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.sync_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_deal', new_callable=AsyncMock)
    async def test_tc2_closed_deal_synced_to_pipedrive(
        self, mock_get_deal, mock_update_deal, mock_sync_person, mock_sync_org, db, test_deal
    ):
        # Set up a deal that was closed by TC2 (NARC or terminated)
        test_deal.pd_deal_id = 5555
        test_deal.status = Deal.STATUS_LOST
        db.add(test_deal)
        db.commit()

        # Mock Pipedrive response - deal is still open in Pipedrive
        mock_get_deal.return_value = {'data': {'id': 5555, 'status': 'open'}}

        # Trigger company sync
        await sync_company_to_pipedrive(test_deal.company_id)

        # Verify deal was synced and updated in Pipedrive
        mock_get_deal.assert_called_once_with(5555)
        mock_update_deal.assert_called_once()
        # Verify status was updated to lost
        call_args = mock_update_deal.call_args
        assert call_args[0][1]['status'] == Deal.STATUS_LOST

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_callbooker_open_deal_synced_to_pipedrive(
        self,
        mock_gcal,
        mock_bg_task,
        mock_create_person,
        mock_create_org,
        mock_create_deal,
        client,
        db,
        test_admin,
        test_pipeline,
        test_stage,
        test_config,
    ):
        from pytz import utc

        mock_gcal.return_value = MockGCalResource(test_admin.username)
        mock_create_org.return_value = {'data': {'id': 7777}}
        mock_create_person.return_value = {'data': {'id': 8888}}
        mock_create_deal.return_value = {'data': {'id': 9999}}

        # Book a sales call which creates a deal
        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': datetime(2026, 7, 3, 9, tzinfo=utc).isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)
        assert r.status_code == 200

        # Get the created company and deal
        company = db.exec(select(Company).where(Company.name == 'Test Company')).first()
        assert company is not None

        deal = db.exec(select(Deal).where(Deal.company_id == company.id)).first()
        assert deal is not None
        assert deal.pd_deal_id is None
        assert deal.status == Deal.STATUS_OPEN

        # Trigger sync manually
        await sync_deal(deal.id)

        # Verify create_deal WAS called for open deal
        mock_create_deal.assert_called_once()

        # Verify deal has pd_deal_id set
        db.refresh(deal)
        assert deal.pd_deal_id == 9999


class TestSyncDealPartialSync:
    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_deal', new_callable=AsyncMock)
    async def test_partial_sync_updates_deal_without_get(
        self, mock_get_deal, mock_update_deal, mock_get_session, db, test_deal, test_company
    ):
        test_deal.pd_deal_id = 5555
        test_company.paid_invoice_count = 10
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_update_deal.return_value = {'data': {'id': 5555}}

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        mock_get_deal.assert_not_called()
        mock_update_deal.assert_called_once()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    async def test_partial_sync_sends_only_syncable_fields(
        self, mock_update_deal, mock_get_session, db, test_deal, test_company
    ):
        test_deal.pd_deal_id = 5555
        test_company.paid_invoice_count = 42
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_update_deal.return_value = {'data': {'id': 5555}}

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        mock_update_deal.assert_called_once()
        call_args = mock_update_deal.call_args

        assert call_args[0][0] == 5555
        payload = call_args[0][1]
        assert 'custom_fields' in payload
        assert payload['custom_fields'] == {DEAL_PD_FIELD_MAP['paid_invoice_count']: '42'}

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    async def test_partial_sync_uses_company_value_not_deal_value(
        self, mock_update_deal, mock_get_session, db, test_deal, test_company
    ):
        test_deal.pd_deal_id = 5555
        test_deal.paid_invoice_count = 5  # Stale value on deal
        test_company.paid_invoice_count = 99  # Fresh value on company
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_update_deal.return_value = {'data': {'id': 5555}}

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        call_args = mock_update_deal.call_args
        payload = call_args[0][1]
        assert payload['custom_fields'][DEAL_PD_FIELD_MAP['paid_invoice_count']] == '99'

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    async def test_partial_sync_no_pd_deal_id_returns_early(
        self, mock_update_deal, mock_get_session, db, test_deal, test_company
    ):
        test_deal.pd_deal_id = None
        test_company.paid_invoice_count = 10
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        mock_update_deal.assert_not_called()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    async def test_partial_sync_no_paid_invoice_count_no_api_call(
        self, mock_update_deal, mock_get_session, db, test_deal, test_company
    ):
        test_deal.pd_deal_id = 5555
        test_company.paid_invoice_count = None
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        mock_update_deal.assert_not_called()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    async def test_partial_sync_paid_invoice_count_zero_is_sent(
        self, mock_update_deal, mock_get_session, db, test_deal, test_company
    ):
        test_deal.pd_deal_id = 5555
        test_company.paid_invoice_count = 0
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_update_deal.return_value = {'data': {'id': 5555}}

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        mock_update_deal.assert_called_once()
        call_args = mock_update_deal.call_args
        payload = call_args[0][1]
        assert payload['custom_fields'][DEAL_PD_FIELD_MAP['paid_invoice_count']] == '0'

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_deal', new_callable=AsyncMock)
    async def test_partial_sync_company_not_found_does_not_full_sync(
        self, mock_get_deal, mock_update_deal, mock_get_session, db, test_deal
    ):
        test_deal.pd_deal_id = 5555
        test_deal.company_id = 999999  # Non-existent company
        db.add(test_deal)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get_deal.return_value = {'data': {'id': 5555, 'status': 'open'}}

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        # we don't want to do a full sync
        mock_get_deal.assert_not_called()

    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    async def test_partial_sync_deal_from_company_directly(self, mock_update_deal, db, test_deal, test_company):
        test_deal.pd_deal_id = 7777
        test_company.paid_invoice_count = 25
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_update_deal.return_value = {'data': {'id': 7777}}

        await partial_sync_deal_from_company(test_company, test_deal)

        mock_update_deal.assert_called_once_with(
            7777, {'custom_fields': {DEAL_PD_FIELD_MAP['paid_invoice_count']: '25'}}
        )

    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    async def test_partial_sync_deal_from_company_no_pd_deal_id(self, mock_update_deal, db, test_deal, test_company):
        test_deal.pd_deal_id = None
        test_company.paid_invoice_count = 25
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        await partial_sync_deal_from_company(test_company, test_deal)

        mock_update_deal.assert_not_called()
        assert db.exec(select(func.count()).select_from(Deal)).one() == 1

    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    async def test_partial_sync_deal_from_company_no_syncable_values(
        self, mock_update_deal, db, test_deal, test_company
    ):
        test_deal.pd_deal_id = 7777
        test_company.paid_invoice_count = None
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        await partial_sync_deal_from_company(test_company, test_deal)

        mock_update_deal.assert_not_called()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    async def test_partial_sync_does_not_create_deal(
        self, mock_create_deal, mock_update_deal, mock_get_session, db, test_deal, test_company
    ):
        test_deal.pd_deal_id = None
        test_company.paid_invoice_count = 10
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        mock_create_deal.assert_not_called()
        mock_update_deal.assert_not_called()

        db.get


class TestDealToPDData:
    """Test _deal_to_pd_data conversion function"""

    def test_deal_to_pd_data_uses_owner_id_not_user_id(self, db, test_deal):
        """Test that deal data uses 'owner_id' field, not 'user_id' for Pipedrive v2 API"""
        # Ensure admin has pd_owner_id set
        test_deal.admin.pd_owner_id = 12345
        db.add(test_deal.admin)
        db.commit()

        result = _deal_to_pd_data(test_deal, db)

        # Should use 'owner_id', not 'user_id'
        assert 'owner_id' in result
        assert result['owner_id'] == 12345
        assert 'user_id' not in result

    def test_deal_to_pd_data_includes_all_required_fields(self, db, test_deal):
        """Test that deal data includes all required fields for Pipedrive"""
        result = _deal_to_pd_data(test_deal, db)

        # Basic fields
        assert 'title' in result
        assert result['title'] == test_deal.name
        assert 'status' in result
        assert result['status'] == test_deal.status

        # Foreign key references
        assert 'org_id' in result
        assert 'person_id' in result
        assert 'pipeline_id' in result
        assert 'stage_id' in result
        assert 'owner_id' in result

        # Custom fields
        assert 'custom_fields' in result

    def test_deal_to_pd_data_handles_missing_contact(self, db, test_deal):
        """Test that deal data handles deals without a contact"""
        test_deal.contact_id = None
        db.add(test_deal)
        db.commit()

        result = _deal_to_pd_data(test_deal, db)

        assert 'person_id' in result
        assert result['person_id'] is None

    def test_deal_to_pd_data_maps_custom_fields(self, db, test_deal):
        """Test that deal custom fields are correctly mapped to Pipedrive field IDs"""
        # Set some custom fields on the deal
        test_deal.website = 'https://example.com'
        test_deal.utm_source = 'google'
        test_deal.utm_campaign = 'summer2024'
        db.add(test_deal)

        # paid_invoice_count comes from Company, not Deal
        company = db.get(Company, test_deal.company_id)
        company.paid_invoice_count = 5
        db.add(company)
        db.commit()

        result = _deal_to_pd_data(test_deal, db)

        assert 'custom_fields' in result
        custom_fields = result['custom_fields']

        # Check non-None fields are included
        assert DEAL_PD_FIELD_MAP['website'] in custom_fields
        assert custom_fields[DEAL_PD_FIELD_MAP['website']] == 'https://example.com'
        assert DEAL_PD_FIELD_MAP['utm_source'] in custom_fields
        assert custom_fields[DEAL_PD_FIELD_MAP['utm_source']] == 'google'
        assert DEAL_PD_FIELD_MAP['utm_campaign'] in custom_fields
        assert custom_fields[DEAL_PD_FIELD_MAP['utm_campaign']] == 'summer2024'
        assert DEAL_PD_FIELD_MAP['paid_invoice_count'] in custom_fields
        assert custom_fields[DEAL_PD_FIELD_MAP['paid_invoice_count']] == '5'

    def test_deal_to_pd_data_excludes_none_and_empty_custom_fields(self, db, test_deal):
        """Test that None and empty string custom fields are not included in Pipedrive data"""
        # Set some fields to None and empty string
        test_deal.website = None
        test_deal.utm_source = ''
        test_deal.utm_campaign = 'valid_value'
        db.add(test_deal)
        db.commit()

        result = _deal_to_pd_data(test_deal, db)

        assert 'custom_fields' in result
        custom_fields = result['custom_fields']

        # None and empty string fields should not be in custom_fields
        assert DEAL_PD_FIELD_MAP['website'] not in custom_fields
        assert DEAL_PD_FIELD_MAP['utm_source'] not in custom_fields

        # Valid value should be included
        assert DEAL_PD_FIELD_MAP['utm_campaign'] in custom_fields


class TestSyncMeetingToPipedrive:
    """Test sync_meeting_to_pipedrive task"""

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_activity', new_callable=AsyncMock)
    async def test_sync_meeting_not_found(self, mock_create, mock_get_session, db):
        """Test syncing non-existent meeting logs warning"""
        mock_get_session.return_value = db

        await sync_meeting_to_pipedrive(999999)

        # Should log warning, not call API
        mock_create.assert_not_called()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_activity', new_callable=AsyncMock)
    async def test_sync_meeting_success(self, mock_create, mock_get_session, db, test_meeting):
        """Test syncing meeting creates activity"""
        mock_get_session.return_value = db
        mock_create.return_value = {'data': {'id': 7777}}

        await sync_meeting_to_pipedrive(test_meeting.id)

        mock_create.assert_called_once()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_activity', new_callable=AsyncMock)
    async def test_sync_meeting_with_error(self, mock_create, mock_get_session, db, test_meeting):
        """Test syncing meeting with API error logs error"""
        mock_get_session.return_value = db
        mock_create.side_effect = Exception('API Error')

        # Should log error but not raise
        await sync_meeting_to_pipedrive(test_meeting.id)

        mock_create.assert_called_once()

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_sales_call_endpoint_syncs_meeting(
        self, mock_gcal, mock_add_task, client, db, test_admin, test_pipeline, test_stage, test_config
    ):
        """Test that sales call endpoint queues meeting sync"""

        from pytz import utc

        mock_gcal.return_value = MockGCalResource(test_admin.username)

        meeting_data = {
            'admin_id': test_admin.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'company_name': 'Test Company',
            'country': 'GB',
            'estimated_income': 1000,
            'currency': 'GBP',
            'price_plan': 'payg',
            'meeting_dt': datetime(2026, 7, 3, 9, tzinfo=utc).isoformat(),
        }

        r = client.post(client.app.url_path_for('book-sales-call'), json=meeting_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        call_args = [call.args[0].__name__ for call in mock_add_task.call_args_list]
        assert 'sync_company_to_pipedrive' in call_args
        assert 'sync_meeting_to_pipedrive' in call_args

    @patch('fastapi.BackgroundTasks.add_task')
    @patch('app.callbooker.google.AdminGoogleCalendar._create_resource')
    async def test_support_call_endpoint_does_not_sync_meeting(
        self, mock_gcal, mock_add_task, client, db, test_admin, test_company
    ):
        """Test that support call endpoint does NOT queue meeting sync"""

        from pytz import utc

        mock_gcal.return_value = MockGCalResource(test_admin.username)

        meeting_data = {
            'admin_id': test_admin.id,
            'company_id': test_company.id,
            'name': 'Test Person',
            'email': 'test@example.com',
            'meeting_dt': datetime(2026, 7, 3, 9, tzinfo=utc).isoformat(),
        }

        r = client.post(client.app.url_path_for('book-support-call'), json=meeting_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        call_args = [call.args[0].__name__ for call in mock_add_task.call_args_list]
        assert 'sync_company_to_pipedrive' not in call_args
        assert 'sync_meeting_to_pipedrive' not in call_args


class TestDataConversionHelpers:
    """Test data conversion helper functions"""

    def test_deal_to_pd_data(self, db, test_deal):
        """Test converting Deal to Pipedrive data"""
        result = _deal_to_pd_data(test_deal, db)

        assert 'title' in result
        assert 'org_id' in result
        assert 'owner_id' in result
        assert 'pipeline_id' in result
        assert 'stage_id' in result
        assert 'status' in result
        assert 'custom_fields' in result

    def test_meeting_to_activity_data(self, db, test_meeting, test_contact, test_company):
        """Test converting Meeting to Pipedrive activity data"""
        # Set Pipedrive IDs to test participants and org_id
        test_contact.pd_person_id = 123
        test_company.pd_org_id = 456
        db.add(test_contact)
        db.add(test_company)
        db.commit()

        result = _meeting_to_activity_data(test_meeting, db)

        assert 'due_date' in result
        assert 'due_time' in result
        assert 'subject' in result
        assert 'owner_id' in result  # Changed from user_id in API v2
        assert 'participants' in result  # Changed from person_id in API v2, array format
        assert result['participants'] == [{'person_id': 123, 'primary': True}]
        assert 'org_id' in result
        assert result['org_id'] == 456

    def test_meeting_to_activity_data_with_deal(self, db, test_meeting, test_deal):
        """Test converting Meeting with deal_id includes deal_id in activity"""
        test_deal.pd_deal_id = 12345
        db.add(test_deal)
        db.commit()

        test_meeting.deal_id = test_deal.id
        db.add(test_meeting)
        db.commit()

        result = _meeting_to_activity_data(test_meeting, db)

        assert 'deal_id' in result
        assert result['deal_id'] == 12345
