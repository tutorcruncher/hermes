import logging
import time
from typing import Optional

import httpx
import logfire

from app.core.config import settings

logger = logging.getLogger('hermes.tc2')

max_retries = 5


async def tc2_request(url: str, *, method: str = 'GET', data: Optional[dict] = None, retry: int = 1) -> dict:
    """
    Make a request to the TutorCruncher API with retry logic for rate limits.

    Args:
        url: API endpoint (without /api/ prefix)
        method: HTTP method (GET, POST, PUT, DELETE)
        data: Request body data
        retry: Internal retry counter (starts at 1, max 5)

    Returns:
        Response JSON data
    """
    headers = {'Authorization': f'token {settings.tc2_api_key}', 'Content-Type': 'application/json'}
    full_url = f'{settings.tc2_base_url}/api/{url}'

    with logfire.span(f'{method} {url}'):
        async with httpx.AsyncClient() as client:
            response = await client.request(method=method, url=full_url, json=data, headers=headers, timeout=30.0)
            logger.info(f'Request method={method} url={url} status_code={response.status_code}')
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429 and retry < max_retries:
                    wait_time = retry * 2
                    logger.warning(
                        f'TC2 API rate limit (429) for {method} {url}, '
                        f'attempt {retry}/{max_retries}, waiting {wait_time}s...'
                    )
                    time.sleep(wait_time)
                    return await tc2_request(url, method=method, data=data, retry=retry + 1)
                else:
                    try:
                        error_data = e.response.json()
                    except Exception:
                        error_data = e.response.text
                    logger.error(f'TC2 API error: {e}. Response: {error_data}')
                    raise
            return response.json()


async def get_client(tc2_cligency_id: int) -> dict:
    """Get client data from TutorCruncher"""
    return await tc2_request(f'clients/{tc2_cligency_id}/')
