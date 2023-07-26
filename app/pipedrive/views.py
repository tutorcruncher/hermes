from fastapi import APIRouter
from starlette.background import BackgroundTasks

from app.models import Deal, Pipeline, Stage, Contact, Company
from app.pipedrive._schema import PipedriveEvent, PDDeal, PDPipeline, PDStage, Person, Organisation
from app.pipedrive._utils import app_logger
from app.tc2.tasks import update_client_from_deal

pipedrive_router = APIRouter()


async def _process_pd_deal(current_pd_deal: PDDeal, old_pd_deal: PDDeal) -> Deal | None:
    """
    Processes a Pipedrive deal event. Creates the deal if it didn't exist in Hermes, updates it if it did or deletes it
    if it's been removed.
    """
    deal = None
    if not old_pd_deal:
        # The deal has just been created. We need to create the deal in Hermes
        deal = await Deal.create(**await current_pd_deal.deal_dict())
    elif not current_pd_deal:
        # The deal has been deleted
        deal = await Deal.get(pd_deal_id=old_pd_deal.id)
        await deal.delete()
    else:
        old_data = await old_pd_deal.deal_dict()
        new_data = await current_pd_deal.deal_dict()
        if old_data != new_data:
            deal = await Deal.get(pd_deal_id=old_pd_deal.id)
            await deal.update_from_dict(new_data)
            await deal.save()
    return deal


async def _process_pd_pipeline(current_pd_pipeline: PDPipeline, old_pd_pipeline: PDPipeline) -> Pipeline:
    """
    Processes a Pipedrive Pipeline event. Creates the Pipeline if it didn't exist in Hermes, updates it if it did
    """
    pipeline = None
    if not old_pd_pipeline:
        # The pipeline has just been created
        pipeline = await Pipeline.create(**await current_pd_pipeline.pipeline_dict())
    elif not current_pd_pipeline:
        # The pipeline has been deleted
        pipeline = await Pipeline.get(pd_pipeline_id=old_pd_pipeline.id)
        await pipeline.delete()
    else:
        old_data = await old_pd_pipeline.pipeline_dict()
        new_data = await current_pd_pipeline.pipeline_dict()
        if old_data != new_data:
            pipeline = await Pipeline.get(pd_pipeline_id=old_pd_pipeline.id)
            await pipeline.update_from_dict(new_data)
            await pipeline.save()
    return pipeline


async def _process_pd_stage(current_pd_stage: PDStage, old_pd_stage: PDStage):
    """
    Processes a Pipedrive Stage event. Creates the Stage if it didn't exist in Hermes,
    updates it if it did
    """
    stage = None
    if not old_pd_stage:
        # The stage has just been created
        stage = await Stage.create(**await current_pd_stage.stage_dict())
    elif not current_pd_stage:
        # The stage has been deleted
        stage = await Stage.get(pd_stage_id=old_pd_stage.id)
        await stage.delete()
    else:
        old_data = await old_pd_stage.stage_dict()
        new_data = await current_pd_stage.stage_dict()
        if old_data != new_data:
            stage = await Stage.get(pd_stage_id=old_pd_stage.id)
            await stage.update_from_dict(new_data)
            await stage.save()
    return stage


async def _process_pd_person(current_pd_person: Person, old_pd_person: Person) -> Contact | None:
    """
    Processes a Pipedrive Person/Contact event. Creates the Person/Contact if it didn't exist in Hermes,
    updates it if it did
    """
    contact = None
    if not old_pd_person:
        # The person has just been created
        contact_data = await current_pd_person.contact_dict()
        contact = await Contact.create(**contact_data)
    elif not current_pd_person:
        # The person has been deleted
        contact = await Contact.get(pd_person_id=old_pd_person.id)
        await contact.delete()
    else:
        old_data = await old_pd_person.contact_dict()
        new_data = await current_pd_person.contact_dict()
        if old_data != new_data:
            contact = await Contact.get(pd_person_id=old_pd_person.id)
            await contact.update_from_dict(new_data)
            await contact.save()
    return contact


async def _process_pd_organisation(current_pd_org: Organisation, old_pd_org: Organisation) -> Company | None:
    """
    Processes a Pipedrive Organisation/Company event. Creates the Organisation/Company if it didn't exist in Hermes,
    updates it if it did.
    """
    company = None
    if not old_pd_org:
        # The org has just been created
        company = await Company.create(**await current_pd_org.company_dict())
    elif not current_pd_org:
        # The org has been deleted
        company = await Company.get(pd_org_id=old_pd_org.id)
        await company.delete()
    else:
        old_data = await old_pd_org.company_dict()
        new_data = await current_pd_org.company_dict()
        if old_data != new_data:
            company = await Company.get(pd_org_id=old_pd_org.id)
            await company.update_from_dict(new_data)
            await company.save()
    return company


@pipedrive_router.post('/callback/', name='Pipedrive callback')
async def callback(event: PipedriveEvent, background_tasks: BackgroundTasks):
    """
    Processes a Pipedrive event. If a Deal is updated then we run a background task to update the cligency in Pipedrive
    """
    event.current and await event.current.a_validate()
    event.previous and await event.previous.a_validate()
    app_logger.info(f'Pipedrive event received: {event.dict()}')
    if event.meta.object == 'deal':
        deal = await _process_pd_deal(event.current, event.previous)
        if deal and (await deal.company).tc_agency_id:
            # We only update the client if the deal has a company with a tc_agency_id
            background_tasks.add_task(update_client_from_deal, deal)
    elif event.meta.object == 'pipeline':
        await _process_pd_pipeline(event.current, event.previous)
    elif event.meta.object == 'stage':
        await _process_pd_stage(event.current, event.previous)
    elif event.meta.object == 'person':
        await _process_pd_person(event.current, event.previous)
    elif event.meta.object == 'organization':
        await _process_pd_organisation(event.current, event.previous)
    return {'status': 'ok'}
