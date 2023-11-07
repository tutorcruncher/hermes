from app.base_schema import fk_json_schema_extra
from pydantic.fields import FieldInfo
from app.models import Company, Contact, Deal, Meeting, CustomField
from app.pipedrive._schema import Organisation, Person, PDDeal, Activity
from app.pipedrive.api import (
    create_activity,
    create_or_update_organisation,
    create_or_update_person,
    get_or_create_pd_deal,
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


MODEL_PD_LU = {Company: Organisation, Contact: Person, Deal: PDDeal, Meeting: Activity}


async def build_custom_field_schema():
    for model, pd_model in MODEL_PD_LU.items():
        custom_fields = await CustomField.filter(linked_object_type=model.__name__)
        # First we reset the custom fields
        pd_model.model_fields = {
            k: v for k, v in pd_model.model_fields.items() if not (v.json_schema_extra or {}).get('custom')
        }
        if custom_fields:
            for field in custom_fields:
                field_kwargs = {
                    'title': field.name,
                    'default': None,
                    'required': False,
                    'serialization_alias': field.pd_field_id,
                    'validation_alias': field.pd_field_id,
                    'json_schema_extra': {'custom': True},
                }
                if field.field_type == CustomField.TYPE_INT:
                    field_kwargs['annotation'] = int
                elif field.field_type == CustomField.TYPE_STR:
                    field_kwargs['annotation'] = str
                elif field.field_type == CustomField.TYPE_FK_FIELD:
                    field_kwargs.update(annotation=int, json_schema_extra=fk_json_schema_extra(model, custom=True))
                pd_model.model_fields[field.machine_name] = FieldInfo(**field_kwargs)
        pd_model.model_rebuild(force=True)
