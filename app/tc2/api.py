import logfire
import requests
from tortoise.exceptions import DoesNotExist

from app.models import Company
from app.tc2._schema import TCClient
from app.tc2._utils import app_logger
from app.utils import settings

session = requests.Session()


async def tc2_request(url: str, *, method: str = 'GET', data: dict = None) -> dict:
    headers = {'Authorization': f'token {settings.tc2_api_key}', 'Content-Type': 'application/json'}
    logfire.debug('TutorCruncher request to url: {url=}: {data=}', url=url, data=data)
    r = session.request(method=method, url=f'{settings.tc2_base_url}/api/{url}', json=data, headers=headers)
    app_logger.info('Request method=%s url=%s status_code=%s', method, url, r.status_code, extra={'data': data})
    logfire.debug(
        'TutorCruncher request method={method=} url={url=} status_code={status_code=}',
        method=method,
        url=url,
        status_code=r.status_code,
    )
    r.raise_for_status()
    return r.json()


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
