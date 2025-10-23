"""
Tests for Pipedrive sync tasks.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.pipedrive.tasks import sync_organization


class TestSyncOrganization:
    """Test sync_organization function"""

    async def test_sync_organization_raises_on_create_failure(self, db, test_company):
        """Test that sync_organization raises exception when organization creation fails"""
        # Mock the API to raise an exception
        with patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = Exception('Pipedrive API error: validation failed')

            # Should raise the exception instead of swallowing it
            with pytest.raises(Exception, match='Pipedrive API error: validation failed'):
                await sync_organization(test_company, db)

            # Verify the API was called
            mock_create.assert_called_once()

    async def test_sync_organization_raises_on_update_failure_non_404(self, db, test_company):
        """Test that sync_organization raises exception when update fails with non-404 error"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        # Mock the API to raise a validation error (not 404)
        with patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = Exception('Pipedrive API error: 400 Bad Request')

            # Should raise the exception instead of swallowing it
            with pytest.raises(Exception, match='400 Bad Request'):
                await sync_organization(test_company, db)

            # Verify the API was called
            mock_get.assert_called_once()

    async def test_sync_organization_recreates_on_404(self, db, test_company):
        """Test that sync_organization recreates organization when getting 404 on update"""
        test_company.pd_org_id = 999
        db.add(test_company)
        db.commit()

        # Mock the API: get returns 404, then create succeeds
        with (
            patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock) as mock_get,
            patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock) as mock_create,
        ):
            mock_get.side_effect = Exception('404 Not Found')
            mock_create.return_value = {'data': {'id': 1000}}

            # Should not raise, should create new org
            await sync_organization(test_company, db)

            # Verify get was called, then create was called
            mock_get.assert_called_once()
            mock_create.assert_called_once()

            # Verify pd_org_id was updated to new value
            db.refresh(test_company)
            assert test_company.pd_org_id == 1000

    async def test_sync_organization_success_create(self, db, test_company):
        """Test successful organization creation"""
        # Mock the API to succeed
        with patch('app.pipedrive.tasks.api.create_organisation', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = {'data': {'id': 888}}

            await sync_organization(test_company, db)

            # Verify the organization was created
            mock_create.assert_called_once()
            db.refresh(test_company)
            assert test_company.pd_org_id == 888

    async def test_sync_organization_success_update(self, db, test_company):
        """Test successful organization update"""
        test_company.pd_org_id = 999
        test_company.name = 'Old Name'
        db.add(test_company)
        db.commit()

        # Mock the API to succeed
        with (
            patch('app.pipedrive.tasks.api.get_organisation', new_callable=AsyncMock) as mock_get,
            patch('app.pipedrive.tasks.api.update_organisation', new_callable=AsyncMock) as mock_update,
        ):
            mock_get.return_value = {'data': {'id': 999, 'name': 'Old Name'}}
            mock_update.return_value = {'data': {'id': 999, 'name': 'New Name'}}

            # Change the name to trigger an update
            test_company.name = 'New Name'
            db.add(test_company)
            db.commit()

            await sync_organization(test_company, db)

            # Verify the organization was updated
            mock_get.assert_called_once_with(999)
            mock_update.assert_called_once()
