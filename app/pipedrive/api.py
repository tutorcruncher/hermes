"""
We want to update the pipedrive person/org when:
- A TC meta client is updated/created/deleted
- A TC company is terminated/updated
- A TC meta invoice is created/updated/deleted
- A new sales/support call is created from the call booker
We want to update deals in pipedrive when:
- Nothing. This should be handled by us updating the person/org; there are then automations in pipedrive to update the
  deal/person/org.
We want to create activities in pipedrive when:
- A new sales/support call is created from the call booker
"""
import requests

from app.models import Company, Contact, Deal, Meeting
from app.pipedrive._schema import Activity, Organisation, PDDeal, Person
from app.pipedrive._utils import app_logger
from app.utils import settings

session = requests.Session()


async def pipedrive_request(url: str, *, method: str = 'GET', data: dict = None) -> dict:
    r = session.request(
        method=method, url=f'{settings.pd_base_url}/api/v1/{url}?api_token={settings.pd_api_key}', data=data
    )
    app_logger.debug('Request to url %s: %r', url, data)
    app_logger.debug('Response: %r', r.json())
    r.raise_for_status()
    app_logger.info('Request method=%s url=%s status_code=%s', method, url, r.status_code)
    r.raise_for_status()
    return r.json()


async def create_or_update_organisation(company: Company) -> Organisation:
    """
    Create or update an organisation within Pipedrive.
    """
    hermes_org = await Organisation.from_company(company)
    hermes_org_data = hermes_org.model_dump(by_alias=True)
    if company.pd_org_id:
        pipedrive_org = Organisation(**(await pipedrive_request(f'organizations/{company.pd_org_id}'))['data'])
        if hermes_org_data != pipedrive_org.model_dump(by_alias=True):
            await pipedrive_request(f'organizations/{company.pd_org_id}', method='PUT', data=hermes_org_data)
            app_logger.info('Updated org %s from company %s', company.pd_org_id, company.id)
    else:
        # if company is not on pipedrive, create it
        created_org = (await pipedrive_request('organizations', method='POST', data=hermes_org_data))['data']
        pipedrive_org = Organisation(**created_org)
        company.pd_org_id = pipedrive_org.id
        await company.save()
        app_logger.info('Created org %s from company %s', company.pd_org_id, company.id)
    return pipedrive_org


async def delete_organisation(company: Company):
    """
    Delete an organisation within Pipedrive.
    """
    if company.pd_org_id:
        try:
            await pipedrive_request(f'organizations/{company.pd_org_id}', method='DELETE')
            company.pd_org_id = None
            await company.save()
            app_logger.info('Deleted org %s from company %s', company.pd_org_id, company.id)
        except Exception as e:
            app_logger.error('Error deleting org %s', e)


async def create_or_update_person(contact: Contact) -> Person:
    """
    Create or update a Person within Pipedrive.
    """
    hermes_person = await Person.from_contact(contact)
    hermes_person_data = hermes_person.model_dump(by_alias=True)
    if contact.pd_person_id:
        pipedrive_person = Person(**(await pipedrive_request(f'persons/{contact.pd_person_id}'))['data'])
        if hermes_person_data != pipedrive_person.model_dump(by_alias=True):
            await pipedrive_request(f'persons/{contact.pd_person_id}', method='PUT', data=hermes_person_data)
            app_logger.info('Updated person %s from contact %s', contact.pd_person_id, contact.id)
    else:
        created_person = (await pipedrive_request('persons', method='POST', data=hermes_person_data))['data']
        pipedrive_person = Person(**created_person)
        contact.pd_person_id = pipedrive_person.id
        await contact.save()
        app_logger.info('Created person %s from contact %s', contact.pd_person_id, contact.id)
    return pipedrive_person


async def delete_persons(contacts: list[Contact]):
    """
    Delete a Person within Pipedrive.
    """
    pd_person_ids = [contact.pd_person_id for contact in contacts if contact.pd_person_id]
    if pd_person_ids:
        try:
            await pipedrive_request(f'persons/{",".join(map(str, pd_person_ids))}', method='DELETE')
            for contact in contacts:
                contact.pd_person_id = None
                await contact.save()
                app_logger.info('Deleted person %s from contact %s', contact.pd_person_id, contact.id)
        except Exception as e:
            app_logger.error('Error deleting persons %s', e)


async def get_or_create_pd_deal(deal: Deal) -> PDDeal:
    """
    Creates a new deal if none exists within Pipedrive.
    """
    pd_deal = await PDDeal.from_deal(deal)
    pd_deal_data = pd_deal.model_dump(by_alias=True)
    if not deal.pd_deal_id:
        pd_deal = PDDeal(**(await pipedrive_request('deals', method='POST', data=pd_deal_data))['data'])
        deal.pd_deal_id = pd_deal.id
        await deal.save()
    return pd_deal


async def delete_deal(deal: Deal):
    """
    Delete a deal within Pipedrive.
    """
    if deal.pd_deal_id:
        try:
            await pipedrive_request(f'deals/{deal.pd_deal_id}', method='DELETE')
            deal.pd_deal_id = None
            await deal.save()
            app_logger.info('Deleted deal %s from deal %s', deal.pd_deal_id, deal.id)
        except Exception as e:
            app_logger.error('Error deleting deal %s', e)


async def create_activity(meeting: Meeting, pipedrive_deal: PDDeal = None) -> Activity:
    """
    Creates a new activity within Pipedrive.
    """
    hermes_activity = await Activity.from_meeting(meeting)
    hermes_activity_data = hermes_activity.model_dump()
    if pipedrive_deal:
        hermes_activity_data['deal_id'] = pipedrive_deal.id
    created_activity = (await pipedrive_request('activities/', method='POST', data=hermes_activity_data))['data']
    activity = Activity(**created_activity)
    app_logger.info('Created activity for deal %s from meeting %s', activity.id, meeting.id)
    return activity
