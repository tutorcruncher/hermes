"""
End-to-end tests for Pipedrive API rate limiting.

These tests make REAL HTTP requests to the TC2 callback endpoint
and verify that rate limiting works correctly with actual Pipedrive API calls.
"""

import asyncio
import threading
import time
from datetime import datetime, timezone

import pytest
from aiohttp import web
from sqlmodel import select

from app.main_app.models import Company


@pytest.fixture(scope='session')
def mock_pipedrive_server():
    """Create a real HTTP server that enforces rate limiting (shared across all tests)"""
    call_times = []
    request_count = [0]

    async def handle_request(request):
        nonlocal call_times
        current_time = time.time()
        call_times.append(current_time)

        recent_calls = [t for t in call_times if current_time - t < 2]
        request_count[0] += 1

        if len(recent_calls) > 10:
            return web.json_response(
                {'error': 'Rate limit exceeded'},
                status=429,
                headers={
                    'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': '2',
                },
            )

        return web.json_response(
            {'data': {'id': request_count[0]}},
            headers={
                'x-ratelimit-limit': '10',
                'x-ratelimit-remaining': str(10 - len(recent_calls)),
                'x-ratelimit-reset': '2',
                'x-daily-requests-left': '9500',
            },
        )

    app = web.Application()
    app.router.add_route('*', '/{tail:.*}', handle_request)

    runner = web.AppRunner(app)
    loop = asyncio.new_event_loop()

    def run_server():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, '127.0.0.1', 8765)
        loop.run_until_complete(site.start())
        loop.run_forever()

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    time.sleep(1)  # Wait for server to start

    yield 'http://127.0.0.1:8765'

    # Cleanup
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)


@pytest.fixture(autouse=True)
async def reset_pipedrive_client():
    """Reset the Pipedrive API client before each test"""
    import app.pipedrive.api as api_module

    # Reset client before test - let it be recreated with proper event loop
    api_module._client = None
    yield
    # Wait a bit for background tasks to finish
    import asyncio

    await asyncio.sleep(0.5)
    # After test, just reset the reference
    api_module._client = None


@pytest.fixture
def sample_tc_webhook_data(test_admin):
    """Sample TC2 webhook payload"""
    return {
        'events': [
            {
                'action': 'UPDATE',
                'verb': 'update',
                'subject': {
                    'model': 'Client',
                    'id': 100,
                    'meta_agency': {
                        'id': 200,
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
                            'id': 300,
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


class TestEndToEndRateLimiting:
    """End-to-end tests for rate limiting with real HTTP requests"""

    @pytest.mark.asyncio
    async def test_single_tc2_webhook_with_rate_limiting(
        self, client, db, test_admin, sample_tc_webhook_data, mock_pipedrive_server, monkeypatch
    ):
        """Test single TC2 webhook triggers Pipedrive sync with rate limiting"""
        monkeypatch.setattr('app.core.config.settings.pd_base_url', mock_pipedrive_server)

        response = client.post(client.app.url_path_for('tc2-callback'), json=sample_tc_webhook_data)

        assert response.status_code == 200
        assert response.json() == {'status': 'ok'}

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 100)).first()
        assert company is not None
        assert company.name == 'Test Company'

    @pytest.mark.asyncio
    async def test_multiple_tc2_webhooks_respect_rate_limits(
        self, client, db, test_admin, mock_pipedrive_server, monkeypatch
    ):
        """Test multiple TC2 webhooks are rate limited correctly"""
        monkeypatch.setattr('app.core.config.settings.pd_base_url', mock_pipedrive_server)

        webhooks = []
        for i in range(5):
            webhooks.append(
                {
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
                                    'paid_invoice_count': i,
                                    'created': datetime.now(timezone.utc).isoformat(),
                                    'price_plan': 'monthly-payg',
                                    'narc': False,
                                },
                                'user': {
                                    'first_name': 'User',
                                    'last_name': str(i),
                                    'email': f'user{i}@example.com',
                                },
                                'status': 'active',
                                'sales_person': {'id': test_admin.tc2_admin_id},
                                'paid_recipients': [],
                                'extra_attrs': [],
                            },
                        }
                    ],
                    '_request_time': 1234567890,
                }
            )

        for webhook in webhooks:
            response = client.post(client.app.url_path_for('tc2-callback'), json=webhook)
            assert response.status_code == 200

        companies = db.exec(select(Company)).all()
        assert len(companies) == 5

        for i in range(5):
            company = db.exec(select(Company).where(Company.tc2_cligency_id == 100 + i)).first()
            assert company is not None
            assert company.name == f'Company {i}'

    @pytest.mark.asyncio
    async def test_batch_webhook_with_multiple_companies(
        self, client, db, test_admin, mock_pipedrive_server, monkeypatch
    ):
        """Test batch webhook with multiple companies in single request"""
        monkeypatch.setattr('app.core.config.settings.pd_base_url', mock_pipedrive_server)

        webhook_data = {
            'events': [
                {
                    'action': 'UPDATE',
                    'verb': 'update',
                    'subject': {
                        'model': 'Client',
                        'id': 500 + i,
                        'meta_agency': {
                            'id': 600 + i,
                            'name': f'Batch Company {i}',
                            'country': 'United Kingdom (GB)',
                            'status': 'active',
                            'paid_invoice_count': 0,
                            'created': datetime.now(timezone.utc).isoformat(),
                            'price_plan': 'monthly-payg',
                            'narc': False,
                        },
                        'user': {
                            'first_name': 'Batch',
                            'last_name': f'User{i}',
                            'email': f'batch{i}@example.com',
                        },
                        'status': 'active',
                        'sales_person': {'id': test_admin.tc2_admin_id},
                        'paid_recipients': [],
                        'extra_attrs': [],
                    },
                }
                for i in range(10)
            ],
            '_request_time': 1234567890,
        }

        response = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)
        assert response.status_code == 200

        companies = db.exec(select(Company).where(Company.tc2_cligency_id >= 500)).all()
        assert len(companies) == 10

    @pytest.mark.asyncio
    async def test_rate_limiter_spaces_out_burst_requests(
        self, client, db, test_admin, mock_pipedrive_server, monkeypatch
    ):
        """Test that rate limiter spaces out burst requests to prevent 429 errors"""
        import asyncio

        from app.pipedrive import api

        monkeypatch.setattr('app.core.config.settings.pd_base_url', mock_pipedrive_server)
        start_time = time.time()
        tasks = []
        for i in range(12):
            org_data = {
                'name': f'Burst Test Company {i}',
                'custom_fields': {},
            }
            tasks.append(api.create_organisation(org_data))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.time() - start_time

        successful = 0
        for result in results:
            if not isinstance(result, Exception):
                successful += 1

        # With rate limiting at 9 req/2sec, 12 requests should take at least 2+ seconds
        assert elapsed >= 2.0, f'Requests completed too fast ({elapsed}s), rate limiter may not be working'
        assert successful >= 10, f'Only {successful}/12 requests succeeded, rate limiter may not be effective'

    @pytest.mark.asyncio
    async def test_without_rate_limiter_gets_429_errors(
        self, client, db, test_admin, mock_pipedrive_server, monkeypatch, caplog
    ):
        """Test that WITHOUT rate limiter, we DO get 429 errors from burst requests"""
        import httpx

        monkeypatch.setattr('app.core.config.settings.pd_base_url', mock_pipedrive_server)
        # Create a regular httpx client WITHOUT rate limiting
        monkeypatch.setattr('app.pipedrive.api._client', httpx.AsyncClient())

        # Fire 15 webhooks in rapid succession (will exceed 10 req/2sec)
        webhooks = []
        for i in range(15):
            webhooks.append(
                {
                    'events': [
                        {
                            'action': 'UPDATE',
                            'verb': 'update',
                            'subject': {
                                'model': 'Client',
                                'id': 900 + i,
                                'meta_agency': {
                                    'id': 1000 + i,
                                    'name': f'No Limit Company {i}',
                                    'country': 'United Kingdom (GB)',
                                    'status': 'active',
                                    'paid_invoice_count': 0,
                                    'created': datetime.now(timezone.utc).isoformat(),
                                    'price_plan': 'monthly-payg',
                                    'narc': False,
                                },
                                'user': {
                                    'first_name': 'NoLimit',
                                    'last_name': str(i),
                                    'email': f'nolimit{i}@example.com',
                                },
                                'status': 'active',
                                'sales_person': {'id': test_admin.tc2_admin_id},
                                'paid_recipients': [],
                                'extra_attrs': [],
                            },
                        }
                    ],
                    '_request_time': 1234567890,
                }
            )

        # Fire all webhooks rapidly - some will fail with 429
        for webhook in webhooks:
            client.post(client.app.url_path_for('tc2-callback'), json=webhook)

        # Verify 429 errors occurred in logs
        assert '429' in caplog.text


class TestCloudflareRateLimiting:
    """Tests for Cloudflare 403 rate limiting with retry logic"""

    @pytest.mark.asyncio
    async def test_403_cloudflare_retry_succeeds_on_second_attempt(self, monkeypatch):
        """Test that 403 Cloudflare rate limit retries and succeeds"""
        from unittest.mock import AsyncMock, patch

        from app.pipedrive import api
        from tests.helpers import MockResponse

        monkeypatch.setattr('app.core.config.settings.pd_api_enable_retry', True)
        monkeypatch.setattr('app.core.config.settings.pd_api_max_retry', 3)

        call_count = [0]

        async def mock_request_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MockResponse(
                    json_data={'error': 'Cloudflare rate limit'},
                    status_code=403,
                    headers={
                        'x-ratelimit-limit': '10',
                        'x-ratelimit-remaining': '0',
                        'x-ratelimit-reset': '2',
                        'x-daily-requests-left': '9500',
                    },
                    raise_for_status_error=True,
                )
            return MockResponse(
                json_data={'data': {'id': 999, 'name': 'Test Org'}},
                status_code=200,
                headers={
                    'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '9',
                    'x-ratelimit-reset': '2',
                    'x-daily-requests-left': '9499',
                },
            )

        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = mock_request_side_effect

            result = await api.pipedrive_request('organizations/999')

            assert result == {'data': {'id': 999, 'name': 'Test Org'}}
            assert call_count[0] == 2

    @pytest.mark.asyncio
    async def test_429_api_retry_succeeds_on_third_attempt(self, monkeypatch):
        """Test that 429 API rate limit retries multiple times and succeeds"""
        from unittest.mock import AsyncMock, patch

        from app.pipedrive import api
        from tests.helpers import MockResponse

        monkeypatch.setattr('app.core.config.settings.pd_api_enable_retry', True)
        monkeypatch.setattr('app.core.config.settings.pd_api_max_retry', 5)

        call_count = [0]

        async def mock_request_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return MockResponse(
                    json_data={'error': 'Rate limit exceeded'},
                    status_code=429,
                    headers={
                        'x-ratelimit-limit': '10',
                        'x-ratelimit-remaining': '0',
                        'x-ratelimit-reset': '2',
                        'x-daily-requests-left': '9500',
                    },
                    raise_for_status_error=True,
                )
            return MockResponse(
                json_data={'data': {'id': 888}},
                status_code=200,
                headers={
                    'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '8',
                    'x-ratelimit-reset': '2',
                    'x-daily-requests-left': '9498',
                },
            )

        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = mock_request_side_effect

            result = await api.pipedrive_request('organizations/888')

            assert result == {'data': {'id': 888}}
            assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_403_retry_fails_after_max_attempts(self, monkeypatch):
        """Test that 403 errors fail after max retry attempts"""
        from unittest.mock import AsyncMock, patch

        import httpx

        from app.pipedrive import api
        from tests.helpers import MockResponse

        monkeypatch.setattr('app.core.config.settings.pd_api_enable_retry', True)
        monkeypatch.setattr('app.core.config.settings.pd_api_max_retry', 3)

        async def mock_request_side_effect(*args, **kwargs):
            return MockResponse(
                json_data={'error': 'Cloudflare rate limit'},
                status_code=403,
                headers={
                    'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': '2',
                    'x-daily-requests-left': '9500',
                },
                raise_for_status_error=True,
            )

        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = mock_request_side_effect

            with pytest.raises(httpx.HTTPStatusError):
                await api.pipedrive_request('organizations/777')

            assert mock_request.call_count == 4

    @pytest.mark.asyncio
    async def test_403_no_retry_when_disabled(self, monkeypatch):
        """Test that 403 errors do not retry when retry is disabled"""
        from unittest.mock import AsyncMock, patch

        import httpx

        from app.pipedrive import api
        from tests.helpers import MockResponse

        monkeypatch.setattr('app.core.config.settings.pd_api_enable_retry', False)

        async def mock_request_side_effect(*args, **kwargs):
            return MockResponse(
                json_data={'error': 'Cloudflare rate limit'},
                status_code=403,
                headers={
                    'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': '2',
                    'x-daily-requests-left': '9500',
                },
                raise_for_status_error=True,
            )

        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = mock_request_side_effect

            with pytest.raises(httpx.HTTPStatusError):
                await api.pipedrive_request('organizations/666')

            assert mock_request.call_count == 1

    @pytest.mark.asyncio
    async def test_mixed_403_and_429_retries(self, monkeypatch):
        """Test that both 403 and 429 errors are retried correctly"""
        from unittest.mock import AsyncMock, patch

        from app.pipedrive import api
        from tests.helpers import MockResponse

        monkeypatch.setattr('app.core.config.settings.pd_api_enable_retry', True)
        monkeypatch.setattr('app.core.config.settings.pd_api_max_retry', 5)

        call_count = [0]

        async def mock_request_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MockResponse(
                    json_data={'error': 'Cloudflare rate limit'},
                    status_code=403,
                    headers={
                        'x-ratelimit-limit': '10',
                        'x-ratelimit-remaining': '0',
                        'x-ratelimit-reset': '2',
                        'x-daily-requests-left': '9500',
                    },
                    raise_for_status_error=True,
                )
            if call_count[0] == 2:
                return MockResponse(
                    json_data={'error': 'API rate limit exceeded'},
                    status_code=429,
                    headers={
                        'x-ratelimit-limit': '10',
                        'x-ratelimit-remaining': '0',
                        'x-ratelimit-reset': '2',
                        'x-daily-requests-left': '9500',
                    },
                    raise_for_status_error=True,
                )
            return MockResponse(
                json_data={'data': {'id': 555, 'name': 'Success'}},
                status_code=200,
                headers={
                    'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '7',
                    'x-ratelimit-reset': '2',
                    'x-daily-requests-left': '9498',
                },
            )

        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = mock_request_side_effect

            result = await api.pipedrive_request('organizations/555')

            assert result == {'data': {'id': 555, 'name': 'Success'}}
            assert call_count[0] == 3

    @pytest.mark.asyncio
    async def test_404_error_does_not_retry(self, monkeypatch):
        """Test that non-rate-limit errors like 404 do not trigger retry"""
        from unittest.mock import AsyncMock, patch

        import httpx

        from app.pipedrive import api
        from tests.helpers import MockResponse

        monkeypatch.setattr('app.core.config.settings.pd_api_enable_retry', True)
        monkeypatch.setattr('app.core.config.settings.pd_api_max_retry', 3)

        async def mock_request_side_effect(*args, **kwargs):
            return MockResponse(
                json_data={'error': 'Not found'},
                status_code=404,
                headers={
                    'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '9',
                    'x-ratelimit-reset': '2',
                    'x-daily-requests-left': '9500',
                },
                raise_for_status_error=True,
            )

        with patch('httpx.AsyncClient.request', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = mock_request_side_effect

            with pytest.raises(httpx.HTTPStatusError):
                await api.pipedrive_request('organizations/404')

            assert mock_request.call_count == 1
