from pydantic import ValidationError

from app.models import Admins, Companies, Contacts
from app.tutorcruncher2._schema import TCClient, TCInvoice, TCRecipient, TCSubject, _TCSimpleUser
from app.tutorcruncher2._utils import app_logger
from app.tutorcruncher2.api import tc_request


async def _create_or_update_company(tc_client: TCClient) -> tuple[bool, Companies]:
    company_data = tc_client.dict()
    admin_lu = {a.tc_admin_id: a for a in await Admins.all()}

    # TODO: We should do proper validation on these fields.
    # This checks that, if the one of the fields is set for the company, we have a matching admin in our database.
    for f in ['client_manager', 'sales_person', 'bdr_person']:
        if company_data[f] is not None:
            if company_data[f] in admin_lu:
                company_data[f] = admin_lu[company_data[f]]
            else:
                company_data.pop(f)

    company_id = company_data.pop('tc_agency_id')
    company, created = await Companies.get_or_create(tc_agency_id=company_id, defaults=company_data)
    if not created:
        company = await company.update_from_dict(company_data)
        await company.save()
    return created, company


async def _create_or_update_contact(tc_sr: TCRecipient, company: Companies) -> tuple[bool, Contacts]:
    contact_data = tc_sr.dict()
    contact_data['company_id'] = company.id
    contact_id = contact_data.pop('tc_sr_id')
    contact, created = await Contacts.get_or_create(tc_sr_id=contact_id, defaults=contact_data)
    if not created:
        contact = await contact.update_from_dict(contact_data)
        await contact.save()
    return created, contact


async def update_from_client_event(tc_subject: TCSubject):
    try:
        tc_client = TCClient(**tc_subject.dict())
    except ValidationError as e:
        # If the user has been deleted, then we'll only get very simple data about them in the webhook. Therefore
        # we know to delete their details from our database.
        try:
            tc_client = _TCSimpleUser(**tc_subject.dict())
        except ValidationError:
            raise e
        else:
            company = await Companies.get_or_none(tc_cligency_id=tc_client.id)
            if company:
                await company.delete()
                app_logger.info(f'Company {company} and related contacts/deals/meetings deleted')
    else:
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


async def update_from_invoice_event(tc_subject: TCSubject):
    tc_invoice = TCInvoice(**tc_subject.dict())
    tc_client_subject = TCSubject(**await tc_request(f'clients/{tc_invoice.client.id}'))
    await update_from_client_event(tc_client_subject)
