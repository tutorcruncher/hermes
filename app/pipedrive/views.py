from typing import Callable, Union

from fastapi import APIRouter
from starlette.background import BackgroundTasks

from app.models import CustomField
from app.tc2.tasks import update_client_from_company

from ._process import process_pd_deal, process_pd_organisation, process_pd_person, process_pd_pipeline, process_pd_stage
from ._schema import PDObjectNames, PDStatus, PipedriveEvent
from ._utils import app_logger

pipedrive_router = APIRouter()


async def prepare_event_data(event_data: dict) -> dict:
    """
    Processes webhooks v2 event data by flattening custom fields and handling special field logic.

    Custom fields in v2 come as objects with 'type' and 'value'/'id' keys.
    We flatten these into the main data object for easier processing.
    """
    # Handle webhooks v2 custom fields format: flatten custom_fields object into main object
    for state in [PDStatus.DATA, PDStatus.PREVIOUS]:
        if event_data.get(state) and isinstance(event_data[state], dict):
            custom_fields = event_data[state].pop('custom_fields', None)
            if custom_fields:
                # In v2, custom fields are objects with 'type' and 'value' or 'id' keys
                # We need to extract just the value and flatten into the main object
                flattened_fields = {}
                for field_id, field_data in custom_fields.items():
                    if field_data is None:
                        flattened_fields[field_id] = None
                    elif isinstance(field_data, dict):
                        # Extract 'value' or 'id' depending on the field type
                        if 'value' in field_data:
                            flattened_fields[field_id] = field_data['value']
                        elif 'id' in field_data:
                            flattened_fields[field_id] = field_data['id']
                    else:
                        # Fallback for unexpected formats
                        flattened_fields[field_id] = field_data
                event_data[state].update(flattened_fields)

    # Skip custom field processing for deletion events (where data is None)
    if not event_data.get(PDStatus.DATA):
        return event_data

    async def handle_custom_field(data: dict, field_name: str, handle_func: Union[Callable, str] = None):
        cf_fields = await CustomField.filter(machine_name=field_name).values_list('pd_field_id', flat=True)
        for pd_field_id in cf_fields:
            for state in [PDStatus.PREVIOUS, PDStatus.DATA]:
                if data.get(state) and pd_field_id in data[state] and isinstance(data[state][pd_field_id], str):
                    if handle_func == 'revert changes':
                        if state == PDStatus.PREVIOUS:
                            data[PDStatus.DATA][pd_field_id] = data[PDStatus.PREVIOUS][pd_field_id]

                    if callable(handle_func):
                        data[state][pd_field_id] = await handle_func(data[state][pd_field_id], data['meta']['entity'])
        return data

    ## TODO: Re-enable in #282
    # event_data = await handle_custom_field(event_data, 'hermes_id', handle_duplicate_hermes_ids)

    event_data = await handle_custom_field(event_data, 'signup_questionnaire', 'revert changes')

    # ignore any updated inherited custom fields on a deal
    deal_custom_fields = await CustomField.filter(
        linked_object_type='Deal', hermes_field_name__isnull=True, tc2_machine_name__isnull=True
    ).values_list('pd_field_id', flat=True)
    if event_data.get(PDStatus.PREVIOUS):
        for pd_field_id in deal_custom_fields:
            # revert any changes to inherited custom fields on a deal
            if event_data[PDStatus.PREVIOUS].get(pd_field_id):
                event_data[PDStatus.DATA][pd_field_id] = event_data[PDStatus.PREVIOUS][pd_field_id]

    return event_data


@pipedrive_router.post('/callback/', name='Pipedrive callback')
async def callback(event: dict, tasks: BackgroundTasks):
    """
    Processes a Pipedrive event. If a Deal is updated then we run a background task to update the cligency in Pipedrive
    TODO: This has 0 security, we should add some.
    """
    # Only process entities we explicitly handle
    entity = event.get('meta', {}).get('entity')
    processed_entities = (
        PDObjectNames.DEAL,
        PDObjectNames.PIPELINE,
        PDObjectNames.STAGE,
        PDObjectNames.PERSON,
        PDObjectNames.ORGANISATION,
    )
    if entity not in processed_entities:
        app_logger.info(f'{entity.capitalize() if entity else "Unknown"} event received, ignoring')
        return {'status': 'ok'}

    event_data = await prepare_event_data(event)
    event_instance = PipedriveEvent(**event_data)
    event_instance.data and await event_instance.data.a_validate()
    event_instance.previous and await event_instance.previous.a_validate()
    app_logger.info(f'Callback: event_instance received for {event_instance.meta.entity}: {event_instance}')
    if event_instance.meta.entity == 'deal':
        # For deletions, get the company before deleting the deal so we can notify TC2
        company = None
        if not event_instance.data and event_instance.previous:
            # This is a deletion - get the deal's company before it's deleted
            deal_to_delete = getattr(event_instance.previous, 'deal', None)
            if deal_to_delete:
                company = await deal_to_delete.company

        deal = await process_pd_deal(event_instance.data, event_instance.previous)

        # For updates/creates, get the company from the deal after processing
        if deal:
            company = await deal.company

        if company and company.tc2_agency_id:
            # We only update the client if the deal has a company with a tc2_agency_id
            tasks.add_task(update_client_from_company, company)
    elif event_instance.meta.entity == PDObjectNames.PIPELINE:
        await process_pd_pipeline(event_instance.data, event_instance.previous)
    elif event_instance.meta.entity == PDObjectNames.STAGE:
        await process_pd_stage(event_instance.data, event_instance.previous)
    elif event_instance.meta.entity == PDObjectNames.PERSON:
        await process_pd_person(event_instance.data, event_instance.previous)
    elif event_instance.meta.entity == PDObjectNames.ORGANISATION:
        company = await process_pd_organisation(event_instance.data, event_instance.previous)
        if company and company.tc2_agency_id:
            # We only update the client if the deal has a company with a tc2_agency_id
            tasks.add_task(update_client_from_company, company)
    return {'status': 'ok'}
