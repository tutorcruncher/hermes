import logging

from fastapi import APIRouter, BackgroundTasks, Depends

from app.core.database import DBSession, get_db
from app.pipedrive.models import Organisation, PDDeal, PDPipeline, PDStage, Person, PipedriveEvent
from app.pipedrive.process import (
    OrganisationProcessor,
    PDDealProcessor,
    PDPipelineProcessor,
    PDStageProcessor,
    PersonProcessor,
)
from app.pipedrive.tasks import create_contact_for_pd_deal

logger = logging.getLogger('hermes.pipedrive')

router = APIRouter(prefix='/pipedrive', tags=['pipedrive'])


@router.post('/callback/', name='pipedrive-callback')
async def pipedrive_callback(
    event: dict,
    background_tasks: BackgroundTasks,
    # 'function' closes the session before the background tasks run, so none is held while they wait on Pipedrive
    db: DBSession = Depends(get_db, scope='function'),
):
    """
    Process Pipedrive webhooks: Pipedrive → Hermes (no TC2 sync)

    This endpoint receives webhooks from Pipedrive when organizations, persons, or deals are updated.
    It updates the Hermes database but does NOT propagate changes back to TC2.

    Supported entities: organization, person, deal, pipeline, stage
    """
    entity = event.get('meta', {}).get('entity')
    action = event.get('meta', {}).get('action')

    logger.info(f'Received Pipedrive webhook: entity={entity}, action={action}')
    if entity not in ('organization', 'person', 'deal', 'pipeline', 'stage'):
        logger.info(f'Ignoring {entity} event')
        return {'status': 'ok'}

    try:
        webhook_event = PipedriveEvent(**event)
        new_data = None
        old_data = None
        if entity == 'organization':
            if webhook_event.data:
                new_data = Organisation(**webhook_event.data)
            if webhook_event.previous:
                old_data = Organisation(**webhook_event.previous)
            await OrganisationProcessor(db).process(old_data, new_data)

        elif entity == 'person':
            if webhook_event.data:
                new_data = Person(**webhook_event.data)
            if webhook_event.previous:
                old_data = Person(**webhook_event.previous)
            await PersonProcessor(db).process(old_data, new_data)

        elif entity == 'deal':
            if webhook_event.data:
                new_data = PDDeal(**webhook_event.data)
            if webhook_event.previous:
                old_data = PDDeal(**webhook_event.previous)
            deal_processor = PDDealProcessor(db)
            await deal_processor.process(old_data, new_data)
            for deal_id, pd_person_id in deal_processor.contacts_to_fetch:
                background_tasks.add_task(create_contact_for_pd_deal, deal_id, pd_person_id)

        elif entity == 'pipeline':
            if webhook_event.data:
                new_data = PDPipeline(**webhook_event.data)
            if webhook_event.previous:
                old_data = PDPipeline(**webhook_event.previous)
            await PDPipelineProcessor(db).process(old_data, new_data)

        elif entity == 'stage':
            if webhook_event.data:
                new_data = PDStage(**webhook_event.data)
            if webhook_event.previous:
                old_data = PDStage(**webhook_event.previous)
            await PDStageProcessor(db).process(old_data, new_data)

        logger.info(f'Successfully processed {entity} webhook')

    except Exception as e:
        logger.error(f'Error processing Pipedrive webhook: {e}', exc_info=True)
        # Don't raise - return success to Pipedrive even if we had an error
        # This prevents them from retrying and spamming us

    return {'status': 'ok'}
