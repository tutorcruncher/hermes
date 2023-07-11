from app.models import Companies, Contacts, Meetings
from app.pipedrive.api import create_or_update_organisation, create_or_update_person


async def check_update_pipedrive(company: Companies, contact: Contacts):
    """
    Checks if we need to update pipedrive for this company/contact.
    """
    await create_or_update_organisation(company)
    await create_or_update_person(contact)


async def create_pipedrive_activity(meeting: Meetings):
    """
    Creates a new activity within Pipedrive.
    """
    # TODO
