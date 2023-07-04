from app.tutorcruncher2._utils import app_logger
from app.tutorcruncher2._schema import TCClient, TCRecipient, ClientDeletedError, TCSubject, TCInvoice
from app.tutorcruncher2.api import tc_request

from app.models import Companies, Contacts, Admins


async def _create_or_update_company(tc_client: TCClient) -> tuple[bool, Companies]:
    company_data = tc_client.dict()
    admin_lu = {a.id: a for a in await Admins.all()}
    for f in ['client_manager', 'sales_person', 'bdr_person']:
        if not (company_data[f] and company_data[f] in admin_lu):
            company_data.pop(f)
    company, created = await Companies.get_or_create(tc_agency_id=tc_client.meta_agency.id, defaults=company_data)
    if not created:
        company = await company.update_from_dict(**tc_client.dict())
        await company.save()
    return created, company


async def _get_or_create_contact(tc_sr: TCRecipient) -> tuple[bool, Contacts]:
    contact = await Contacts.filter(tc_sr_id=tc_sr.id)
    created = False
    if not contact:
        contact_data = tc_sr.dict()
        contact_data['tc_sr_id'] = contact_data.pop('id')
        contact = await Contacts.create(**contact_data)
        created = True

    return created, contact


async def _create_or_update_contact(tc_sr: TCRecipient) -> tuple[bool, Contacts]:
    created, contact = _get_or_create_contact(tc_sr)
    if not created:
        contact = await contact.update_from_dict(**tc_sr.dict())
        await contact.save()
    return created, contact


async def update_from_client_event(tc_subject: TCSubject):
    try:
        tc_client = TCClient(**tc_subject.dict())
    except ClientDeletedError:
        client = await Contacts.get(tc_cligency_id=tc_subject.id)
        await client.company.delete()
        app_logger.info(f'Company {client.company} and related contacts/deals/meetings deleted')
    else:
        company_created, company = _create_or_update_company(tc_client)
        contacts_created, contacts_updated = [], []
        for recipient in tc_client.paid_recipients:
            contact_created, contact = _create_or_update_contact(recipient)
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
