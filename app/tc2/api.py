import requests

session = requests.Session()


async def tc2_request(url: str, *, method: str = 'GET', data: dict = None) -> dict:
    from ..main import settings

    headers = {'Authorization': f'token {settings.tc2_api_key}'}
    r = session.request(method=method, url=f'{settings.tc2_api_url}/{url}', data=data, headers=headers)
    r.raise_for_status()
    return r.json()
