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
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl

import requests
import logfire

from app.models import Company, Contact, Deal, Meeting
from app.pipedrive._schema import Activity, Organisation, PDDeal, Person
from app.pipedrive._utils import app_logger
from app.tc2._process import get_or_create_deal
from app.utils import settings

session = requests.Session()


async def pipedrive_request(url: str, *, method: str = 'GET', data: dict = None) -> dict:
    # Parse the URL and convert to list
    url_parts = list(urlparse(url))

    # Parse the existing query params
    query_params = dict(parse_qsl(url_parts[4]))

    # Add the API token to the query params
    query_params.update({'api_token': settings.pd_api_key})

    # Encode the query params and add back to the URL
    url_parts[4] = urlencode(query_params)

    # Construct the final URL
    final_url = urlunparse(url_parts)
    debug(f'{settings.pd_base_url}/api/v1/{final_url}')
    r = session.request(method=method, url=f'{settings.pd_base_url}/api/v1/{final_url}', data=data)
    app_logger.debug('Request to url %s: %r', url, data)
    logfire.debug('Pipedrive request to url: {url=}: {data=}', url=url, data=data)
    app_logger.debug('Response: %r', r.json())
    r.raise_for_status()
    app_logger.info('Request method=%s url=%s status_code=%s', method, url, r.status_code)
    logfire.debug(
        'Pipedrive request method={method=} url={url=} status_code={status_code=}',
        method=method,
        url=url,
        status_code=r.status_code,
    )
    r.raise_for_status()
    return r.json()


async def create_or_update_organisation(company: Company) -> Organisation | None:
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
        # if company is not linked to pipedrive, compare the org name with all orgs in pipedrive
        # if there is a match, link the company to the org and update the org
        if company.tc2_cligency_id:
            tc2_cligency_url = f'{settings.tc2_base_url}/clients/{company.tc2_cligency_id}/'
            pd_response = await pipedrive_request(f'organizations/search?term={tc2_cligency_url}&exact_match=True'
                                                  f'&limit=1')
            search_item = pd_response['data']['items'][0]['item'] if pd_response['data']['items'] else None
            if search_item:
                debug('found this org:')
                debug(search_item)
                company.pd_org_id = search_item['id']
                company.winback = True
                await company.save()
                await pipedrive_request(f'organizations/{company.pd_org_id}', method='PUT', data=hermes_org_data)
                app_logger.info('Updated lost pd org %s from company %s', company.pd_org_id, company.id)
                debug('updating with this data:')
                debug(hermes_org_data)
                return

        # if company is not linked to pipedrive and there is no match, create a new org
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


async def create_or_update_person(contact: Contact, company: Company | None) -> Person | None:
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
        return pipedrive_person
    else:
        if company and company.winback:
            debug(company.winback)
            # get the Person by email
            pd_response = await pipedrive_request(f'persons/search?term={contact.email}&organization_id={company.pd_org_id}&limit=1')
            search_item = pd_response['data']['items'][0]['item'] if pd_response['data']['items'] else None
            if search_item:
                debug('found this person:')
                debug(search_item)
                contact.pd_person_id = search_item['id']
                await contact.save()
                debug('updating with this data:')
                debug(hermes_person_data)
                await pipedrive_request(f'persons/{contact.pd_person_id}', method='PUT', data=hermes_person_data)
                app_logger.info('Updated person %s from contact %s', contact.pd_person_id, contact.id)
                return

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


async def get_or_create_pd_deal(deal: Deal, company: Company | None) -> PDDeal:
    """
    Creates a new deal if none exists within Pipedrive.
    """
    if not deal:
        if company and company.winback:
            first_contact_with_pd_person_id = next(
                (contact for contact in await company.contacts if contact.pd_person_id), None)
            deal = await get_or_create_deal(company, first_contact_with_pd_person_id)
            pd_deal = await PDDeal.from_deal(deal)
            pd_deal_data = pd_deal.model_dump(by_alias=True)
            pd_response = await pipedrive_request(f'organizations/{company.pd_org_id}/deals?start=0&limit=1&status=all_not_deleted&sort=update_time DESC&only_primary_association=1')
            search_item = pd_response['data']
            if search_item:
                debug('deal we are updating:')
                debug(search_item)
                deal.pd_deal_id = search_item['id']
                await deal.save()
                await pipedrive_request(f'deals/{deal.pd_deal_id}', method='PUT', data=pd_deal_data)
                app_logger.info('Found deal %s from deal %s', deal.pd_deal_id, deal.id)
                debug('updating with this data:')
                debug(pd_deal_data)
                return pd_deal

    else:
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
