from fastapi import APIRouter
from starlette.background import BackgroundTasks
from starlette.requests import Request

from app.pipedrive._process import (
    _process_pd_deal,
    _process_pd_pipeline,
    _process_pd_stage,
    _process_pd_person,
    _process_pd_organisation,
)
from app.pipedrive._schema import PipedriveEvent
from app.pipedrive._utils import app_logger
from app.tc2.tasks import update_client_from_deal

pipedrive_router = APIRouter()


@pipedrive_router.post('/callback/', name='Pipedrive callback')
async def callback(request: Request, tasks: BackgroundTasks):
    """
    Processes a Pipedrive event. If a Deal is updated then we run a background task to update the cligency in Pipedrive
    """
    try:
        event = PipedriveEvent(**await request.json())
    except Exception as e:
        app_logger.exception(e)
        raise
    # event.current and await event.current.a_validate()
    # event.previous and await event.previous.a_validate()
    app_logger.info(f'Callback: event received for {event.meta.object}')
    if event.meta.object == 'deal':
        deal = await _process_pd_deal(event.current, event.previous)
        if deal and (await deal.company).tc2_agency_id:
            # We only update the client if the deal has a company with a tc2_agency_id
            tasks.add_task(update_client_from_deal, deal)
    elif event.meta.object == 'pipeline':
        await _process_pd_pipeline(event.current, event.previous)
    elif event.meta.object == 'stage':
        await _process_pd_stage(event.current, event.previous)
    elif event.meta.object == 'person':
        await _process_pd_person(event.current, event.previous)
    elif event.meta.object == 'organization':
        await _process_pd_organisation(event.current, event.previous)
    return {'status': 'ok'}
