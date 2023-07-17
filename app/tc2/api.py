import requests

from app.models import Contacts, Deals

session = requests.Session()


async def tc2_request(url: str, *, method: str = 'GET', data: dict = None) -> dict:
    from ..main import settings

    headers = {'Authorization': f'token {settings.tc2_api_key}'}
    r = session.request(method=method, url=f'{settings.tc2_api_url}/api/{url}', data=data, headers=headers)
    r.raise_for_status()
    return r.json()


async def update_client_from_deal(deal: Deals):
    pass
