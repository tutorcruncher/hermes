import hashlib
import hmac
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.database import get_session
from app.core.locks import RedisLockRegistry
from app.pipedrive.tasks import purge_company_from_pipedrive, sync_company_to_pipedrive
from app.tc2.models import TCClient, TCWebhook
from app.tc2.process import process_tc_client

logger = logging.getLogger('hermes.tc2')

router = APIRouter(prefix='/tc2', tags=['tc2'])

# Per-cligency lock to serialise concurrent webhook processing for the same TC2 client.
# Prevents duplicate Hermes Deal rows when CREATED_A_CLIENT and EDITED_A_CLIENT
# arrive as near-simultaneous separate requests from TC2 batched webhooks.
_cligency_locks = RedisLockRegistry('hermes:cligency-lck', lease_timeout_seconds=10, blocking_timeout_seconds=10)

# The fields of TC2's short Client payload (ClientSimpleSerializer, plus model/url/is_deleted added by the webhook),
# which TC2 sends for clients outside its detail queryset: deleted users, including deletes, and admin users.
_SHORT_CLIENT_FIELDS = {'model', 'url', 'id', 'first_name', 'last_name', 'email', 'role_type', 'is_deleted'}


@router.post('/callback/', name='tc2-callback')
async def tc2_callback(
    request: Request,
    webhook: TCWebhook,
    background_tasks: BackgroundTasks,
    webhook_signature: Optional[str] = Header(None),
):
    """
    Process TC2 webhooks: TC2 → Hermes → Pipedrive

    Handles Client and Invoice events from TutorCruncher.
    """
    # TC2 sends its webhooks through Chronos, which signs the exact body it sends with the TC2 API key
    if not settings.dev_mode:
        expected_sig = hmac.new(settings.tc2_api_key.encode(), await request.body(), hashlib.sha256).hexdigest()
        # Encoded because compare_digest raises TypeError on a non-ASCII str
        if not webhook_signature or not hmac.compare_digest(webhook_signature.encode(), expected_sig.encode()):
            logger.warning('Rejected a TC2 webhook with an invalid signature')
            return JSONResponse({'status': 'error', 'message': 'Unauthorized'}, status_code=403)

    for event in webhook.events:
        if event.subject.model == 'Client':
            if event.action == 'AGREE_TERMS':
                logger.info('Ignoring AGREE_TERMS event')
                continue

            subject = event.subject.model_dump()
            # Enquiries have meta_agency null, and short payloads have no agency data. Any other payload without
            # meta_agency must still fail validation below, so a TC2 contract break is logged as an error.
            if ('meta_agency' in subject and subject['meta_agency'] is None) or subject.keys() <= _SHORT_CLIENT_FIELDS:
                logger.info(f'Ignoring {event.action} for client {event.subject.id} as it has no meta_agency')
                continue

            try:
                async with _cligency_locks.acquire(event.subject.id):
                    # Process the client (creates/updates Company and Contacts)
                    with get_session() as db:
                        company = await process_tc_client(TCClient(**subject), db)

                    if company:
                        # Queue background task to sync to Pipedrive
                        if company.narc:
                            background_tasks.add_task(purge_company_from_pipedrive, company.id)
                        else:
                            background_tasks.add_task(sync_company_to_pipedrive, company.id)

            except Exception as e:
                logger.error(f'Error processing TC2 client event: {e}', exc_info=True)

        else:
            logger.info(f'Ignoring event with subject model {event.subject.model}')

    return {'status': 'ok'}
