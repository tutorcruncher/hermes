import hashlib
import hmac
from secrets import compare_digest
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from starlette.background import BackgroundTasks
from starlette.requests import Request

from app.pipedrive.tasks import pd_post_process_client_event, pd_post_purge_client_event
from app.tc2._process import update_from_client_event, update_from_invoice_event
from app.tc2._schema import TCWebhook
from app.tc2._utils import app_logger
from app.utils import settings

tc2_router = APIRouter()


@tc2_router.post('/callback/', name='TC2 callback')
async def callback(
    request: Request, webhook: TCWebhook, webhook_signature: Optional[str] = Header(None), tasks: BackgroundTasks = None
):
    """
    Callback for TC2
    Updates Hermes and other systems based on events in TC2.
    """
    expected_sig = hmac.new(settings.tc2_api_key.encode(), (await request.body()), hashlib.sha256).hexdigest()
    if not webhook_signature or not compare_digest(webhook_signature, expected_sig):
        raise HTTPException(status_code=403, detail='Unauthorized key')
    for event in webhook.events:
        company, deal = None, None
        if event.subject.model == 'Client':
            company, deal = await update_from_client_event(event.subject)
        elif event.subject.model == 'Invoice':
            company, deal = await update_from_invoice_event(event.subject)
        else:
            app_logger.info('Ignoring event with subject model %s', event.subject.model)
        if company:
            if company.narc:
                tasks.add_task(pd_post_purge_client_event, company, deal)
            else:
                tasks.add_task(pd_post_process_client_event, company, deal)


    return {'status': 'ok'}
