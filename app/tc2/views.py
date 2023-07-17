from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.settings import Settings
from app.tc2._process import process_tc2_client, update_from_invoice_event
from app.tc2._schema import TCClient, TCWebhook
from app.tc2._utils import app_logger
from app.utils import get_bearer

tc2_router = APIRouter()
settings = Settings()


@tc2_router.post('/callback/', name='TC2 callback')
async def callback(webhook: TCWebhook, Authorization: Optional[str] = Header(None)):
    """
    Callback for TC2
    Updates Hermes and other systems based on events in TC2.
    """
    # TODO: Check less than 1 paying invoice
    # TODO: Add created and check that
    if not get_bearer(Authorization) == settings.tc2_api_key:
        raise HTTPException(status_code=403, detail='Unauthorized key')
    for event in webhook.events:
        if event.subject.model == 'Client':
            await process_tc2_client(event.subject)
        elif event.subject.model == 'Invoice':
            await update_from_invoice_event(event.subject)
        else:
            app_logger.info('Ignoring event with subject model %s', event.subject.model)
    return {'status': 'ok'}


@tc2_router.post('/companies/create/', name='Create company from TC2')
async def create_company(client: TCClient, Authorization: Optional[str] = Header(None)):
    """
    Gets or creates a company from TC2 data.
    """
    if not get_bearer(Authorization) == settings.tc2_api_key:
        raise HTTPException(status_code=403, detail='Unauthorized key')
    company = await process_tc2_client(client)
    return {'status': 'ok', 'company': company}
