from fastapi import APIRouter, HTTPException
from starlette.background import BackgroundTasks

from app.pipedrive._process import (
    _process_pd_deal,
    _process_pd_pipeline,
    _process_pd_stage,
    _process_pd_person,
    _process_pd_organisation,
)
from app.pipedrive._schema import PipedriveEvent
from app.pipedrive._utils import app_logger
from app.tc2.tasks import update_client_from_company

pipedrive_router = APIRouter()


@pipedrive_router.post('/callback/', name='Pipedrive callback')
async def callback(event: PipedriveEvent, tasks: BackgroundTasks):
    try:
        debug('pipedrive callback')
        debug(event)
        debug(event.meta)
        event.current and await event.current.a_validate()
        event.previous and await event.previous.a_validate()

        app_logger.info(f'Callback: event received for {event.meta.object}')
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
            debug(company.__dict__)
            if company and company.tc2_agency_id:
                # We only update the client if the deal has a company with a tc2_agency_id
                tasks.add_task(update_client_from_company, company)
        return {'status': 'ok'}

    except HTTPException as http_exception:
        if http_exception.status_code == 422:
            response_data = await http_exception.detail.json()
            raise HTTPException(
                status_code=422,
                detail=f"Unprocessable Entity: {response_data}",
            )


@pipedrive_router.post('/debug_callback/', name='Pipedrive debug callback')
async def debug_callback(event: PipedriveEvent, tasks: BackgroundTasks):
    app_logger.info(f'Debug: event received for {event.meta.object}')
    if event.meta.object == 'deal':
        if event.current:
            await event.current.a_validate()
        if event.previous:
            await event.previous.a_validate()

        deal = await _process_pd_deal(event.current, event.previous)
        if deal:
            company = await deal.company
            if company and company.tc2_agency_id:
                tasks.add_task(update_client_from_company, company)
    elif event.meta.object == 'pipeline':
        if event.current:
            await event.current.a_validate()
        if event.previous:
            await event.previous.a_validate()

        await _process_pd_pipeline(event.current, event.previous)
    elif event.meta.object == 'stage':
        if event.current:
            await event.current.a_validate()
        if event.previous:
            await event.previous.a_validate()

        await _process_pd_stage(event.current, event.previous)
    elif event.meta.object == 'person':
        if event.current:
            await event.current.a_validate()
        if event.previous:
            await event.previous.a_validate()

        await _process_pd_person(event.current, event.previous)
    elif event.meta.object == 'organization':
        if event.current:
            await event.current.a_validate()
        if event.previous:
            await event.previous.a_validate()

        company = await _process_pd_organisation(event.current, event.previous)
        if company and company.tc2_agency_id:
            tasks.add_task(update_client_from_company, company)

    response_data = {
        "meta": event.meta,
        "current": event.current.dict() if event.current else None,
        "previous": event.previous.dict() if event.previous else None
    }
    await debug_log(response_data)
    return {'status': 'ok'}


@pipedrive_router.post('/debug_log/', name='debug log')
async def debug_log(event_data: dict):
    app_logger.info("Captured event data for debugging:")
    debug(event_data)
    # app_logger.info(event_data)
    return {'status': 'ok'}
