import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_callback_invalid_api_key(client: AsyncClient):
    r = await client.post(
        '/callback/tc2/', headers={'Authorization': 'Bearer 999'}, json={'_request_time': 123, 'events': []}
    )
    assert r.status_code == 403, r.json()


@pytest.mark.anyio
async def test_callback_missing_api_key(client: AsyncClient):
    r = await client.post('/callback/tc2/', json={'_request_time': 123, 'events': []})
    assert r.status_code == 403, r.json()


CLIENT_FULL_EVENT_DATA = {
    'action': 'create',
    'verb': 'create',
    'subject': {
        'model': 'Client',
        'meta_agency': {
            'id': 11,
            'name': 'MyTutors',
            'website': 'www.example.com',
            'status': 'active',
            'paid_invoice_count': 12,
        },
        'associated_admin': {
            'id': 22,
            'first_name': 'Brain',
            'last_name': 'Johnson',
            'email': 'brian@tc.com',
        },
    },
}


async def test_cb_client_event_test_1():
    """
    Create a new company
    Create no contacts
    """
    event = {'action': 'create', 'verb': 'create', 'subject': {'model': 'Client', 'meta_agency': {}}}
    r = await client.post('/callback/tc2/', json={'_request_time': 123, 'events': []})


async def test_cb_client_event_test_2():
    """
    Create a new company
    Create new contacts
    With associated admin
    """
    pass


async def test_cb_client_event_test_3():
    """
    Update a current company
    Create no contacts
    Without associated admin
    """
    pass


async def test_cb_client_event_test_4():
    """
    Update a current company
    Create new contacts
    With invalid associated admin
    """
    pass


async def test_cb_client_event_test_5():
    """
    Update a current company
    Update contacts
    """
    pass


async def test_cb_client_deleted_test_1():
    """
    Company deleted, has no contacts
    """
    pass


async def test_cb_client_deleted_test_2():
    """
    Company deleted, has contacts, deals and meetings
    """
    pass


async def test_cb_invoice_event_update_client():
    """
    Processing an invoice event means we get the client from TC.
    """
    pass


async def test_cb_invoice_event_tc_request_error():
    """
    Processing an invoice event means we get the client from TC. Testing an error.
    """
    pass
