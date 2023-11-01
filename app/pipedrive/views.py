from fastapi import APIRouter
from starlette.background import BackgroundTasks

from app.pipedrive._process import (
    _process_pd_deal,
    _process_pd_organisation,
    _process_pd_person,
    _process_pd_pipeline,
    _process_pd_stage,
)
from app.pipedrive._schema import PipedriveEvent
from app.pipedrive._utils import app_logger
from app.tc2.tasks import update_client_from_company

pipedrive_router = APIRouter()


@pipedrive_router.post('/callback/', name='Pipedrive callback')
async def callback(event: PipedriveEvent, tasks: BackgroundTasks):
    """
    Processes a Pipedrive event. If a Deal is updated then we run a background task to update the cligency in Pipedrive
    """
    event.current and await event.current.a_validate()
    event.previous and await event.previous.a_validate()
    app_logger.info(f'Callback: event received for {event.meta.object}: {event}')
    if event.meta.object == 'deal':
        deal = await _process_pd_deal(event.current, event.previous)
        company = await deal.company
        if company.tc2_agency_id:
            # We only update the client if the deal has a company with a tc2_agency_id
            tasks.add_task(update_client_from_company, company)
    elif event.meta.object == 'pipeline':
        await _process_pd_pipeline(event.current, event.previous)
    elif event.meta.object == 'stage':
        await _process_pd_stage(event.current, event.previous)
    elif event.meta.object == 'person':
        await _process_pd_person(event.current, event.previous)
    elif event.meta.object == 'organization':
        company = await _process_pd_organisation(event.current, event.previous)
        if company and company.tc2_agency_id:
            # We only update the client if the deal has a company with a tc2_agency_id
            tasks.add_task(update_client_from_company, company)
    return {'status': 'ok'}
