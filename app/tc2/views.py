import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header

from app.core.config import settings
from app.core.database import DBSession, get_db
from app.pipedrive.tasks import purge_company_from_pipedrive, sync_company_to_pipedrive
from app.tc2.models import TCClient, TCWebhook
from app.tc2.process import process_tc_client

logger = logging.getLogger('hermes.tc2')

router = APIRouter()


@router.post('/callback/', name='tc2-callback')
async def tc2_callback(
    webhook: TCWebhook,
    background_tasks: BackgroundTasks,
    db: DBSession = Depends(get_db),
    webhook_signature: Optional[str] = Header(None, alias='X-Webhook-Signature'),
):
    """
    Process TC2 webhooks: TC2 → Hermes → Pipedrive

    Handles Client and Invoice events from TutorCruncher.
    """
    # Verify HMAC signature (skip in dev mode)
    if not settings.dev_mode:
        # TODO: Get request body for signature verification
        # For now, we'll skip this but it should be implemented
        pass

    for event in webhook.events:
        if event.subject.model == 'Client':
            if event.action == 'AGREE_TERMS':
                logger.info('Ignoring AGREE_TERMS event')
                continue

            try:
                # Process the client (creates/updates Company and Contacts)
                company = await process_tc_client(TCClient(**event.subject.model_dump()), db)

                if company:
                    # Queue background task to sync to Pipedrive
                    if company.narc:
                        # NARC companies are deleted/purged from Pipedrive
                        background_tasks.add_task(purge_company_from_pipedrive, company.id)
                    else:
                        background_tasks.add_task(sync_company_to_pipedrive, company.id)

            except Exception as e:
                logger.error(f'Error processing TC2 client event: {e}', exc_info=True)

        else:
            logger.info(f'Ignoring event with subject model {event.subject.model}')

    return {'status': 'ok'}
