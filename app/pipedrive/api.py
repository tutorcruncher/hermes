import asyncio
import logging
from typing import Optional

import httpx
import logfire
from httpx_limiter import AsyncRateLimitedTransport, Rate

from app.core.config import settings

logger = logging.getLogger('hermes.pipedrive')

_transport = AsyncRateLimitedTransport.create(
    Rate.create(magnitude=settings.pd_api_max_rate, duration=settings.pd_api_rate_period)
)
_client = httpx.AsyncClient(
    transport=_transport
)  # need to use a singleton client to keep the rate limiting throughout all the requests.

RATE_LIMIT_STATUS_CODE = 429


def _extract_rate_limit_headers(response: httpx.Response) -> dict:
    return {
        'limit': response.headers.get('x-ratelimit-limit'),
        'remaining': response.headers.get('x-ratelimit-remaining'),
        'reset': response.headers.get('x-ratelimit-reset'),
        'daily_left': response.headers.get('x-daily-requests-left'),
    }


async def pipedrive_request(
    endpoint: str,
    *,
    method: str = 'GET',
    query_params: Optional[dict] = None,
    data: Optional[dict] = None,
    retry: int = 0,
) -> dict:
    """
    Make a request to the Pipedrive API v2.

    Args:
        endpoint: The API endpoint (without /v2/ prefix)
        method: HTTP method (GET, POST, PATCH, DELETE)
        query_params: Query parameters dict
        data: Request body data
        retry: Internal retry counter

    Returns:
        Response JSON data
    """
    url = f'{settings.pd_base_url}/api/v2/{endpoint}'
    headers = {'x-api-token': settings.pd_api_key, 'Content-Type': 'application/json', 'Accept': 'application/json'}

    with logfire.span(f'{method} {endpoint}'):
        response = await _client.request(
            method=method, uzrl=url, headers=headers, params=query_params, json=data, timeout=30.0
        )
        rate_limit_info = _extract_rate_limit_headers(response)
        logger.info(
            f'Request method={method} url={endpoint} status_code={response.status_code} '
            f'rate_limit={rate_limit_info["remaining"]}/{rate_limit_info["limit"]} '
            f'daily_left={rate_limit_info["daily_left"]}'
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if (
                settings.pd_api_enable_retry
                and e.response.status_code == RATE_LIMIT_STATUS_CODE
                and retry < settings.pd_api_max_retry
            ):
                wait_time = (retry + 1) * 2
                logger.warning(
                    f'Pipedrive API rate limit for {method} {endpoint}, retry {retry + 1}/3, waiting {wait_time}s...'
                )
                await asyncio.sleep(wait_time)
                return await pipedrive_request(
                    endpoint, method=method, query_params=query_params, data=data, retry=retry + 1
                )
            else:
                try:
                    error_data = response.json()
                except Exception:
                    error_data = response.text
                logger.error(f'Pipedrive API error: {e}. Response: {error_data}')
                raise
        return response.json()


async def create_organisation(org_data: dict) -> dict:
    """Create organization in Pipedrive using v2 API"""
    return await pipedrive_request('organizations', method='POST', data=org_data)


async def update_organisation(org_id: int, changed_fields: dict) -> dict:
    """
    Update organization using PATCH (v2 API).
    Only send changed fields to minimize conflicts.
    """
    return await pipedrive_request(f'organizations/{org_id}', method='PATCH', data=changed_fields)


async def get_organisation(org_id: int) -> dict:
    """Get organization from Pipedrive"""
    return await pipedrive_request(f'organizations/{org_id}', method='GET')


async def delete_organisation(org_id: int) -> dict:
    """Delete organization from Pipedrive"""
    return await pipedrive_request(f'organizations/{org_id}', method='DELETE')


async def create_person(person_data: dict) -> dict:
    """Create person in Pipedrive using v2 API"""
    return await pipedrive_request('persons', method='POST', data=person_data)


async def update_person(person_id: int, changed_fields: dict) -> dict:
    """Update person using PATCH"""
    return await pipedrive_request(f'persons/{person_id}', method='PATCH', data=changed_fields)


async def get_person(person_id: int) -> dict:
    """Get person from Pipedrive"""
    return await pipedrive_request(f'persons/{person_id}', method='GET')


async def create_deal(deal_data: dict) -> dict:
    """Create deal in Pipedrive using v2 API"""
    return await pipedrive_request('deals', method='POST', data=deal_data)


async def update_deal(deal_id: int, changed_fields: dict) -> dict:
    """Update deal using PATCH"""
    return await pipedrive_request(f'deals/{deal_id}', method='PATCH', data=changed_fields)


async def get_deal(deal_id: int) -> dict:
    """Get deal from Pipedrive"""
    return await pipedrive_request(f'deals/{deal_id}', method='GET')


async def create_activity(activity_data: dict) -> dict:
    """Create activity in Pipedrive"""
    return await pipedrive_request('activities', method='POST', data=activity_data)


def get_changed_fields(old_data: Optional[dict], new_data: dict) -> dict:
    """
    Compare old and new data to find changed fields.
    Used for PATCH requests to only send changed fields.

    Args:
        old_data: Original data from Pipedrive (None if creating new)
        new_data: New data to send

    Returns:
        Dict containing only changed fields
    """
    if old_data is None:
        return new_data

    changed = {}
    for key, new_value in new_data.items():
        old_value = old_data.get(key)
        if old_value != new_value:
            changed[key] = new_value

    return changed
