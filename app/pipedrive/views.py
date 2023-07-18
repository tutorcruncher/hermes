from fastapi import APIRouter, Body
from starlette.background import BackgroundTasks

from app.models import Deals, Pipelines, PipelineStages, Contacts, Companies
from app.pipedrive._schema import PipedriveEvent, PDDeal, PDPipeline, PDStage, Person, Organisation
from app.pipedrive._utils import app_logger

pipedrive_router = APIRouter()


async def _process_pd_deal(event: PipedriveEvent) -> Deals | None:
    """
    Processes a Pipedrive deal event. Creates the deal if it didn't exist in Hermes, updates it if it did or deletes it
    if it's been removed.
    """
    current_pd_deal = event.current and PDDeal(**event.current)
    old_pd_deal = event.previous and PDDeal(**event.previous)
    deal = None
    if not old_pd_deal:
        # The deal has just been created. We need to create the deal in Hermes and update the cligency in Meta with
        # the deal's stage
        deal = await Deals.create(**await current_pd_deal.deal_dict())
    elif not current_pd_deal:
        # The deal has been deleted
        deal = await Deals.get(id=old_pd_deal.id)
        await deal.delete()
    elif old_pd_deal.stage_id != current_pd_deal.stage_id or old_pd_deal.status != current_pd_deal.status:
        # The deal has moved from one stage to another, or been closed/reopened
        deal = await Deals.get(id=old_pd_deal.id)
        await deal.update_from_dict(**await current_pd_deal.deal_dict())
        await deal.save()
    return deal


async def _process_pd_pipeline(event: PipedriveEvent):
    """
    Processes a Pipedrive Pipeline event. Creates the Pipeline if it didn't exist in Hermes, updates it if it did
    """
    current_pd_pipeline = event.current and PDPipeline(**event.current)
    old_pd_pipeline = event.previous and PDPipeline(**event.previous)
    if not old_pd_pipeline:
        # The pipeline has just been created
        await Pipelines.create(**await current_pd_pipeline.pipeline_dict())
    elif not current_pd_pipeline:
        # The pipeline has been deleted
        pipeline = await Pipelines.get(id=old_pd_pipeline.id)
        await pipeline.delete()
    elif old_pd_pipeline.name != current_pd_pipeline.name:
        pipeline = await Pipelines.get(id=old_pd_pipeline.id)
        pipeline.name = current_pd_pipeline.name
        await pipeline.save()


async def _process_pd_stage(event: PipedriveEvent):
    """
    Processes a Pipedrive Stage/PipelineStage event. Creates the Stage/PipelineStage if it didn't exist in Hermes,
    updates it if it did
    """
    current_pd_stage = event.current and PDStage(**event.current)
    old_pd_stage = event.previous and PDStage(**event.previous)
    if not old_pd_stage:
        # The stage has just been created
        await PipelineStages.create(**await current_pd_stage.stage_dict())
    elif not current_pd_stage:
        # The stage has been deleted
        stage = await PipelineStages.get(id=old_pd_stage.id)
        await stage.delete()
    elif old_pd_stage.name != current_pd_stage.name:
        stage = await PipelineStages.get(id=old_pd_stage.id)
        stage.name = current_pd_stage.name
        await stage.save()


async def _process_pd_person(event: PipedriveEvent) -> Contacts | None:
    """
    Processes a Pipedrive Person/Contact event. Creates the Person/Contact if it didn't exist in Hermes,
    updates it if it did
    """

    # What if no company?

    current_pd_person = event.current and Person(**event.current)
    old_pd_person = event.previous and Person(**event.previous)
    contact = None
    if not old_pd_person:
        # The person has just been created
        contact_data = await current_pd_person.contact_dict()
        company = await Companies.get(id=current_pd_person.org_id)
        contact_data['company_id'] = company.id
        contact = await Contacts.create(**contact_data)
    elif not current_pd_person:
        # The person has been deleted
        contact = await Contacts.get(id=old_pd_person.id)
        await contact.delete()
    else:
        old_data = await old_pd_person.contact_dict()
        new_data = await current_pd_person.contact_dict()
        if old_data != new_data:
            contact = await Contacts.get(id=old_pd_person.id)
            await contact.update_from_dict(**await current_pd_person.contact_dict())
            await contact.save()
    return contact


async def _process_pd_organisation(current_pd_org: Organisation, old_pd_org: Organisation) -> Companies | None:
    """
    Processes a Pipedrive Organisation/Company event. Creates the Organisation/Company if it didn't exist in Hermes,
    updates it if it did
    """
    company = None
    if not old_pd_org:
        # The org has just been created
        company = await Companies.create(**await current_pd_org.company_dict())
    elif not current_pd_org:
        # The org has been deleted
        company = await Companies.get(id=old_pd_org.id)
        await company.delete()
    else:
        old_data = await old_pd_org.company_dict()
        new_data = await current_pd_org.company_dict()
        if old_data != new_data:
            company = await Companies.get(id=old_pd_org.id)
            await company.update_from_dict(**new_data)
            await company.save()
    return company


@pipedrive_router.post('/callback/', name='Pipedrive callback')
async def callback(event: PipedriveEvent, background_tasks: BackgroundTasks):
    """
    Processes a Pipedrive event. If a Deal is updated then we run a task to update the cligency in Pipedrive
    """
    app_logger.info(f'Pipedrive event received: {event.dict()}')
    if event.meta.object == 'deal':
        deal = await _process_pd_deal(event)
        if deal and (await deal.company).tc_agency_id:
            background_tasks.add_task(update_client_from_deal, deal)
    elif event.meta.object == 'pipeline':
        await _process_pd_pipeline(event)
    elif event.meta.object == 'stage':
        await _process_pd_stage(event)
    elif event.meta.object == 'person':
        await _process_pd_person(event)
    elif event.meta.object == 'organization':
        await _process_pd_organisation(event.current, event.previous)
    return {'status': 'ok'}
