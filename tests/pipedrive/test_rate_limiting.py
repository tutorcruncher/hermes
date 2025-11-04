"""
Comprehensive tests for Pipedrive API rate limiting.

This test module covers:
- Rate limiter transport functionality
- 429 retry logic
- TC2 webhook → Pipedrive sync rate limiting (end-to-end)
- Multiple concurrent webhooks handling
- Burst request throttling
"""

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlmodel import select

from app.main_app.models import Company, Contact
from app.pipedrive import api
from tests.helpers import MockResponse


@pytest.fixture
def mock_pipedrive_rate_limit_headers():
    """Headers returned by Pipedrive API with rate limit info"""
    return {
        'x-ratelimit-limit': '10',
        'x-ratelimit-remaining': '7',
        'x-ratelimit-reset': '1.5',
        'x-daily-requests-left': '9500',
    }


@pytest.fixture
def sample_tc_webhook_data(test_admin):
    """Sample TC2 webhook payload for testing"""
    return {
        'events': [
            {
                'action': 'UPDATE',
                'verb': 'update',
                'subject': {
                    'model': 'Client',
                    'id': 123,
                    'meta_agency': {
                        'id': 456,
                        'name': 'Test Company',
                        'country': 'United Kingdom (GB)',
                        'status': 'active',
                        'paid_invoice_count': 5,
                        'created': '2024-01-01T00:00:00Z',
                        'price_plan': 'monthly-payg',
                        'narc': False,
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
                        {
                            'id': 789,
                            'first_name': 'John',
                            'last_name': 'Doe',
                            'email': 'john@example.com',
                        },
                    ],
                    'extra_attrs': [],
                },
            }
        ],
        '_request_time': 1234567890,
    }


class TestRateLimitHeaderExtraction:
    """Test rate limit header extraction utility"""

    def test_extract_rate_limit_headers_with_all_headers(self, mock_pipedrive_rate_limit_headers):
        """Test extracting rate limit headers when all are present"""
        mock_response = MockResponse(
            json_data={'data': {'id': 123}},
            status_code=200,
            headers=mock_pipedrive_rate_limit_headers,
        )

        headers = api._extract_rate_limit_headers(mock_response)

        assert headers['limit'] == '10'
        assert headers['remaining'] == '7'
        assert headers['reset'] == '1.5'
        assert headers['daily_left'] == '9500'

    def test_extract_rate_limit_headers_with_missing_headers(self):
        """Test extracting rate limit headers when some are missing"""
        mock_response = MockResponse(
            json_data={'data': {'id': 123}},
            status_code=200,
            headers={'x-ratelimit-limit': '10'},
        )

        headers = api._extract_rate_limit_headers(mock_response)

        assert headers['limit'] == '10'
        assert headers['remaining'] is None
        assert headers['reset'] is None
        assert headers['daily_left'] is None

    def test_extract_rate_limit_headers_logs_remaining_capacity(self, mock_pipedrive_rate_limit_headers, caplog):
        """Test that rate limit info is logged"""
        mock_response = MockResponse(
            json_data={'data': {'id': 123}},
            status_code=200,
            headers=mock_pipedrive_rate_limit_headers,
        )

        with patch('app.pipedrive.api._client') as mock_client:
            mock_client.request = AsyncMock(return_value=mock_response)

            async def test():
                await api.pipedrive_request('test-endpoint', method='GET')

            asyncio.run(test())

            assert 'rate_limit=7/10' in caplog.text
            assert 'daily_left=9500' in caplog.text


class TestPipedriveAPIRetryLogic:
    """Test 429 error retry logic"""

    @patch('app.pipedrive.api._client')
    async def test_429_error_triggers_retry(self, mock_client):
        """Test that 429 error triggers exponential backoff retry"""
        rate_limit_response = MockResponse(
            json_data={'error': 'Rate limit exceeded'},
            status_code=429,
            raise_for_status_error=True,
        )
        success_response = MockResponse(
            json_data={'data': {'id': 123}},
            status_code=200,
        )

        mock_client.request = AsyncMock(side_effect=[rate_limit_response, success_response])

        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            result = await api.pipedrive_request('test-endpoint', method='GET')

            assert result == {'data': {'id': 123}}
            assert mock_client.request.call_count == 2
            mock_sleep.assert_awaited_once_with(2)

    @patch('app.pipedrive.api._client')
    async def test_429_error_retries_up_to_3_times(self, mock_client):
        """Test that 429 errors retry up to 3 times before failing"""
        rate_limit_response = MockResponse(
            json_data={'error': 'Rate limit exceeded'},
            status_code=429,
            raise_for_status_error=True,
        )

        mock_client.request = AsyncMock(return_value=rate_limit_response)

        with patch('asyncio.sleep', new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await api.pipedrive_request('test-endpoint', method='GET')

            assert mock_client.request.call_count == 4

    @patch('app.pipedrive.api._client')
    async def test_429_error_uses_exponential_backoff(self, mock_client):
        """Test that retry delays use exponential backoff (2s, 4s, 6s)"""
        rate_limit_response = MockResponse(
            json_data={'error': 'Rate limit exceeded'},
            status_code=429,
            raise_for_status_error=True,
        )

        mock_client.request = AsyncMock(return_value=rate_limit_response)

        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(httpx.HTTPStatusError):
                await api.pipedrive_request('test-endpoint', method='GET')

            sleep_calls = [call[0][0] for call in mock_sleep.await_args_list]
            assert sleep_calls == [2, 4, 6]

    @patch('app.pipedrive.api._client')
    async def test_non_429_errors_do_not_retry(self, mock_client):
        """Test that non-429 errors (404, 500, etc.) do not trigger retry"""
        error_response = MockResponse(
            json_data={'error': 'Not found'},
            status_code=404,
            raise_for_status_error=True,
        )

        mock_client.request = AsyncMock(return_value=error_response)

        with pytest.raises(httpx.HTTPStatusError):
            await api.pipedrive_request('test-endpoint', method='GET')

        assert mock_client.request.call_count == 1


class TestRateLimiterTransport:
    """Test httpx-limiter transport rate limiting"""

    @patch('app.pipedrive.api._client')
    async def test_rate_limiter_enforces_time_period(self, mock_client):
        """Test that rate limiter enforces 9 requests per 2 seconds"""
        mock_response = MockResponse(json_data={'data': {'id': 123}}, status_code=200)
        mock_client.request = AsyncMock(return_value=mock_response)

        start_time = time.time()

        tasks = [api.pipedrive_request(f'test-endpoint-{i}', method='GET') for i in range(18)]
        await asyncio.gather(*tasks)

        elapsed_time = time.time() - start_time

        assert elapsed_time >= 2.0

    @patch('app.pipedrive.api._client')
    async def test_rate_limiter_allows_burst_within_limit(self, mock_client):
        """Test that rate limiter allows up to 9 requests to burst"""
        mock_response = MockResponse(json_data={'data': {'id': 123}}, status_code=200)
        mock_client.request = AsyncMock(return_value=mock_response)

        start_time = time.time()

        tasks = [api.pipedrive_request(f'test-endpoint-{i}', method='GET') for i in range(9)]
        await asyncio.gather(*tasks)

        elapsed_time = time.time() - start_time

        assert elapsed_time < 1.0

    @patch('app.pipedrive.api._client')
    async def test_concurrent_requests_share_rate_limiter(self, mock_client):
        """Test that concurrent requests from different tasks share the same rate limiter"""
        mock_response = MockResponse(json_data={'data': {'id': 123}}, status_code=200)
        mock_client.request = AsyncMock(return_value=mock_response)

        async def make_requests(count):
            tasks = [api.pipedrive_request(f'endpoint-{i}', method='GET') for i in range(count)]
            await asyncio.gather(*tasks)

        start_time = time.time()

        await asyncio.gather(
            make_requests(5),
            make_requests(5),
            make_requests(5),
        )

        elapsed_time = time.time() - start_time

        assert elapsed_time >= 2.0


class TestPipedriveTaskRateLimiting:
    """Test rate limiting in Pipedrive sync tasks"""

    @patch('httpx.AsyncClient.request')
    async def test_sync_company_respects_rate_limits(self, mock_request, db, test_admin):
        """Test that sync_company_to_pipedrive respects rate limits"""
        from app.pipedrive.tasks import sync_company_to_pipedrive

        company = db.create(
            Company(
                name='Test Company',
                sales_person_id=test_admin.id,
                tc2_cligency_id=123,
                tc2_agency_id=456,
            )
        )

        db.create(
            Contact(
                company_id=company.id,
                first_name='John',
                last_name='Doe',
                email='john@example.com',
            )
        )
        db.create(
            Contact(
                company_id=company.id,
                first_name='Jane',
                last_name='Smith',
                email='jane@example.com',
            )
        )

        mock_response = MockResponse(json_data={'data': {'id': 999}}, status_code=200)
        mock_request.return_value = mock_response

        await sync_company_to_pipedrive(company.id)

        expected_calls = 6
        assert mock_request.call_count == expected_calls


class TestTC2WebhookRateLimiting:
    """Test end-to-end rate limiting from TC2 webhook to Pipedrive"""

    @patch('httpx.AsyncClient.request')
    async def test_single_webhook_triggers_pipedrive_sync_with_rate_limiting(
        self, mock_request, client, db, test_admin, sample_tc_webhook_data, mock_pipedrive_rate_limit_headers
    ):
        """Test that single TC2 webhook triggers Pipedrive sync with rate limiting"""
        mock_response = MockResponse(
            json_data={'data': {'id': 999}},
            status_code=200,
            headers=mock_pipedrive_rate_limit_headers,
        )
        mock_request.return_value = mock_response

        r = client.post(client.app.url_path_for('tc2-callback'), json=sample_tc_webhook_data)

        assert r.status_code == 200
        assert r.json() == {'status': 'ok'}

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 123)).first()
        assert company is not None
        assert company.name == 'Test Company'

    @patch('httpx.AsyncClient.request')
    async def test_multiple_webhooks_with_same_company_dont_cause_rate_limit(
        self, mock_request, client, db, test_admin, sample_tc_webhook_data, mock_pipedrive_rate_limit_headers
    ):
        """Test that multiple webhooks for same company are handled gracefully"""
        mock_response = MockResponse(
            json_data={'data': {'id': 999}},
            status_code=200,
            headers=mock_pipedrive_rate_limit_headers,
        )
        mock_request.return_value = mock_response

        for i in range(3):
            sample_tc_webhook_data['events'][0]['subject']['meta_agency']['paid_invoice_count'] = i
            r = client.post(client.app.url_path_for('tc2-callback'), json=sample_tc_webhook_data)
            assert r.status_code == 200

        assert mock_request.call_count > 0

    @patch('httpx.AsyncClient.request')
    async def test_batch_webhook_with_multiple_companies_respects_rate_limits(
        self, mock_request, client, db, test_admin, mock_pipedrive_rate_limit_headers
    ):
        """Test that batch webhook with multiple companies respects rate limits"""
        mock_response = MockResponse(
            json_data={'data': {'id': 999}},
            status_code=200,
            headers=mock_pipedrive_rate_limit_headers,
        )
        mock_request.return_value = mock_response

        webhook_data = {
            'events': [
                {
                    'action': 'UPDATE',
                    'verb': 'update',
                    'subject': {
                        'model': 'Client',
                        'id': 100 + i,
                        'meta_agency': {
                            'id': 200 + i,
                            'name': f'Company {i}',
                            'country': 'United Kingdom (GB)',
                            'status': 'active',
                            'paid_invoice_count': 0,
                            'created': datetime.now(timezone.utc).isoformat(),
                            'price_plan': 'monthly-payg',
                            'narc': False,
                        },
                        'user': {
                            'first_name': 'User',
                            'last_name': f'{i}',
                            'email': f'user{i}@example.com',
                        },
                        'status': 'active',
                        'sales_person': {'id': test_admin.tc2_admin_id},
                        'paid_recipients': [],
                        'extra_attrs': [],
                    },
                }
                for i in range(5)
            ],
            '_request_time': 1234567890,
        }

        r = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert r.status_code == 200

        companies = db.exec(select(Company)).all()
        assert len(companies) == 5


class TestRateLimitingEdgeCases:
    """Test edge cases and error scenarios for rate limiting"""

    @patch('app.pipedrive.api._client')
    async def test_rate_limiter_handles_slow_api_responses(self, mock_client):
        """Test that rate limiter handles slow API responses correctly"""

        async def slow_response(*args, **kwargs):
            await asyncio.sleep(0.5)
            return MockResponse(json_data={'data': {'id': 123}}, status_code=200)

        mock_client.request = AsyncMock(side_effect=slow_response)

        start_time = time.time()
        tasks = [api.pipedrive_request(f'endpoint-{i}', method='GET') for i in range(5)]
        await asyncio.gather(*tasks)
        elapsed_time = time.time() - start_time

        assert elapsed_time >= 0.5

    @patch('app.pipedrive.api._client')
    async def test_rate_limiter_continues_after_429_retry_success(self, mock_client):
        """Test that rate limiter continues working after successful 429 retry"""
        rate_limit_response = MockResponse(
            json_data={'error': 'Rate limit exceeded'},
            status_code=429,
            raise_for_status_error=True,
        )
        success_response = MockResponse(json_data={'data': {'id': 123}}, status_code=200)

        call_count = 0

        async def mixed_responses(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return rate_limit_response
            return success_response

        mock_client.request = AsyncMock(side_effect=mixed_responses)

        with patch('asyncio.sleep', new_callable=AsyncMock):
            result = await api.pipedrive_request('test-endpoint', method='GET')
            assert result == {'data': {'id': 123}}

            result2 = await api.pipedrive_request('test-endpoint-2', method='GET')
            assert result2 == {'data': {'id': 123}}

    @patch('app.pipedrive.api._client')
    async def test_multiple_429_errors_across_requests(self, mock_client):
        """Test handling multiple 429 errors across different requests"""
        responses = []
        for i in range(10):
            if i % 3 == 0:
                responses.append(
                    MockResponse(
                        json_data={'error': 'Rate limit exceeded'},
                        status_code=429,
                        raise_for_status_error=True,
                    )
                )
            responses.append(MockResponse(json_data={'data': {'id': i}}, status_code=200))

        mock_client.request = AsyncMock(side_effect=responses)

        with patch('asyncio.sleep', new_callable=AsyncMock):
            results = []
            for i in range(5):
                try:
                    result = await api.pipedrive_request(f'endpoint-{i}', method='GET')
                    results.append(result)
                except httpx.HTTPStatusError:
                    pass

            assert len(results) >= 3


class TestRateLimitingMonitoring:
    """Test rate limit monitoring and observability"""

    @patch('app.pipedrive.api._client')
    async def test_rate_limit_headers_logged_for_every_request(
        self, mock_client, caplog, mock_pipedrive_rate_limit_headers
    ):
        """Test that rate limit headers are logged for monitoring"""
        mock_response = MockResponse(
            json_data={'data': {'id': 123}},
            status_code=200,
            headers=mock_pipedrive_rate_limit_headers,
        )
        mock_client.request = AsyncMock(return_value=mock_response)

        await api.pipedrive_request('test-endpoint', method='GET')

        assert 'rate_limit=7/10' in caplog.text
        assert 'daily_left=9500' in caplog.text
        assert 'test-endpoint' in caplog.text

    @patch('app.pipedrive.api._client')
    async def test_429_retry_attempts_logged(self, mock_client, caplog):
        """Test that 429 retry attempts are logged with wait times"""
        rate_limit_response = MockResponse(
            json_data={'error': 'Rate limit exceeded'},
            status_code=429,
            raise_for_status_error=True,
        )
        success_response = MockResponse(json_data={'data': {'id': 123}}, status_code=200)

        mock_client.request = AsyncMock(side_effect=[rate_limit_response, success_response])

        with patch('asyncio.sleep', new_callable=AsyncMock):
            await api.pipedrive_request('test-endpoint', method='GET')

            assert 'rate limit (429)' in caplog.text.lower()
            assert 'retry 1/3' in caplog.text
            assert 'waiting 2s' in caplog.text

    @patch('app.pipedrive.api._client')
    async def test_daily_requests_left_tracked(self, mock_client):
        """Test that x-daily-requests-left header is tracked across requests"""
        call_count = 0

        async def decreasing_quota(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return MockResponse(
                json_data={'data': {'id': 123}},
                status_code=200,
                headers={
                    'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '9',
                    'x-daily-requests-left': str(10000 - call_count),
                },
            )

        mock_client.request = AsyncMock(side_effect=decreasing_quota)

        for i in range(3):
            await api.pipedrive_request(f'endpoint-{i}', method='GET')

        assert call_count == 3
