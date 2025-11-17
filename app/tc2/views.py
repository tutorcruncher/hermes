import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header
from sqlmodel import select

from app.core.config import settings
from app.core.database import get_session
from app.main_app.models import Admin, Company
from app.pipedrive.tasks import purge_company_from_pipedrive, sync_company_to_pipedrive
from app.tc2.models import TCClient, TCWebhook
from app.tc2.process import process_tc_client

logger = logging.getLogger('hermes.tc2')

router = APIRouter(prefix='/tc2', tags=['tc2'])


def _prefetch_webhook_data(webhook: TCWebhook) -> tuple[dict[int, Company], dict[int, Admin]]:
    """
    Pre-fetch all companies and admins needed for webhook processing.
    Returns lookup dictionaries keyed by TC2 IDs.
    """
    tc2_cligency_ids = set()
    tc2_admin_ids = set()

    for event in webhook.events:
        if event.subject.model == 'Client' and event.action != 'AGREE_TERMS':
            client = TCClient(**event.subject.model_dump())
            tc2_cligency_ids.add(client.id)
            if client.sales_person_id:
                tc2_admin_ids.add(client.sales_person_id)
            if client.associated_admin_id:
                tc2_admin_ids.add(client.associated_admin_id)
            if client.bdr_person_id:
                tc2_admin_ids.add(client.bdr_person_id)

    with get_session() as db:
        companies = db.exec(select(Company).where(Company.tc2_cligency_id.in_(tc2_cligency_ids))).all()
        admins = db.exec(select(Admin).where(Admin.tc2_admin_id.in_(tc2_admin_ids))).all()

    prefetched_companies = {c.tc2_cligency_id: c for c in companies}
    prefetched_admins = {a.tc2_admin_id: a for a in admins}

    return prefetched_companies, prefetched_admins


@router.post('/callback/', name='tc2-callback')
async def tc2_callback(
    webhook: TCWebhook,
    background_tasks: BackgroundTasks,
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

    prefetched_companies, prefetched_admins = _prefetch_webhook_data(webhook)

    for event in webhook.events:
        if event.subject.model == 'Client':
            if event.action == 'AGREE_TERMS':
                logger.info('Ignoring AGREE_TERMS event')
                continue

            try:
                # Process the client (creates/updates Company and Contacts)
                with get_session() as db:
                    company = await process_tc_client(
                        TCClient(**event.subject.model_dump()),
                        db,
                        prefetched_companies=prefetched_companies,
                        prefetched_admins=prefetched_admins,
                    )

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
