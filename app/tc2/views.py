from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from app.settings import Settings
from app.tc2._process import update_from_client_event, update_from_invoice_event
from app.tc2._schema import TCWebhook
from app.tc2._utils import app_logger

tc2_router = APIRouter()
settings = Settings()


def get_bearer(auth: str):
    try:
        return auth.split(' ')[1]
    except (AttributeError, IndexError):
        return


@tc2_router.post('/callback/tc2/', name='TC2 callback')
async def tc_callback(webhook: TCWebhook, Authorization: Optional[str] = Header(None)):
    """
    Callback for TC2
    Updates Hermes and Hubspot based on events in TC2.
    These options are seen in EVENT_DEAL_STAGE_LU in hubspot.py
    """
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
