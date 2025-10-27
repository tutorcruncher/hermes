import logging

from fastapi import APIRouter, Depends

from app.core.database import DBSession, get_db
from app.pipedrive.models import Organisation, PDDeal, PDPipeline, PDStage, Person, PipedriveEvent
from app.pipedrive.process import (
    OrganisationProcessor,
    PDDealProcessor,
    PDPipelineProcessor,
    PDStageProcessor,
    PersonProcessor,
)

logger = logging.getLogger('hermes.pipedrive')

router = APIRouter(prefix='/pipedrive', tags=['pipedrive'])


@router.post('/callback/', name='pipedrive-callback')
async def pipedrive_callback(event: dict, db: DBSession = Depends(get_db)):
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
            await PDDealProcessor(db).process(old_data, new_data)

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
