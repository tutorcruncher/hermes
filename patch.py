from app.models import Contact
from app.pipedrive.api import create_or_update_person


async def update_all_contacts():
    """
    Updates all contacts in Pipedrive.
    """
    for contact in await Contact.all():
        await create_or_update_person(contact)


async def update_contact(c_id: int):
    """
    Updates a contact in Pipedrive.
    """
    contact = await Contact.get(id=c_id)
    await create_or_update_person(contact)
