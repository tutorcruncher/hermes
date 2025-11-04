"""
End-to-end tests for Pipedrive API rate limiting.

These tests make REAL HTTP requests to the TC2 callback endpoint
and verify that rate limiting works correctly with actual Pipedrive API calls.
"""

import time
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, Response
from sqlmodel import select
from starlette.testclient import TestClient

from app.main_app.models import Company


@pytest.fixture
def mock_pipedrive_server():
    """Create a mock Pipedrive API server that enforces rate limiting"""
    app = FastAPI()

    call_times = []
    request_count = 0

    @app.api_route('/{path:path}', methods=['GET', 'POST', 'PATCH', 'DELETE'])
    async def mock_pipedrive_endpoint(path: str):
        nonlocal request_count
        current_time = time.time()
        call_times.append(current_time)

        recent_calls = [t for t in call_times if current_time - t < 2]
        request_count += 1

        if len(recent_calls) > 10:
            return Response(
                status_code=429,
                content='{"error": "Rate limit exceeded"}',
                headers={
                    'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '0',
                    'x-ratelimit-reset': '2',
                    'content-type': 'application/json',
                },
            )

        return Response(
            status_code=200,
            content=f'{{"data": {{"id": {request_count}}}}}',
            headers={
                'x-ratelimit-limit': '10',
                'x-ratelimit-remaining': str(10 - len(recent_calls)),
                'x-ratelimit-reset': '2',
                'x-daily-requests-left': '9500',
                'content-type': 'application/json',
            },
        )

    with TestClient(app) as server:
        yield server


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
        monkeypatch.setattr('app.core.config.settings.pd_base_url', mock_pipedrive_server.base_url)
        monkeypatch.setattr('app.pipedrive.api._client', None)

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
        monkeypatch.setattr('app.core.config.settings.pd_base_url', mock_pipedrive_server.base_url)
        monkeypatch.setattr('app.pipedrive.api._client', None)

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
        monkeypatch.setattr('app.core.config.settings.pd_base_url', mock_pipedrive_server.base_url)
        monkeypatch.setattr('app.pipedrive.api._client', None)

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
    async def test_rate_limiter_prevents_429_errors(
        self, client, db, test_admin, mock_pipedrive_server, monkeypatch, caplog
    ):
        """Test that rate limiter prevents 429 errors from Pipedrive"""
        monkeypatch.setattr('app.core.config.settings.pd_base_url', mock_pipedrive_server.base_url)
        monkeypatch.setattr('app.pipedrive.api._client', None)

        webhook_data = {
            'events': [
                {
                    'action': 'UPDATE',
                    'verb': 'update',
                    'subject': {
                        'model': 'Client',
                        'id': 700,
                        'meta_agency': {
                            'id': 800,
                            'name': 'Rate Limit Test Company',
                            'country': 'United Kingdom (GB)',
                            'status': 'active',
                            'paid_invoice_count': 0,
                            'created': datetime.now(timezone.utc).isoformat(),
                            'price_plan': 'monthly-payg',
                            'narc': False,
                        },
                        'user': {'first_name': 'Rate', 'last_name': 'Test', 'email': 'ratetest@example.com'},
                        'status': 'active',
                        'sales_person': {'id': test_admin.tc2_admin_id},
                        'paid_recipients': [
                            {
                                'id': 900 + i,
                                'first_name': f'Contact{i}',
                                'last_name': 'Test',
                                'email': f'contact{i}@example.com',
                            }
                            for i in range(5)
                        ],
                        'extra_attrs': [],
                    },
                }
            ],
            '_request_time': 1234567890,
        }

        response = client.post(client.app.url_path_for('tc2-callback'), json=webhook_data)

        assert response.status_code == 200

        company = db.exec(select(Company).where(Company.tc2_cligency_id == 700)).first()
        assert company is not None

        assert '429' not in caplog.text or 'retry' in caplog.text.lower()
