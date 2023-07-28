from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.tc2._process import update_from_client_event, update_from_invoice_event
from app.tc2._schema import TCWebhook
from app.tc2._utils import app_logger
from app.utils import get_bearer, settings

tc2_router = APIRouter()


@tc2_router.post('/callback/', name='TC2 callback')
async def callback(webhook: TCWebhook, Authorization: Optional[str] = Header(None)):
    """
    Callback for TC2
    Updates Hermes and other systems based on events in TC2.
    """
    # TODO: Check less than 1 paying invoice
    # TODO: Add created and check that
    # TODO: Do callback to Pipedrive
    if not get_bearer(Authorization) == settings.tc2_api_key:
        raise HTTPException(status_code=403, detail='Unauthorized key')
    for event in webhook.events:
        if event.subject.model == 'Client':
            await update_from_client_event(event.subject)
        elif event.subject.model == 'Invoice':
            await update_from_invoice_event(event.subject)
        else:
            app_logger.info('Ignoring event with subject model %s', event.subject.model)
    return {'status': 'ok'}
