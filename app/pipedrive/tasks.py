from typing import Type

import logfire
from tortoise.transactions import in_transaction

from app.base_schema import get_custom_fieldinfo
from app.models import Company, Contact, CustomField, Deal, Meeting
from app.pipedrive._process import update_or_create_inherited_deal_custom_field_values
from app.pipedrive._schema import Activity, Organisation, PDDeal, Person, PipedriveBaseModel
from app.pipedrive.api import (
    create_activity,
    delete_deal,
    delete_organisation,
    delete_persons,
    get_and_create_or_update_organisation,
    get_and_create_or_update_pd_deal,
    get_and_create_or_update_person,
)


async def _transy_get_and_create_or_update_organisation(company: Company) -> Organisation:
    """
    Create or update an Org in Pipedrive in a transaction
    """
    async with in_transaction():
        company = await Company.select_for_update().get(id=company.id)
        return await get_and_create_or_update_organisation(company)


async def _transy_get_and_create_or_update_person(contact: Contact) -> Person:
    """
    Create or update an Org in Pipedrive in a transaction
    """
    async with in_transaction():
        contact = await Contact.select_for_update().get(id=contact.id)
        return await get_and_create_or_update_person(contact)


async def _transy_get_and_create_or_update_deal(deal: Deal) -> PDDeal:
    """
    Create or update an Org in Pipedrive in a transaction
    """
    async with in_transaction():
        deal = await Deal.select_for_update().get(id=deal.id)
        return await get_and_create_or_update_pd_deal(deal)


async def _transy_create_activity(meeting: Meeting, pd_deal: PDDeal = None) -> Activity:
    """
    Create or update an Org in Pipedrive in a transaction
    """
    async with in_transaction():
        meeting = await Meeting.select_for_update().get(id=meeting.id)
        return await create_activity(meeting, pd_deal)


async def pd_post_process_sales_call(company: Company, contact: Contact, meeting: Meeting, deal: Deal):
    """
    Called after a sales call is booked. Creates/updates the Org & Person in pipedrive then creates the activity.
    """
    with logfire.span('pd_post_process_sales_call'):
        await _transy_get_and_create_or_update_organisation(company)
        await _transy_get_and_create_or_update_person(contact)
        pd_deal = await _transy_get_and_create_or_update_deal(deal)
        await update_or_create_inherited_deal_custom_field_values(company)
        await _transy_create_activity(meeting, pd_deal)


async def pd_post_process_support_call(contact: Contact, meeting: Meeting):
    """
    Called after a support call is booked. Creates the activity if the contact have a pipedrive id
    """
    with logfire.span('pd_post_process_support_call'):
        await _transy_get_and_create_or_update_person(contact)
        await _transy_create_activity(meeting)


async def pd_post_process_client_event(company: Company, deal: Deal = None):
    """
    Called after a client event from TC2. For example, a client paying an invoice.
    """
    with logfire.span('pd_post_process_client_event'):
        await _transy_get_and_create_or_update_organisation(company)
        for contact in await company.contacts:
            await _transy_get_and_create_or_update_person(contact)
        if deal:
            await _transy_get_and_create_or_update_deal(deal)
            await update_or_create_inherited_deal_custom_field_values(company)


async def pd_post_purge_client_event(company: Company, deal: Deal = None):
    """
    Called after a client event from TC2. Deletes the Org & Persons in pipedrive then deletes the deal.
    """
    with logfire.span('pd_post_purge_client_event'):
        if deal:
            await delete_deal(deal)
        await delete_persons(list(await company.contacts))
        await delete_organisation(company)


MODEL_PD_LU = {Company: Organisation, Contact: Person, Deal: PDDeal, Meeting: Activity}


async def pd_rebuild_schema_with_custom_fields() -> list[Type[PipedriveBaseModel]]:
    """
    Adds extra fields to the schema for the Pipedrive models based on CustomFields in the DB
    """
    with logfire.span('pd_rebuild_schema_with_custom_fields'):
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
