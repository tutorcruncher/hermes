import time

import logfire
import requests
from requests import HTTPError
from tortoise.exceptions import DoesNotExist

from app.models import Company
from app.tc2._schema import TCClient
from app.tc2._utils import app_logger
from app.utils import settings

session = requests.Session()
max_retries = 5


async def tc2_request(url: str, *, method: str = 'GET', data: dict = None, retry: int = 1) -> dict:
    """
    Make a request to the TutorCruncher API with retry logic for rate limits.
    @param url: desired endpoint
    @param method: GET, POST, PUT, DELETE
    @param data: data to send in the request body
    @param retry: internal retry counter (starts at 1, max 5)
    @return: json response
    """
    headers = {'Authorization': f'token {settings.tc2_api_key}', 'Content-Type': 'application/json'}
    app_logger.debug('TutorCruncher request to url: {url=}: {data=}', url=url, data=data)
    with logfire.span('{method} {url!r}', url=url, method=method):
        r = session.request(method=method, url=f'{settings.tc2_base_url}/api/{url}', json=data, headers=headers)
    app_logger.info('Request method=%s url=%s status_code=%s', method, url, r.status_code, extra={'data': data})

    try:
        r.raise_for_status()
        return r.json()
    except HTTPError as e:
        if r.status_code == 429 and retry < max_retries:
            wait_time = retry * 2
            app_logger.warning(
                f'TC2 API rate limit (429) for {method} {url}, attempt {retry}/{max_retries}, waiting {wait_time}s...'
            )
            time.sleep(wait_time)
            return await tc2_request(url, method=method, data=data, retry=retry + 1)
        else:
            raise e


async def get_or_create_company(tc2_cligency_id: int) -> Company:
    """
    Gets or creates a client in TutorCruncher.
    """
    from app.tc2._process import update_from_client_event

    try:
        company = await Company.get(tc2_cligency_id=tc2_cligency_id)
    except DoesNotExist:
        # If the company does not exist, create it
        tc_client_data = await tc2_request(f'clients/{tc2_cligency_id}/')
        # Format the data to match the TCSubject model
        tc_client = TCClient(**tc_client_data)

        # Create the Company the same way we would if it was a webhook
        company, _ = await update_from_client_event(tc_client, create_deal=False)
    return company
