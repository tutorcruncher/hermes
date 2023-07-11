from app.models import Companies, Contacts, Meetings
from app.pipedrive.api import create_or_update_organisation, create_or_update_person


async def check_update_pipedrive(company: Companies, contact: Contacts):
    """
    Checks if we need to update pipedrive for this company/contact.
    """
    await create_or_update_organisation(company)
    await create_or_update_person(contact)


async def post_sales_call(company: Companies, contact: Contacts, meeting: Meetings):
    """
    Called after a sales call is booked. Creates/updates the Org & Person in pipedrive then creates the activity.
    """
    await create_or_update_organisation(company)
    await create_or_update_person(contact)
    await create_activity(meeting)


async def post_support_call(company: Companies, contact: Contacts, meeting: Meetings):
    """
    Called after a support call is booked. Creates the activity if the company/contact have a pipedrive id
    """
    await create_or_update_person(contact)
    await create_pipedrive_activity(meeting)


async def create_pipedrive_activity(meeting: Meetings):
    """
    Creates a new activity within Pipedrive.
    """
    # TODO
