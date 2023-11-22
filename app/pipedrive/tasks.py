from typing import Type

from app.base_schema import get_custom_fieldinfo
from app.models import Company, Contact, Deal, Meeting, CustomField
from app.pipedrive._schema import Organisation, Person, PDDeal, Activity, PipedriveBaseModel
from app.pipedrive.api import (
    create_activity,
    create_or_update_organisation,
    create_or_update_person,
    get_or_create_pd_deal,
    delete_organisation,
    delete_persons,
    delete_deal,
)


async def pd_post_process_sales_call(company: Company, contact: Contact, meeting: Meeting, deal: Deal):
    """
    Called after a sales call is booked. Creates/updates the Org & Person in pipedrive then creates the activity.
    """
    await create_or_update_organisation(company)
    await create_or_update_person(contact)
    pd_deal = await get_or_create_pd_deal(deal)
    await create_activity(meeting, pd_deal)


async def pd_post_process_support_call(contact: Contact, meeting: Meeting):
    """
    Called after a support call is booked. Creates the activity if the contact have a pipedrive id
    """
    if (await contact.company).pd_org_id:
        await create_or_update_person(contact)
        await create_activity(meeting)


async def pd_post_process_client_event(company: Company, deal: Deal = None):
    """
    Called after a client event from TC2. For example, a client paying an invoice.
    """
    await create_or_update_organisation(company)
    for contact in await company.contacts:
        await create_or_update_person(contact)
    if deal:
        await get_or_create_pd_deal(deal)


async def pd_post_purge_client_event(company: Company, deal: Deal = None):
    """
    Called after a client event from TC2. Deletes the Org & Persons in pipedrive then deletes the deal.
    """
    await delete_organisation(company)
    await delete_persons(list(await company.contacts))
    if deal:
        await delete_deal(deal)


MODEL_PD_LU = {Company: Organisation, Contact: Person, Deal: PDDeal, Meeting: Activity}


async def pd_rebuild_schema_with_custom_fields() -> list[Type[PipedriveBaseModel]]:
    """
    Adds extra fields to the schema for the Pipedrive models based on CustomFields in the DB
    """
    models_to_rebuild = []
    for model, pd_model in MODEL_PD_LU.items():
        custom_fields = await CustomField.filter(linked_object_type=model.__name__)
        # First we reset the custom fields
        pd_model.model_fields = {
            k: v for k, v in pd_model.model_fields.items() if not (v.json_schema_extra or {}).get('custom')
        }
        for field in custom_fields:
            pd_model.model_fields[field.machine_name] = await get_custom_fieldinfo(
                field, model, serialization_alias=field.pd_field_id, validation_alias=field.pd_field_id
            )
        models_to_rebuild.append(pd_model)
    return models_to_rebuild
