"""
Tests for Pipedrive API v2 helper functions.
"""

import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.pipedrive import api
from tests.helpers import PD_NOT_FOUND_BODY


class TestPipedriveAPIHelpers:
    """Test Pipedrive API helper functions"""

    def test_get_changed_fields_returns_only_changed(self):
        """Test that get_changed_fields only returns fields that changed"""
        old_data = {'name': 'Test', 'value': 10, 'unchanged': 'same'}
        new_data = {'name': 'Updated', 'value': 10, 'unchanged': 'same', 'new_field': 'new'}

        changed = api.get_changed_fields(old_data, new_data)

        assert changed == {'name': 'Updated', 'new_field': 'new'}

    def test_get_changed_fields_with_none_old_data(self):
        """Test that get_changed_fields returns all fields when old_data is None"""
        new_data = {'name': 'Test', 'value': 10}

        changed = api.get_changed_fields(None, new_data)

        assert changed == new_data


class TestPipedriveRequestErrorLog:
    @pytest.mark.parametrize(
        'status_code, body, level',
        [
            (404, PD_NOT_FOUND_BODY, logging.WARNING),
            (410, {'success': False, 'error': 'Gone', 'code': 'ERR_GONE'}, logging.WARNING),
            (404, '<html>Not Found</html>', logging.ERROR),
            (500, {'success': False, 'error': 'Error', 'code': 'ERR'}, logging.ERROR),
        ],
        ids=['pipedrive-not-found', 'gone', 'not-from-pipedrive', 'server-error'],
    )
    @patch('httpx.AsyncClient.request', new_callable=AsyncMock)
    async def test_error_log_level(self, mock_request, status_code, body, level, caplog):
        """A gone object is logged as a warning, as its caller handles it, and any other error as an error"""
        request = httpx.Request('GET', 'https://example.pipedrive.com/api/v2/persons/1')
        if isinstance(body, str):
            mock_request.return_value = httpx.Response(status_code, text=body, request=request)
        else:
            mock_request.return_value = httpx.Response(status_code, json=body, request=request)

        with pytest.raises(httpx.HTTPStatusError):
            await api.pipedrive_request('persons/1')

        assert [r.levelno for r in caplog.records if r.getMessage().startswith('Pipedrive API error')] == [level]
