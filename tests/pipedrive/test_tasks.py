"""
Tests for Pipedrive sync tasks.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.pipedrive.tasks import (
    _deal_to_pd_data,
    _meeting_to_activity_data,
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
    async def test_sync_deal_update_404_then_create(self, mock_get, mock_create, mock_get_session, db, test_deal):
        """Test deal update getting 404 then creates new"""
        test_deal.pd_deal_id = 999
        db.add(test_deal)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = Exception('404 Not Found')
        mock_create.return_value = {'data': {'id': 3333}}

        await sync_deal(test_deal.id)

        db.refresh(test_deal)
        assert test_deal.pd_deal_id == 3333

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
        test_deal.paid_invoice_count = 5
        db.add(test_deal)
        db.commit()

        result = _deal_to_pd_data(test_deal, db)

        assert 'custom_fields' in result
        custom_fields = result['custom_fields']

        # Verify custom fields are present (exact field IDs depend on DEAL_PD_FIELD_MAP)
        from app.pipedrive.field_mappings import DEAL_PD_FIELD_MAP

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

        from app.pipedrive.field_mappings import DEAL_PD_FIELD_MAP

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
