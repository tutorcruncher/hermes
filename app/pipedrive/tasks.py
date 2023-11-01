from app.models import Company, Contact, Deal, Meeting
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
