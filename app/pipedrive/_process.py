from typing import Optional

from app.models import Deal, Pipeline, Stage, Contact, Company
from app.pipedrive._schema import PDDeal, PDPipeline, PDStage, Person, Organisation
from app.pipedrive._utils import app_logger


async def _process_pd_organisation(
    current_pd_org: Optional[Organisation], old_pd_org: Optional[Organisation]
) -> Company | None:
    """
    Processes a Pipedrive Organisation/Company event. Creates the Organisation/Company if it didn't exist in Hermes,
    updates it if it did.

    TODO: If we can't match the company by it's PD id, we should really try and match it by name also. However, as of
    now it should be impossible to create a company in Pipedrive that already exists in Hermes as the only other
    two ways to create a company (from TC2 and the Callbooker) always create the new company in PD.
    """
    # add hermes company id to pipedrive Org, that way filter by company_id
    # company = await Company.filter(pd_org_id=current_pd_org.id if current_pd_org else old_pd_org.id).first()
    company = await Company.filter(id=current_pd_org.company_id if current_pd_org else old_pd_org.company_id).first()
    if company:
        if current_pd_org:
            # The org has been updated
            old_data = old_pd_org and await old_pd_org.company_dict()
            new_data = await current_pd_org.company_dict()
            if old_data != new_data:
                await company.update_from_dict(new_data)
                await company.save()
                app_logger.info('Callback: updating Company %s from Organisation %s', company.id, current_pd_org.id)
        else:
            # The org has been deleted
            company = await Company.get(pd_org_id=old_pd_org.id)
            await company.delete()
            app_logger.info('Callback: deleting Company %s from Organisation %s', company.id, old_pd_org.id)
    elif current_pd_org:
        # The org has just been created
        company = await Company.create(**await current_pd_org.company_dict())
        app_logger.info('Callback: creating Company %s from Organisation %s', company.id, current_pd_org.id)
    return company


async def _process_pd_person(current_pd_person: Optional[Person], old_pd_person: Optional[Person]) -> Contact | None:
    """
    Processes a Pipedrive Person/Contact event. Creates the Person/Contact if it didn't exist in Hermes,
    updates it if it did

    TODO: If we can't match the contact by it's PD id, we should really try and match it by name also. However, I don't
    care enough since Companies are really the only important part.
    """
    contact = await Contact.filter(pd_person_id=current_pd_person.id if current_pd_person else old_pd_person.id).first()

    if contact:
        if current_pd_person:
            # The person has been updated
            old_data = old_pd_person and await old_pd_person.contact_dict()
            new_data = await current_pd_person.contact_dict()
            if new_data['company_id'] and old_data != new_data:
                await contact.update_from_dict(new_data)
                await contact.save()
                app_logger.info('Callback: updating Contact %s from Person %s', contact.id, current_pd_person.id)
        else:
            # The person has been deleted
            contact = await Contact.get(pd_person_id=old_pd_person.id)
            await contact.delete()
            app_logger.info('Callback: deleting Contact %s from Person %s', contact.id, old_pd_person.id)
    elif current_pd_person:
        # The person has just been created
        contact_data = await current_pd_person.contact_dict()
        if contact_data['company_id']:
            contact = await Contact.create(**contact_data)
            app_logger.info('Callback: creating Contact %s from Person %s', contact.id, current_pd_person.id)
        else:
            app_logger.info(
                'Callback: not creating Contact from Person %s as Org %s not in DB',
                current_pd_person.id,
                current_pd_person.org_id,
            )
    return contact


async def _process_pd_deal(current_pd_deal: Optional[PDDeal], old_pd_deal: Optional[PDDeal]) -> Deal | None:
    """
    Processes a Pipedrive deal event. Creates the deal if it didn't exist in Hermes, updates it if it did or deletes it
    if it's been removed.
    """
    # deal = await Deal.filter(pd_deal_id=current_pd_deal.hermes_deal_id if current_pd_deal else old_pd_deal.hermes_deal_id).first()
    deal = await Deal.filter(pd_deal_id=current_pd_deal.id if current_pd_deal else old_pd_deal.id).first()

    if deal:
        if current_pd_deal:
            # The deal has been updated
            old_data = old_pd_deal and await old_pd_deal.deal_dict()
            new_data = await current_pd_deal.deal_dict()
            if old_data != new_data:
                await deal.update_from_dict(new_data)
                await deal.save()
                app_logger.info('Callback: updating Deal %s from PDDeal %s', deal.id, current_pd_deal.id)
        else:
            # The deal has been deleted
            deal = await Deal.get(pd_deal_id=old_pd_deal.id)
            await deal.delete()
            app_logger.info('Callback: deleting Deal %s from PDDeal %s', deal.id, old_pd_deal.id)
    elif current_pd_deal:
        # The deal has just been created
        deal = await Deal.create(**await current_pd_deal.deal_dict())
        app_logger.info('Callback: creating Deal %s from PDDeal %s', deal.id, current_pd_deal.id)
    return deal


async def _process_pd_pipeline(
    current_pd_pipeline: Optional[PDPipeline], old_pd_pipeline: Optional[PDPipeline]
) -> Pipeline | None:
    """
    Processes a Pipedrive Pipeline event. Creates the Pipeline if it didn't exist in Hermes, updates if it did .
    """
    pd_pipeline_id = current_pd_pipeline.id if current_pd_pipeline else old_pd_pipeline.id
    pipeline = await Pipeline.filter(pd_pipeline_id=pd_pipeline_id).first()

    if pipeline:
        if current_pd_pipeline:
            # The pipeline has been updated
            old_data = old_pd_pipeline and await old_pd_pipeline.pipeline_dict()
            new_data = await current_pd_pipeline.pipeline_dict()
            if old_data != new_data:
                await pipeline.update_from_dict(new_data)
                await pipeline.save()
                app_logger.info(
                    'Callback: updating Pipeline %s from PDPipeline %s', pipeline.id, current_pd_pipeline.id
                )
        else:
            # The pipeline has been deleted
            pipeline = await Pipeline.get(pd_pipeline_id=old_pd_pipeline.id)
            await pipeline.delete()
            app_logger.info('Callback: deleting Pipeline %s from PDPipeline %s', pipeline.id, old_pd_pipeline.id)
    elif current_pd_pipeline:
        # The pipeline has just been created
        pipeline = await Pipeline.create(**await current_pd_pipeline.pipeline_dict())
        app_logger.info('Callback: creating Pipeline %s from PDPipeline %s', pipeline.id, current_pd_pipeline.id)
    return pipeline


async def _process_pd_stage(current_pd_stage: Optional[PDStage], old_pd_stage: Optional[PDStage]) -> Stage | None:
    """
    Processes a Pipedrive Stage event. Creates the Stage if it didn't exist in Hermes,
    updates it if it did
    """
    pd_stage_id = current_pd_stage.id if current_pd_stage else old_pd_stage.id
    stage = await Stage.filter(pd_stage_id=pd_stage_id).first()
    if stage:
        if current_pd_stage:
            # The stage has been updated
            old_data = old_pd_stage and await old_pd_stage.stage_dict()
            new_data = await current_pd_stage.stage_dict()
            if old_data != new_data:
                await stage.update_from_dict(new_data)
                await stage.save()
                app_logger.info('Callback: updating Stage %s from PDStage %s', stage.id, current_pd_stage.id)
        else:
            # The stage has been deleted
            stage = await Stage.get(pd_stage_id=old_pd_stage.id)
            await stage.delete()
            app_logger.info('Callback: deleting Stage %s from PDStage%s', stage.id, old_pd_stage.id)
    elif current_pd_stage:
        # The stage has just been created
        stage = await Stage.create(**await current_pd_stage.stage_dict())
        app_logger.info('Callback: creating Stage %s from PDStage %s', stage.id, current_pd_stage.id)
    return stage
