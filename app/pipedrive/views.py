from fastapi import APIRouter
from starlette.background import BackgroundTasks

from app.models import CustomField
from app.pipedrive._process import (
    _process_pd_deal,
    _process_pd_organisation,
    _process_pd_person,
    _process_pd_pipeline,
    _process_pd_stage,
)
from app.pipedrive._schema import PDObjectNames, PDStatus, PipedriveEvent, handle_duplicate_hermes_ids
from app.pipedrive._utils import app_logger
from app.tc2.tasks import update_client_from_company

pipedrive_router = APIRouter()


async def prepare_event_data(event_data: dict) -> dict:
    """
    This function retrieves all the pd_field_ids for the custom field 'hermes_id' and then checks if the previous value
    is a string. If it is, it calls handle_duplicate_hermes_ids to handle the duplicate hermes_id.
    """
    hermes_id_cf_fields = await CustomField.filter(machine_name='hermes_id').values_list('pd_field_id', flat=True)
    for hermes_id_pd_field_id in hermes_id_cf_fields:
        for state in [PDStatus.PREVIOUS.value, PDStatus.CURRENT.value]:
            if (
                event_data.get(state)
                and hermes_id_pd_field_id in event_data[state]
                and isinstance(event_data[state][hermes_id_pd_field_id], str)
            ):
                event_data[state][hermes_id_pd_field_id] = await handle_duplicate_hermes_ids(
                    event_data[state][hermes_id_pd_field_id], event_data['meta']['object']
                )

    return event_data


@pipedrive_router.post('/callback/', name='Pipedrive callback')
async def callback(event: dict, tasks: BackgroundTasks):
    """
    Processes a Pipedrive event. If a Deal is updated then we run a background task to update the cligency in Pipedrive
    TODO: This has 0 security, we should add some.
    """
    event_data = await prepare_event_data(event)
    event_instance = PipedriveEvent(**event_data)

    event_instance.current and await event_instance.current.a_validate()
    event_instance.previous and await event_instance.previous.a_validate()

    app_logger.info(f'Callback: event_instance received for {event_instance.meta.object}: {event_instance}')
    if event_instance.meta.object == 'deal':
        deal = await _process_pd_deal(event_instance.current, event_instance.previous)
        company = await deal.company
        if company.tc2_agency_id:
            # We only update the client if the deal has a company with a tc2_agency_id
            tasks.add_task(update_client_from_company, company)
    elif event_instance.meta.object == PDObjectNames.PIPELINE:
        await _process_pd_pipeline(event_instance.current, event_instance.previous)
    elif event_instance.meta.object == PDObjectNames.STAGE:
        await _process_pd_stage(event_instance.current, event_instance.previous)
    elif event_instance.meta.object == PDObjectNames.PERSON:
        await _process_pd_person(event_instance.current, event_instance.previous)
    elif event_instance.meta.object == PDObjectNames.ORGANISATION:
        company = await _process_pd_organisation(event_instance.current, event_instance.previous)
        if company and company.tc2_agency_id:
            # We only update the client if the deal has a company with a tc2_agency_id
            tasks.add_task(update_client_from_company, company)
    return {'status': 'ok'}
