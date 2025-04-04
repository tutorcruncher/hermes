from datetime import datetime, timedelta

from pydantic import ValidationError
from pytz import utc

from app.models import Company, Contact, CustomField, CustomFieldValue, Deal
from app.tc2._schema import TCClient, TCInvoice, TCRecipient, TCSubject, _TCSimpleRole
from app.tc2._utils import app_logger
from app.tc2.api import tc2_request
from app.utils import get_config


async def _create_or_update_company(tc2_client: TCClient) -> tuple[bool, Company]:
    """
    Creates or updates a Company in our database from a TutorCruncher client/meta_agency.

    TODO: We should try and match companies on their name/contact email address rather than creating a new one.
    """
    company_custom_fields = await CustomField.filter(linked_object_type='Company')
    company_data = tc2_client.company_dict(company_custom_fields)
    company_id = company_data.pop('tc2_agency_id')

    if company_data['sales_person'] is None:
        raise ValidationError('Company must have a sales_person, Please add one in TC2')

    company, created = await Company.get_or_create(tc2_agency_id=company_id, defaults=company_data)

    company.has_signed_up = True
    await company.save()

    if not created:
        company = await company.update_from_dict(company_data)
        await company.save()
    # TC2 doesn't tell us which custom fields have been updated, so we have to check them all.
    await company.process_custom_field_vals({}, await tc2_client.custom_field_values(company_custom_fields))
    return created, company


async def _create_or_update_contact(tc2_sr: TCRecipient, company: Company) -> tuple[bool, Contact]:
    """
    Creates or updates a Contact in our database from a TutorCruncher SR (linked to a Cligency).
    """
    contact_data = tc2_sr.contact_dict()
    contact_data['company_id'] = company.id
    contact_id = contact_data.pop('tc2_sr_id')
    contact, created = await Contact.get_or_create(tc2_sr_id=contact_id, defaults=contact_data)
    if not created:
        contact = await contact.update_from_dict(contact_data)
        await contact.save()
    return created, contact


async def _get_or_create_deal(company: Company, contact: Contact | None) -> Deal:
    """
    Get or create an Open deal.
    always update the inherited custom fields on the deal.
    """

    deal = await Deal.filter(company_id=company.id, status=Deal.STATUS_OPEN).first()
    config = await get_config()
    if not deal:
        match company.price_plan:
            case Company.PP_PAYG:
                pipeline = await config.payg_pipeline
            case Company.PP_STARTUP:
                pipeline = await config.startup_pipeline
            case Company.PP_ENTERPRISE:
                pipeline = await config.enterprise_pipeline
            case _:
                raise ValueError(f'Unknown price plan {company.price_plan}')

        deal = await Deal.create(
            company_id=company.id,
            contact_id=contact and contact.id,
            name=company.name,
            pipeline_id=pipeline.id,
            admin_id=company.sales_person_id,
            stage_id=pipeline.dft_entry_stage_id,
        )

    # update the inherited custom fields on the deal
    deal_custom_fields = await CustomField.filter(linked_object_type='Deal')
    deal_custom_field_machine_names = [cf.machine_name for cf in deal_custom_fields]
    company_custom_fields_to_inherit = (
        await CustomField.filter(linked_object_type='Company', machine_name__in=deal_custom_field_machine_names)
        .exclude(machine_name='hermes_id')
        .prefetch_related('values')
    )

    for cf in company_custom_fields_to_inherit:
        if cf.values:
            deal_cf = next((dcf for dcf in deal_custom_fields if dcf.machine_name == cf.machine_name), None)
            if deal_cf:
                await CustomFieldValue.update_or_create(
                    **{'custom_field_id': deal_cf.id, 'deal': deal, 'defaults': {'value': cf.values[0].value}}
                )

        else:
            # these custom fields values are not stored on the model.
            if cf.hermes_field_name:
                # get the associated deal custom field
                deal_cf = next((dcf for dcf in deal_custom_fields if dcf.machine_name == cf.machine_name), None)
                if cf.field_type == CustomField.TYPE_FK_FIELD:
                    val = getattr(company, f'{cf.hermes_field_name}_id', None)
                else:
                    val = getattr(company, cf.hermes_field_name, None)
                if deal_cf and val:
                    await CustomFieldValue.update_or_create(
                        **{'custom_field_id': deal_cf.id, 'deal': deal, 'defaults': {'value': val}}
                    )

    return deal


async def update_from_client_event(
    tc2_subject: TCSubject | TCClient, create_deal: bool = True
) -> tuple[(Company | None), (Deal | None)]:
    """
    When an action happens in TC where the subject is a Client, we check to see if we need to update the Company/Contact
    in our db. if the Client is a narc, then we delete the Company and all related objects.
    """
    if isinstance(tc2_subject, TCSubject):
        try:
            tc2_client = TCClient(**tc2_subject.model_dump())
        except ValidationError as e:
            # If the user has been deleted, then we'll only get very simple data about them in the webhook. Therefore
            # we know to delete their details from our database.
            try:
                tc2_client = _TCSimpleRole(**tc2_subject.model_dump())
            except ValidationError:
                raise e
            else:
                company = await Company.get_or_none(tc2_cligency_id=tc2_client.id)
                if company:
                    await company.delete()
                    app_logger.info(f'Company {company} and related contacts/deals/meetings deleted')
                return None, None
    else:
        tc2_client = tc2_subject
    deal, contact = None, None
    await tc2_client.a_validate()
    company_created, company = await _create_or_update_company(tc2_client)
    if not company.narc:
        tc2_agency = tc2_client.meta_agency
        contacts_created, contacts_updated = [], []
        for i, recipient in enumerate(tc2_client.paid_recipients):
            if i == 0 and company_created and not recipient.email:
                recipient.email = tc2_client.user.email

            contact_created, contact = await _create_or_update_contact(recipient, company=company)
            if contact_created:
                contacts_created.append(contact)
            else:
                contacts_updated.append(contact)

        should_create_deal = (
            create_deal
            and tc2_agency
            and tc2_agency.status in [Company.STATUS_PENDING_EMAIL_CONF, Company.STATUS_TRIAL]
            and tc2_agency.created > datetime.now().replace(tzinfo=utc) - timedelta(days=90)
            and tc2_agency.paid_invoice_count == 0
            and tc2_client.sales_person
        )
        if should_create_deal:
            deal = await _get_or_create_deal(company, contact)
    else:
        contacts_created, contacts_updated, deal = [], [], None
    app_logger.info(
        f'Company {company} {"created" if company_created else "updated"}:, '
        f'Contacts created: {contacts_created}, '
        f'Contacts updated: {contacts_updated}'
        f'Deal created: {deal}'
    )
    return company, deal


async def update_from_invoice_event(tc2_subject: TCSubject):
    """
    As above, but we also check when an invoice changes in some way (as we have the paid_invoice_count on a Company).
    """
    tc2_invoice = TCInvoice(**tc2_subject.model_dump())
    tc2_client_subject = TCSubject(**await tc2_request(f'clients/{tc2_invoice.client.id}'))
    return await update_from_client_event(tc2_client_subject)
