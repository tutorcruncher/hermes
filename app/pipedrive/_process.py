from typing import Optional

from tortoise.exceptions import DoesNotExist

from app.models import Company, Contact, CustomField, CustomFieldValue, Deal, Pipeline, Stage
from app.pipedrive._schema import Organisation, PDDeal, PDPipeline, PDStage, Person
from app.pipedrive._utils import app_logger
from app.pipedrive.api import get_and_create_or_update_organisation, get_and_create_or_update_pd_deal


async def update_or_create_inherited_deal_custom_field_values(company):
    """
    Update the inherited custom field values of all company deals with the custom field values of the company
    then send to pipedrive to update the deal
    """
    deal_custom_fields = await CustomField.filter(linked_object_type='Deal')
    deal_custom_field_machine_names = [cf.machine_name for cf in deal_custom_fields]
    company_custom_fields_to_inherit = (
        await CustomField.filter(linked_object_type='Company', machine_name__in=deal_custom_field_machine_names)
        .exclude(machine_name='hermes_id')
        .prefetch_related('values')
    )

    deals = await company.deals

    for cf in company_custom_fields_to_inherit:
        deal_cf = next((dcf for dcf in deal_custom_fields if dcf.machine_name == cf.machine_name), None)
        if not deal_cf:
            continue

        if cf.values:
            value = cf.values[0].value
        elif cf.hermes_field_name:
            value = getattr(company, cf.hermes_field_name, None).id
        else:
            raise ValueError(f'No value for custom field {cf}')

        for deal in deals:
            await CustomFieldValue.update_or_create(
                **{'custom_field_id': deal_cf.id, 'deal': deal, 'defaults': {'value': value}}
            )

            await get_and_create_or_update_pd_deal(deal)


async def _process_pd_organisation(
    current_pd_org: Optional[Organisation], old_pd_org: Optional[Organisation]
) -> Company | None:
    """
    Processes a Pipedrive Organisation/Company event. Creates the Organisation/Company if it didn't exist in Hermes,
    updates it if it did.

    TODO: If we can't match the company by it's hermes_id, we should really try and match it by name also. However, as
    of now it should be impossible to create a company in Pipedrive that already exists in Hermes as the only other
    two ways to create a company (from TC2 and the Callbooker) always create the new company in PD.

    if a company is not found in a_validate, then we will also check if it already exists in the db by matching the
    pd_org_id
    """
    # Company has been set here by Org.a_validate, as we have a custom field `hermes_id` linking it to the Company
    current_company = getattr(current_pd_org, 'company', None) if current_pd_org else None
    old_company = getattr(old_pd_org, 'company', None) if old_pd_org else None

    try:
        existing_company = await Company.get(pd_org_id=current_pd_org.id) if current_pd_org else None
    except DoesNotExist:
        existing_company = None
    company = current_company or old_company or existing_company
    company_custom_fields = await CustomField.filter(linked_object_type='Company')
    if company:
        if current_pd_org:
            # The org has been updated
            old_org_data = old_pd_org and await old_pd_org.company_dict(company_custom_fields)
            new_org_data = await current_pd_org.company_dict(company_custom_fields)
            if old_org_data != new_org_data:
                await company.update_from_dict(new_org_data)
                await company.save()
                app_logger.info('Callback: updating Company %s from Organisation %s', company.id, current_pd_org.id)
            old_company_cf_vals = await old_pd_org.custom_field_values(company_custom_fields) if old_org_data else {}
            new_company_cf_vals = await current_pd_org.custom_field_values(company_custom_fields)
            cfs_created, cfs_updated, cfs_deleted = await company.process_custom_field_vals(
                old_company_cf_vals, new_company_cf_vals
            )
            if cfs_created:
                app_logger.info(
                    'Callback: creating Company %s cf ids %s from Organisation %s',
                    company.id,
                    list(cfs_created),
                    current_pd_org.id,
                )
            if cfs_updated:
                app_logger.info(
                    'Callback: updating Company %s cf ids %s from Organisation %s',
                    company.id,
                    list(cfs_updated),
                    current_pd_org.id,
                )
            if cfs_deleted:
                app_logger.info(
                    'Callback: deleting Company %s cf ids %s from Organisation %s',
                    company.id,
                    list(cfs_deleted),
                    current_pd_org.id,
                )
        else:
            # The org has been deleted. The linked custom fields will also be deleted
            await company.delete()
            app_logger.info('Callback: deleting Company %s from Organisation %s', company.id, old_pd_org.id)
    elif current_pd_org:
        # The org has just been created
        company = await Company.create(**await current_pd_org.company_dict(company_custom_fields))
        # post to pipedrive to update the hermes_id
        app_logger.info('Callback: creating Company %s from Organisation %s', company.id, current_pd_org.id)
        new_company_cf_vals = await current_pd_org.custom_field_values(company_custom_fields)
        cfs_created = await company.process_custom_field_vals({}, new_company_cf_vals)
        if cfs_created:
            app_logger.info(
                'Callback: creating Company %s cf values from Organisation %s', company.id, current_pd_org.id
            )

    # here we should check if any cf values have been updated which should be inherited by the deal
    if await company.deals:
        await update_or_create_inherited_deal_custom_field_values(company)

    return company


async def _process_pd_person(current_pd_person: Optional[Person], old_pd_person: Optional[Person]) -> Contact | None:
    """
    Processes a Pipedrive Person/Contact event. Creates the Person/Contact if it didn't exist in Hermes,
    updates it if it did

    TODO: If we can't match the contact by it's hermes_id, we should really try and match it by name also. However, I
    don't care enough since Companies are really the only important part.

    if a contact is not found in a_validate, then we will also check if it already exists in the db by matching the
    pd_person_id
    """
    # Contact has been set here by Person.a_validate, as we have a custom field `hermes_id` linking it to the Contact
    current_contact = getattr(current_pd_person, 'contact', None) if current_pd_person else None
    old_contact = getattr(old_pd_person, 'contact', None) if old_pd_person else None

    try:
        existing_person = await Contact.get(pd_person_id=current_pd_person.id) if current_pd_person else None
    except DoesNotExist:
        existing_person = None

    contact = current_contact or old_contact or existing_person
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
    # Deal has been set here by PDDeal.a_validate, as we have a custom field `hermes_id` linking it to the Deal
    current_deal = getattr(current_pd_deal, 'deal', None) if current_pd_deal else None
    old_deal = getattr(old_pd_deal, 'deal', None) if old_pd_deal else None
    deal = current_deal or old_deal
    deal_custom_fields = await CustomField.filter(linked_object_type='Deal')

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
