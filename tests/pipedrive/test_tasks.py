"""
Tests for Pipedrive sync tasks.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import func
from sqlmodel import select

from app.main_app.models import Company, Contact, Deal
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP, DEAL_PD_FIELD_MAP
from app.pipedrive.tasks import (
    _company_to_org_data,
    _deal_to_pd_data,
    _meeting_to_activity_data,
    partial_sync_deal_from_company,
    sync_company_to_pipedrive,
    sync_deal,
    sync_meeting_to_pipedrive,
    sync_organization,
    sync_person,
)
from tests.helpers import pipedrive_http_error


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

    @patch('app.core.config.settings.sync_create_deals', True)
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    async def test_concurrent_sync_creates_only_one_deal(
        self,
        mock_create_org,
        mock_get_org,
        mock_update_org,
        mock_create_person,
        mock_get_person,
        mock_update_person,
        mock_create_deal,
        mock_get_deal,
        mock_update_deal,
        db,
        test_company,
        test_contact,
        test_deal,
    ):
        """Test that two concurrent sync_company_to_pipedrive calls for the same company
        only create one PD deal, not two (the lock serializes them)."""
        test_company.pd_org_id = None
        test_contact.pd_person_id = None
        test_deal.pd_deal_id = None
        db.add(test_company)
        db.add(test_contact)
        db.add(test_deal)
        db.commit()

        mock_create_org.return_value = {'data': {'id': 100}}
        mock_get_org.return_value = {'data': {'id': 100}}
        mock_create_person.return_value = {'data': {'id': 200}}
        mock_get_person.return_value = {'data': {'id': 200}}
        mock_create_deal.return_value = {'data': {'id': 300}}
        mock_get_deal.return_value = {'data': {'id': 300}}

        # Run two syncs concurrently for the locks to serialise them
        await asyncio.gather(
            sync_company_to_pipedrive(test_company.id),
            sync_company_to_pipedrive(test_company.id),
        )

        # The first sync creates the deal; the second sync should see pd_deal_id already set
        # and do a GET+PATCH
        assert mock_create_deal.call_count == 1

    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_org_404_stops_company_sync(
        self,
        mock_get_org,
        mock_create_org,
        mock_get_person,
        mock_update_person,
        mock_create_person,
        mock_get_deal,
        mock_update_deal,
        mock_create_deal,
        db,
        test_company,
        test_contact,
        test_deal,
    ):
        """An org that is gone from Pipedrive marks the company deleted and stops the sync, so its persons
        and deals are not sent to Pipedrive with no org"""
        test_company.pd_org_id = 999
        test_contact.pd_person_id = 888
        test_deal.pd_deal_id = 777
        db.add(test_company)
        db.add(test_contact)
        db.add(test_deal)
        db.commit()

        mock_get_org.side_effect = pipedrive_http_error(404, 'organizations/999')

        await sync_company_to_pipedrive(test_company.id)

        mock_create_org.assert_not_called()
        mock_get_person.assert_not_called()
        mock_update_person.assert_not_called()
        mock_create_person.assert_not_called()
        mock_get_deal.assert_not_called()
        mock_update_deal.assert_not_called()
        mock_create_deal.assert_not_called()

        db.refresh(test_company)
        db.refresh(test_contact)
        db.refresh(test_deal)
        assert test_company.is_deleted is True
        assert test_company.pd_org_id is None
        assert test_contact.is_deleted is False
        assert test_contact.pd_person_id == 888
        assert test_deal.status == Deal.STATUS_OPEN
        assert test_deal.pd_deal_id == 777

    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_booking_sync_recreates_person_gone_from_pipedrive(
        self,
        mock_get_org,
        mock_update_org,
        mock_get_person,
        mock_create_person,
        mock_create_deal,
        db,
        test_company,
        test_contact,
    ):
        """A sync for a sales call booking recreates a contact's person that is gone from Pipedrive"""
        test_company.pd_org_id = 999
        test_contact.pd_person_id = 888
        db.add(test_company)
        db.add(test_contact)
        db.commit()

        mock_get_org.return_value = {'data': {'id': 999}}
        mock_get_person.side_effect = pipedrive_http_error(404, 'persons/888')
        mock_create_person.return_value = {'data': {'id': 1111}}
        mock_create_deal.return_value = {'data': {'id': 2222}}

        await sync_company_to_pipedrive(test_company.id, booked_contact_id=test_contact.id)

        mock_create_person.assert_called_once()
        db.refresh(test_contact)
        assert test_contact.is_deleted is False
        assert test_contact.pd_person_id == 1111

    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    async def test_booking_sync_brings_back_deleted_company_and_contact(
        self, mock_create_org, mock_create_person, db, test_company, test_contact
    ):
        """A sales call booked for a company and contact marked deleted brings both back into Pipedrive, and leaves
        the company's other deleted contacts alone"""
        test_company.is_deleted = True
        test_company.pd_org_id = None
        test_contact.is_deleted = True
        test_contact.pd_person_id = None
        db.add(test_company)
        db.add(test_contact)
        db.commit()
        other_contact = db.create(
            Contact(first_name='Other', last_name='Person', company_id=test_company.id, is_deleted=True)
        )

        mock_create_org.return_value = {'data': {'id': 1000}}
        mock_create_person.return_value = {'data': {'id': 1111}}

        await sync_company_to_pipedrive(test_company.id, booked_contact_id=test_contact.id)

        mock_create_org.assert_called_once()
        mock_create_person.assert_called_once()
        db.refresh(test_company)
        db.refresh(test_contact)
        db.refresh(other_contact)
        assert test_company.is_deleted is False
        assert test_company.pd_org_id == 1000
        assert test_contact.is_deleted is False
        assert test_contact.pd_person_id == 1111
        assert other_contact.is_deleted is True
        assert other_contact.pd_person_id is None


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

    @pytest.mark.parametrize('status_code', [404, 410])
    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_sync_organization_404_marks_company_deleted(
        self, mock_get, mock_create, mock_get_session, status_code, db, test_company
    ):
        """An org that is gone from Pipedrive marks the company deleted, as the delete webhook does, and is not
        recreated"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = pipedrive_http_error(status_code, 'organizations/999')

        assert await sync_organization(test_company.id) is False

        mock_create.assert_not_called()
        db.refresh(test_company)
        assert test_company.is_deleted is True
        assert test_company.pd_org_id is None

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_sync_organization_404_recreates_when_asked(
        self, mock_get, mock_create, mock_get_session, db, test_company
    ):
        """A sales call booking recreates an org that is gone from Pipedrive"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = pipedrive_http_error(404, 'organizations/999')
        mock_create.return_value = {'data': {'id': 1000}}

        assert await sync_organization(test_company.id, recreate_on_404=True) is True

        mock_create.assert_called_once()
        db.refresh(test_company)
        assert test_company.pd_org_id == 1000
        assert test_company.is_deleted is False

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_sync_organization_500_on_id_containing_404_raises(
        self, mock_get, mock_create, mock_get_session, db, test_company
    ):
        """A server error for an org whose id contains '404' is not taken as the org being gone"""
        test_company.pd_org_id = 14041
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = pipedrive_http_error(500, 'organizations/14041')

        with pytest.raises(httpx.HTTPStatusError):
            await sync_organization(test_company.id)

        mock_create.assert_not_called()
        db.refresh(test_company)
        assert test_company.is_deleted is False
        assert test_company.pd_org_id == 14041

    @pytest.mark.parametrize('body', [{'detail': 'Not Found'}, '<html>Not Found</html>'])
    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_sync_organization_404_without_pipedrive_body_raises(
        self, mock_get, mock_create, mock_get_session, body, db, test_company
    ):
        """A 404 that did not come from the Pipedrive API, e.g. from a wrong base URL, does not mark the company
        deleted"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = pipedrive_http_error(404, 'organizations/999', body=body)

        with pytest.raises(httpx.HTTPStatusError):
            await sync_organization(test_company.id)

        mock_create.assert_not_called()
        db.refresh(test_company)
        assert test_company.is_deleted is False
        assert test_company.pd_org_id == 999

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_organisation', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock)
    async def test_sync_organization_patch_404_after_get_raises(
        self, mock_get, mock_update, mock_create, mock_get_session, db, test_company
    ):
        """The GET just proved the org exists, so a 404 on the PATCH does not mark the company deleted"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.return_value = {'data': {'id': 999, 'name': 'Old Name'}}
        mock_update.side_effect = pipedrive_http_error(404, 'organizations/999', method='PATCH')

        with pytest.raises(httpx.HTTPStatusError):
            await sync_organization(test_company.id, recreate_on_404=True)

        mock_create.assert_not_called()
        db.refresh(test_company)
        assert test_company.is_deleted is False
        assert test_company.pd_org_id == 999

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

    async def test_company_to_org_data_sends_receive_marketing_emails_as_enum_option_ids(self, db, test_company, monkeypatch):
        """receive_marketing_emails syncs to Pipedrive as enum option IDs (single-option field)."""
        from app.pipedrive import field_mappings

        monkeypatch.setitem(
            field_mappings.COMPANY_PD_ENUM_OPTION_MAP,
            'receive_marketing_emails',
            {'yes': 101, 'no': 102},
        )
        pd_field = COMPANY_PD_FIELD_MAP['receive_marketing_emails']

        test_company.receive_marketing_emails = True
        assert _company_to_org_data(test_company)['custom_fields'][pd_field] == 101

        test_company.receive_marketing_emails = False
        assert _company_to_org_data(test_company)['custom_fields'][pd_field] == 102

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

    @pytest.mark.parametrize('status_code', [404, 410])
    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    async def test_sync_person_404_marks_contact_deleted(
        self, mock_get, mock_create, mock_get_session, status_code, db, test_contact
    ):
        """A person that is gone from Pipedrive marks the contact deleted, as the delete webhook does, and is not
        recreated"""
        test_contact.pd_person_id = 999
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = pipedrive_http_error(status_code, 'persons/999')

        await sync_person(test_contact.id)

        mock_create.assert_not_called()
        db.refresh(test_contact)
        assert test_contact.is_deleted is True
        assert test_contact.pd_person_id is None

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    async def test_sync_person_404_not_requested_again(self, mock_get, mock_create, mock_get_session, db, test_contact):
        """Once a person is found gone from Pipedrive, the next sync makes no Pipedrive call for it"""
        test_contact.pd_person_id = 999
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = pipedrive_http_error(404, 'persons/999')

        await sync_person(test_contact.id)
        await sync_person(test_contact.id)

        mock_get.assert_called_once_with(999)
        mock_create.assert_not_called()

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.update_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    async def test_sync_person_patch_404_after_get_keeps_contact(
        self, mock_get, mock_update, mock_create, mock_get_session, db, test_contact
    ):
        """The GET just proved the person exists, so a 404 on the PATCH does not mark the contact deleted"""
        test_contact.pd_person_id = 999
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.return_value = {'data': {'id': 999, 'name': 'Old Name'}}
        mock_update.side_effect = pipedrive_http_error(404, 'persons/999', method='PATCH')

        await sync_person(test_contact.id)

        mock_create.assert_not_called()
        db.refresh(test_contact)
        assert test_contact.is_deleted is False
        assert test_contact.pd_person_id == 999

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    async def test_sync_person_404_recreates_when_asked(
        self, mock_get, mock_create, mock_get_session, db, test_contact
    ):
        """A sales call booking recreates a person that is gone from Pipedrive"""
        test_contact.pd_person_id = 999
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = pipedrive_http_error(404, 'persons/999')
        mock_create.return_value = {'data': {'id': 1111}}

        await sync_person(test_contact.id, recreate_on_404=True)

        db.refresh(test_contact)
        assert test_contact.pd_person_id == 1111
        assert test_contact.is_deleted is False

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    async def test_sync_person_500_on_id_containing_404_keeps_contact(
        self, mock_get, mock_create, mock_get_session, db, test_contact
    ):
        """A server error for a person whose id contains '404' is not taken as the person being gone"""
        test_contact.pd_person_id = 14041
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = pipedrive_http_error(500, 'persons/14041')

        await sync_person(test_contact.id)

        mock_create.assert_not_called()
        db.refresh(test_contact)
        assert test_contact.is_deleted is False
        assert test_contact.pd_person_id == 14041

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    async def test_sync_person_404_after_id_changed_keeps_contact(
        self, mock_get, mock_create, mock_get_session, db, test_contact
    ):
        """If the contact got a new Pipedrive id while the request was in flight, the 404 for the old id does not
        mark it deleted"""
        test_contact.pd_person_id = 999
        db.add(test_contact)
        db.commit()

        async def relink_then_404(pd_person_id):
            test_contact.pd_person_id = 2222
            db.add(test_contact)
            db.commit()
            raise pipedrive_http_error(404, f'persons/{pd_person_id}')

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = relink_then_404

        await sync_person(test_contact.id)

        mock_create.assert_not_called()
        db.refresh(test_contact)
        assert test_contact.is_deleted is False
        assert test_contact.pd_person_id == 2222

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

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_person', new_callable=AsyncMock)
    async def test_sync_person_create_sets_marketing_status_subscribed(
        self, mock_create, mock_get_session, db, test_contact
    ):
        """Test that newly created persons have marketing_status=subscribed so
        automated campaigns can send (otherwise PD defaults to no_consent)."""
        test_contact.pd_person_id = None
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_create.return_value = {'data': {'id': 3333}}

        await sync_person(test_contact.id)

        mock_create.assert_called_once()
        payload = mock_create.call_args[0][0]
        assert payload['marketing_status'] == 'subscribed'

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_person', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_person', new_callable=AsyncMock)
    async def test_sync_person_update_does_not_set_marketing_status(
        self, mock_get, mock_update, mock_get_session, db, test_contact
    ):
        """Test that updates to existing persons never send marketing_status.

        Pipedrive only permits each status transition once; re-sending subscribed
        on every sync would fail the second time a user manually unsubscribes.
        """
        test_contact.pd_person_id = 999
        test_contact.first_name = 'NewFirst'
        db.add(test_contact)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.return_value = {'data': {'id': 999, 'name': 'Old Name', 'marketing_status': 'unsubscribed'}}
        mock_update.return_value = {'data': {'id': 999}}

        await sync_person(test_contact.id)

        mock_update.assert_called_once()
        payload = mock_update.call_args[0][1]
        assert 'marketing_status' not in payload


class TestSyncDeal:
    """Test sync_deal function"""

    @pytest.mark.parametrize('status_code', [404, 410])
    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    @patch('app.pipedrive.tasks.api.get_deal', new_callable=AsyncMock)
    async def test_sync_deal_404_marks_deal_deleted(
        self, mock_get, mock_create, mock_get_session, status_code, db, test_deal
    ):
        """A deal that is gone from Pipedrive gets the deleted status, as the delete webhook does, and is not
        recreated"""
        test_deal.pd_deal_id = 999
        db.add(test_deal)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_get.side_effect = pipedrive_http_error(status_code, 'deals/999')

        await sync_deal(test_deal.id)

        mock_create.assert_not_called()
        db.refresh(test_deal)
        assert test_deal.status == Deal.STATUS_DELETED
        assert test_deal.pd_deal_id is None

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
    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.create_deal', new_callable=AsyncMock)
    async def test_sync_deal_create_includes_pipeline_and_stage(self, mock_create, mock_get_session, db, test_deal):
        """New deals sent to Pipedrive must include pipeline_id and stage_id
        so they land in the correct pipeline (PAYG/Startup/Enterprise)."""
        test_deal.pd_deal_id = None
        db.add(test_deal)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_create.return_value = {'data': {'id': 5555}}

        await sync_deal(test_deal.id)

        mock_create.assert_called_once()
        payload = mock_create.call_args[0][0]
        assert 'pipeline_id' in payload, 'create_deal payload must include pipeline_id'
        assert payload['pipeline_id'] == test_deal.pipeline.pd_pipeline_id
        assert 'stage_id' in payload, 'create_deal payload must include stage_id'
        assert payload['stage_id'] == test_deal.stage.pd_stage_id

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
            'meeting_dt': datetime(2030, 7, 3, 9, tzinfo=utc).isoformat(),
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
            'meeting_dt': datetime(2030, 7, 3, 9, tzinfo=utc).isoformat(),
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
    async def test_partial_sync_404_marks_deal_deleted(
        self, mock_update_deal, mock_get_session, db, test_deal, test_company
    ):
        """A paying company's deal that is gone from Pipedrive gets the deleted status"""
        test_deal.pd_deal_id = 5555
        test_company.paid_invoice_count = 10
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_update_deal.side_effect = pipedrive_http_error(404, 'deals/5555', method='PATCH')

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        db.refresh(test_deal)
        assert test_deal.status == Deal.STATUS_DELETED
        assert test_deal.pd_deal_id is None

    @patch('app.pipedrive.tasks.get_session')
    @patch('app.pipedrive.tasks.api.update_deal', new_callable=AsyncMock)
    async def test_partial_sync_server_error_keeps_deal(
        self, mock_update_deal, mock_get_session, db, test_deal, test_company
    ):
        """A server error on the partial deal update does not mark the deal deleted"""
        test_deal.pd_deal_id = 5555
        test_company.paid_invoice_count = 10
        db.add(test_deal)
        db.add(test_company)
        db.commit()

        mock_get_session.return_value = SessionMock(db)
        mock_update_deal.side_effect = pipedrive_http_error(500, 'deals/5555', method='PATCH')

        await sync_deal(test_deal.id, only_syncable_deal_fields=True)

        db.refresh(test_deal)
        assert test_deal.status == Deal.STATUS_OPEN
        assert test_deal.pd_deal_id == 5555

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

        deal_count = len(db.exec(select(Deal)).all())
        assert deal_count == 1


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
            'meeting_dt': datetime(2030, 7, 3, 9, tzinfo=utc).isoformat(),
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
            'meeting_dt': datetime(2030, 7, 3, 9, tzinfo=utc).isoformat(),
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
