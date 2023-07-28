from app.models import Deal, Pipeline, Stage, Contact, Company
from app.pipedrive._schema import PDDeal, PDPipeline, PDStage, Person, Organisation
from app.pipedrive._utils import app_logger


async def _process_pd_deal(current_pd_deal: PDDeal, old_pd_deal: PDDeal) -> Deal | None:
    """
    Processes a Pipedrive deal event. Creates the deal if it didn't exist in Hermes, updates it if it did or deletes it
    if it's been removed.
    """
    deal = None
    if not old_pd_deal:
        # The deal has just been created. We need to create the deal in Hermes
        deal = await Deal.create(**await current_pd_deal.deal_dict())
        app_logger.info('Callback: creating Deal %s from PDDeal %s', deal.id, current_pd_deal.id)
    elif not current_pd_deal:
        # The deal has been deleted
        deal = await Deal.get(pd_deal_id=old_pd_deal.id)
        await deal.delete()
        app_logger.info('Callback: deleting Deal %s from PDDeal %s', deal.id, old_pd_deal.id)
    else:
        old_data = await old_pd_deal.deal_dict()
        new_data = await current_pd_deal.deal_dict()
        if old_data != new_data:
            deal = await Deal.get(pd_deal_id=old_pd_deal.id)
            await deal.update_from_dict(new_data)
            await deal.save()
            app_logger.info('Callback: updating Deal %s from PDDeal %s', deal.id, current_pd_deal.id)
    return deal


async def _process_pd_pipeline(current_pd_pipeline: PDPipeline, old_pd_pipeline: PDPipeline) -> Pipeline:
    """
    Processes a Pipedrive Pipeline event. Creates the Pipeline if it didn't exist in Hermes, updates " if it did ."""
    pipeline = None
    if not old_pd_pipeline:
        # The pipeline has just been created
        pipeline = await Pipeline.create(**await current_pd_pipeline.pipeline_dict())
        app_logger.info('Callback: creating Pipeline %s from PDPipeline %s', pipeline.id, current_pd_pipeline.id)
    elif not current_pd_pipeline:
        # The pipeline has been deleted
        pipeline = await Pipeline.get(pd_pipeline_id=old_pd_pipeline.id)
        await pipeline.delete()
        app_logger.info('Callback: deleting Pipeline %s from PDPipeline %s', pipeline.id, old_pd_pipeline.id)
    else:
        old_data = await old_pd_pipeline.pipeline_dict()
        new_data = await current_pd_pipeline.pipeline_dict()
        if old_data != new_data:
            pipeline = await Pipeline.get(pd_pipeline_id=old_pd_pipeline.id)
            await pipeline.update_from_dict(new_data)
            await pipeline.save()
            app_logger.info('Callback: updating Pipeline %s from PDPipeline %s', pipeline.id, current_pd_pipeline.id)
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
        app_logger.info('Callback: creating Stage %s from PDStage %s', stage.id, current_pd_stage.id)
    elif not current_pd_stage:
        # The stage has been deleted
        stage = await Stage.get(pd_stage_id=old_pd_stage.id)
        await stage.delete()
        app_logger.info('Callback: deleting Stage %s from PDStage%s', stage.id, old_pd_stage.id)
    else:
        old_data = await old_pd_stage.stage_dict()
        new_data = await current_pd_stage.stage_dict()
        if old_data != new_data:
            stage = await Stage.get(pd_stage_id=old_pd_stage.id)
            await stage.update_from_dict(new_data)
            await stage.save()
            app_logger.info('Callback: updating Stage %s from PDStage %s', stage.id, current_pd_stage.id)
    return stage


async def _process_pd_person(current_pd_person: Person, old_pd_person: Person) -> Contact | None:
    """
    Processes a Pipedrive Person/Contact event. Creates the Person/Contact if it didn't exist in Hermes,
    updates it if it did
    """
    contact = None
    if not old_pd_person:
        # The person has just been created
        contact = await Contact.create(**await current_pd_person.contact_dict())
        app_logger.info('Callback: creating Contact %s from Person %s', contact.id, current_pd_person.id)
    elif not current_pd_person:
        # The person has been deleted
        contact = await Contact.get(pd_person_id=old_pd_person.id)
        await contact.delete()
        app_logger.info('Callback: deleting Contact %s from Person %s', contact.id, old_pd_person.id)
    else:
        old_data = await old_pd_person.contact_dict()
        new_data = await current_pd_person.contact_dict()
        if old_data != new_data:
            contact = await Contact.get(pd_person_id=old_pd_person.id)
            await contact.update_from_dict(new_data)
            await contact.save()
            app_logger.info('Callback: updating Contact %s from Person %s', contact.id, current_pd_person.id)
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
        app_logger.info('Callback: creating Company %s from Organisation %s', company.id, current_pd_org.id)
    elif not current_pd_org:
        # The org has been deleted
        company = await Company.get(pd_org_id=old_pd_org.id)
        await company.delete()
        app_logger.info('Callback: deleting Company %s from Organisation %s', company.id, old_pd_org.id)
    else:
        old_data = await old_pd_org.company_dict()
        new_data = await current_pd_org.company_dict()
        if old_data != new_data:
            company = await Company.get(pd_org_id=old_pd_org.id)
            await company.update_from_dict(new_data)
            await company.save()
            app_logger.info('Callback: updating Company %s from Organisation %s', company.id, current_pd_org.id)
    return company
