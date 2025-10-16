"""Tests for Pipedrive API functions."""

from unittest import mock

from tests._common import HermesTestCase
from tests.pipedrive.helpers import FakePipedrive


class PipedriveAPITestCase(HermesTestCase):
    def setUp(self):
        """Synchronous setup (called for each test)"""
        super().setUp()
        self.pipedrive = FakePipedrive()

    @mock.patch('app.pipedrive.api.session.request')
    async def test_pipedrive_request_uses_json_encoding(self, mock_request):
        """Test that pipedrive_request uses json= parameter for proper JSON encoding."""
        from app.pipedrive.api import pipedrive_request

        # Mock successful response
        mock_request.return_value.json.return_value = {'success': True, 'data': {'id': 123}}
        mock_request.return_value.status_code = 200
        mock_request.return_value.raise_for_status = lambda: None

        # Test data with various types that would be incorrectly serialized with data= parameter
        test_data = {
            'name': 'Test Company',
            'address_country': 'GB',
            'owner_id': 15761943,
            'created': '2025-08-31',
            'optional_field': None,  # Should not be sent or be null, not string "None"
        }

        await pipedrive_request('organizations/16957', method='PUT', data=test_data)

        # Verify the request was called with json= parameter, not data= parameter
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args.kwargs

        # The key assertion: json parameter should be used, not data
        assert 'json' in call_kwargs, 'Request should use json= parameter for JSON encoding'
        assert call_kwargs['json'] == test_data, 'JSON data should match input data'
        assert 'data' not in call_kwargs or call_kwargs.get('data') is None, 'Request should not use data= parameter'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_pipedrive_request_json_serialization(self, mock_request):
        """Test that values are properly serialized as JSON, not as string representations."""
        from app.pipedrive.api import pipedrive_request

        # Mock successful response
        mock_request.return_value.json.return_value = {'success': True, 'data': {'id': 123}}
        mock_request.return_value.status_code = 200
        mock_request.return_value.raise_for_status = lambda: None

        # Test data that would fail if form-encoded
        test_data = {
            'string_value': 'Test',
            'int_value': 42,
            'none_value': None,
            'date_string': '2025-08-31',
        }

        await pipedrive_request('organizations', method='POST', data=test_data)

        # Get the actual data that was passed to the mock
        call_kwargs = mock_request.call_args.kwargs
        sent_data = call_kwargs['json']

        # Verify values are the correct types, not stringified versions
        assert sent_data['string_value'] == 'Test', 'String should not have extra quotes'
        assert sent_data['int_value'] == 42, 'Integer should remain an integer'
        assert sent_data['none_value'] is None, 'None should be None, not string "None"'
        assert sent_data['date_string'] == '2025-08-31', 'Date string should not have extra quotes'

    @mock.patch('app.pipedrive.api.session.request')
    async def test_pipedrive_request_get_method_no_data(self, mock_request):
        """Test that GET requests work correctly without data parameter."""
        from app.pipedrive.api import pipedrive_request

        # Mock successful response
        mock_request.return_value.json.return_value = {
            'success': True,
            'data': {'id': 123, 'name': 'Test Org'},
        }
        mock_request.return_value.status_code = 200
        mock_request.return_value.raise_for_status = lambda: None

        result = await pipedrive_request('organizations/123', method='GET')

        # Verify GET request was made without data/json payload
        mock_request.assert_called_once()
        call_kwargs = mock_request.call_args.kwargs
        assert call_kwargs.get('json') is None, 'GET request should not have json data'
        assert result == {'success': True, 'data': {'id': 123, 'name': 'Test Org'}}
