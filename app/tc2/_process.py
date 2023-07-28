from pydantic import ValidationError

from app.models import Company, Contact
from app.tc2._schema import TCClient, TCInvoice, TCRecipient, TCSubject, _TCSimpleRole
from app.tc2._utils import app_logger
from app.tc2.api import tc2_request


async def _create_or_update_company(tc_client: TCClient) -> tuple[bool, Company]:
    """
    Creates or updates a Company in our database from a TutorCruncher client/meta_agency.
    """
    company_data = tc_client.company_dict()
    company_id = company_data.pop('tc_agency_id')
    company, created = await Company.get_or_create(tc_agency_id=company_id, defaults=company_data)
    if not created:
        company = await company.update_from_dict(company_data)
        await company.save()
    return created, company


async def _create_or_update_contact(tc_sr: TCRecipient, company: Company) -> tuple[bool, Contact]:
    """
    Creates or updates a Contact in our database from a TutorCruncher SR (linked to a Cligency).
    """
    contact_data = tc_sr.contact_dict()
    contact_data['company_id'] = company.id
    contact_id = contact_data.pop('tc_sr_id')
    contact, created = await Contact.get_or_create(tc_sr_id=contact_id, defaults=contact_data)
    if not created:
        contact = await contact.update_from_dict(contact_data)
        await contact.save()
    return created, contact


async def update_from_client_event(tc_subject: TCSubject | TCClient) -> Company | None:
    """
    When an action happens in TC where the subject is a Client, we check to see if we need to update the Company/Contact
    in our db.
    """
    try:
        tc_client = TCClient(**tc_subject.dict())
    except ValidationError as e:
        # If the user has been deleted, then we'll only get very simple data about them in the webhook. Therefore
        # we know to delete their details from our database.
        try:
            tc_client = _TCSimpleRole(**tc_subject.dict())
        except ValidationError:
            raise e
        else:
            company = await Company.get_or_none(tc_cligency_id=tc_client.id)
            if company:
                await company.delete()
                app_logger.info(f'Company {company} and related contacts/deals/meetings deleted')
    else:
        await tc_client.a_validate()
        if tc_client.meta_agency.paid_invoice_count > 4:
            # Any company that has more than 4 paid invoices is a long term customer and we don't care.
            return
        company_created, company = await _create_or_update_company(tc_client)
        contacts_created, contacts_updated = [], []
        for recipient in tc_client.paid_recipients:
            contact_created, contact = await _create_or_update_contact(recipient, company=company)
            if contact_created:
                contacts_created.append(contact)
            else:
                contacts_updated.append(contact)
        app_logger.info(
            f'Company {company} {"created" if company_created else "updated"}:, '
            f'Contacts created: {contacts_created}, '
            f'Contacts updated: {contacts_updated}'
        )
        return company


async def update_from_invoice_event(tc_subject: TCSubject):
    """
    As above, but we also check when an invoice changes in some way (as we have the paid_invoice_count on a Company).
    """
    tc_invoice = TCInvoice(**tc_subject.dict())
    tc_client_subject = TCSubject(**await tc2_request(f'clients/{tc_invoice.client.id}'))
    await update_from_client_event(tc_client_subject)
