from typing import Callable, Union

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
    This function, `prepare_event_data`, processes the event data by handling custom fields 'hermes_id' and
    'signup_questionnaire'.
    For 'hermes_id', it retrieves all the pd_field_ids and checks if the previous value is a
    string. If it is, it calls the function `handle_duplicate_hermes_ids` to handle any duplicate hermes_id.
    For 'signup_questionnaire', it retrieves all the pd_field_ids and checks if the current and previous values are
    different. If they are, it sets the current value back to the previous value.
    """

    async def handle_custom_field(data: dict, field_name: str, handle_func: Union[Callable, str] = None):
        cf_fields = await CustomField.filter(machine_name=field_name).values_list('pd_field_id', flat=True)
        for pd_field_id in cf_fields:
            for state in [PDStatus.PREVIOUS, PDStatus.CURRENT]:
                if data.get(state) and pd_field_id in data[state] and isinstance(data[state][pd_field_id], str):
                    if handle_func == 'revert changes':
                        if state == PDStatus.PREVIOUS:
                            data[PDStatus.CURRENT][pd_field_id] = data[PDStatus.PREVIOUS][pd_field_id]

                    if callable(handle_func):
                        data[state][pd_field_id] = await handle_func(data[state][pd_field_id], data['meta']['object'])
        return data

    event_data = await handle_custom_field(event_data, 'hermes_id', handle_duplicate_hermes_ids)
    event_data = await handle_custom_field(event_data, 'signup_questionnaire', 'revert changes')
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
