import requests

from app.tc2._utils import app_logger
from app.utils import settings

session = requests.Session()


async def tc2_request(url: str, *, method: str = 'GET', data: dict = None) -> dict:
    headers = {
        'Authorization': f'token {settings.tc2_api_key}',
        'Content-Type': 'application/json'
    }
    r = session.request(method=method, url=f'{settings.tc2_base_url}/api/{url}', json=data, headers=headers)
    app_logger.info('Request method=%s url=%s status_code=%s', method, url, r.status_code, extra={'data': data})
    r.raise_for_status()
    return r.json()

