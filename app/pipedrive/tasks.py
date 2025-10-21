import logging
from datetime import datetime

import logfire
from sqlmodel import select

from app.core.database import get_session
from app.main_app.models import Company, Contact, Deal, Meeting
from app.pipedrive import api
from app.pipedrive.field_mappings import COMPANY_PD_FIELD_MAP, CONTACT_PD_FIELD_MAP, DEAL_PD_FIELD_MAP

logger = logging.getLogger('hermes.pipedrive')


async def sync_company_to_pipedrive(company_id: int):
    """
    Sync company and related data to Pipedrive.
    This is called after TC2 or Callbooker updates.
    """
    with logfire.span('sync_company_to_pipedrive'):
        db = get_session()
        try:
            company = db.get(Company, company_id)
            if not company:
                logger.warning(f'Company {company_id} not found, skipping sync')
                return

            # Sync organization
            await sync_organization(company, db)

            # Sync all contacts
            statement = select(Contact).where(Contact.company_id == company_id)
            contacts = db.exec(statement).all()
            for contact in contacts:
                await sync_person(contact, db)

            # Sync all deals
            statement = select(Deal).where(Deal.company_id == company_id)
            deals = db.exec(statement).all()
            for deal in deals:
                await sync_deal(deal, db)

            logger.info(f'Successfully synced company {company_id} to Pipedrive')
        except Exception as e:
            logger.error(f'Error syncing company {company_id}: {e}', exc_info=True)
        finally:
            db.close()


async def sync_organization(company: Company, db):
    """Sync a single organization to Pipedrive"""
    org_data = _company_to_org_data(company)

    if company.pd_org_id:
        # Update existing organization
        try:
            # Get current data from Pipedrive
            pd_org = await api.get_organisation(company.pd_org_id)
            current_data = pd_org.get('data', {})

            # Calculate changed fields
            changed_fields = api.get_changed_fields(current_data, org_data)

            if changed_fields:
                await api.update_organisation(company.pd_org_id, changed_fields)
                logger.info(f'Updated organization {company.pd_org_id} for company {company.id}')
        except Exception as e:
            logger.error(f'Error updating organization {company.pd_org_id}: {e}')
            # If organization doesn't exist in Pipedrive, create it
            if '404' in str(e) or '410' in str(e):
                company.pd_org_id = None
                db.add(company)
                db.commit()

    if not company.pd_org_id:
        # Create new organization
        try:
            result = await api.create_organisation(org_data)
            company.pd_org_id = result['data']['id']
            db.add(company)
            db.commit()
            logger.info(f'Created organization {company.pd_org_id} for company {company.id}')
        except Exception as e:
            logger.error(f'Error creating organization for company {company.id}: {e}')


async def sync_person(contact: Contact, db):
    """Sync a single person to Pipedrive"""
    person_data = _contact_to_person_data(contact, db)

    if contact.pd_person_id:
        # Update existing person
        try:
            pd_person = await api.get_person(contact.pd_person_id)
            current_data = pd_person.get('data', {})

            changed_fields = api.get_changed_fields(current_data, person_data)

            if changed_fields:
                await api.update_person(contact.pd_person_id, changed_fields)
                logger.info(f'Updated person {contact.pd_person_id} for contact {contact.id}')
        except Exception as e:
            logger.error(f'Error updating person {contact.pd_person_id}: {e}')
            if '404' in str(e) or '410' in str(e):
                contact.pd_person_id = None
                db.add(contact)
                db.commit()

    if not contact.pd_person_id:
        # Create new person
        try:
            result = await api.create_person(person_data)
            contact.pd_person_id = result['data']['id']
            db.add(contact)
            db.commit()
            logger.info(f'Created person {contact.pd_person_id} for contact {contact.id}')
        except Exception as e:
            logger.error(f'Error creating person for contact {contact.id}: {e}')


async def sync_deal(deal: Deal, db):
    """Sync a single deal to Pipedrive"""
    deal_data = _deal_to_pd_data(deal, db)

    if deal.pd_deal_id:
        # Update existing deal
        try:
            pd_deal = await api.get_deal(deal.pd_deal_id)
            current_data = pd_deal.get('data', {})

            changed_fields = api.get_changed_fields(current_data, deal_data)

            if changed_fields:
                await api.update_deal(deal.pd_deal_id, changed_fields)
                logger.info(f'Updated deal {deal.pd_deal_id} for deal {deal.id}')
        except Exception as e:
            logger.error(f'Error updating deal {deal.pd_deal_id}: {e}')
            if '404' in str(e) or '410' in str(e):
                deal.pd_deal_id = None
                db.add(deal)
                db.commit()

    if not deal.pd_deal_id:
        # Create new deal
        try:
            result = await api.create_deal(deal_data)
            deal.pd_deal_id = result['data']['id']
            db.add(deal)
            db.commit()
            logger.info(f'Created deal {deal.pd_deal_id} for deal {deal.id}')
        except Exception as e:
            logger.error(f'Error creating deal for deal {deal.id}: {e}')


async def sync_meeting_to_pipedrive(meeting_id: int):
    """Sync a meeting as an activity to Pipedrive"""
    with logfire.span('sync_meeting_to_pipedrive'):
        db = get_session()
        try:
            meeting = db.get(Meeting, meeting_id)
            if not meeting:
                logger.warning(f'Meeting {meeting_id} not found, skipping sync')
                return

            activity_data = _meeting_to_activity_data(meeting, db)
            result = await api.create_activity(activity_data)
            logger.info(f'Created activity {result["data"]["id"]} for meeting {meeting_id}')
        except Exception as e:
            logger.error(f'Error syncing meeting {meeting_id}: {e}', exc_info=True)
        finally:
            db.close()


async def purge_company_from_pipedrive(company_id: int):
    """Delete a company and all related data from Pipedrive (for NARC companies)"""
    with logfire.span('purge_company_from_pipedrive'):
        db = get_session()
        try:
            company = db.get(Company, company_id)
            if not company:
                return

            # Delete organization
            if company.pd_org_id:
                try:
                    await api.delete_organisation(company.pd_org_id)
                    logger.info(f'Deleted organization {company.pd_org_id}')
                except Exception as e:
                    logger.error(f'Error deleting organization {company.pd_org_id}: {e}')

            logger.info(f'Purged company {company_id} from Pipedrive')
        except Exception as e:
            logger.error(f'Error purging company {company_id}: {e}', exc_info=True)
        finally:
            db.close()


def _company_to_org_data(company: Company) -> dict:
    """Convert Company model to Pipedrive organization data"""
    data = {
        'name': company.name,
        'owner_id': company.sales_person.pd_owner_id if company.sales_person else None,
        'address_country': company.country,
    }

    # Build custom_fields using field mapping
    custom_fields = {}

    # Map fields to Pipedrive field IDs
    for field_name, pd_field_id in COMPANY_PD_FIELD_MAP.items():
        if field_name == 'hermes_id':
            value = company.id
        elif field_name == 'tc2_cligency_url':
            value = company.tc2_cligency_url
        else:
            value = getattr(company, field_name, None)

        if value is not None:
            # Convert datetime to ISO date string
            if isinstance(value, datetime):
                value = value.date().isoformat()
            custom_fields[pd_field_id] = value

    data['custom_fields'] = custom_fields
    return data


def _contact_to_person_data(contact: Contact, db) -> dict:
    """Convert Contact model to Pipedrive person data"""
    company = db.get(Company, contact.company_id)

    data = {
        'name': contact.name,
        'email': [contact.email] if contact.email else [],
        'phone': contact.phone,
        'org_id': company.pd_org_id if company else None,
        'owner_id': company.sales_person.pd_owner_id if (company and company.sales_person) else None,
    }

    # Add custom fields
    custom_fields = {}
    for field_name, pd_field_id in CONTACT_PD_FIELD_MAP.items():
        if field_name == 'hermes_id':
            custom_fields[pd_field_id] = contact.id

    data['custom_fields'] = custom_fields
    return data


def _deal_to_pd_data(deal: Deal, db) -> dict:
    """Convert Deal model to Pipedrive deal data"""
    company = db.get(Company, deal.company_id) if deal.company_id else None
    contact = db.get(Contact, deal.contact_id) if deal.contact_id else None

    data = {
        'title': deal.name,
        'org_id': company.pd_org_id if company else None,
        'person_id': contact.pd_person_id if contact else None,
        'user_id': deal.admin.pd_owner_id if deal.admin else None,
        'pipeline_id': deal.pipeline.pd_pipeline_id if deal.pipeline else None,
        'stage_id': deal.stage.pd_stage_id if deal.stage else None,
        'status': deal.status,
    }

    # Build custom_fields using field mapping
    custom_fields = {}

    # Map fields to Pipedrive field IDs
    for field_name, pd_field_id in DEAL_PD_FIELD_MAP.items():
        if field_name == 'hermes_id':
            value = deal.id
        elif field_name == 'tc2_cligency_url':
            # Get from company
            value = company.tc2_cligency_url if company else None
        else:
            value = getattr(deal, field_name, None)

        if value is not None:
            custom_fields[pd_field_id] = value

    data['custom_fields'] = custom_fields
    return data


def _meeting_to_activity_data(meeting: Meeting, db) -> dict:
    """Convert Meeting model to Pipedrive activity data"""
    contact = db.get(Contact, meeting.contact_id)
    company = db.get(Company, meeting.company_id) if meeting.company_id else None

    data = {
        'due_date': meeting.start_time.strftime('%Y-%m-%d') if meeting.start_time else None,
        'due_time': meeting.start_time.strftime('%H:%M') if meeting.start_time else None,
        'subject': meeting.name,
        'user_id': meeting.admin.pd_owner_id if meeting.admin else None,
        'person_id': contact.pd_person_id if contact else None,
        'org_id': company.pd_org_id if company else None,
    }

    if meeting.deal_id:
        deal = db.get(Deal, meeting.deal_id)
        if deal and deal.pd_deal_id:
            data['deal_id'] = deal.pd_deal_id

    return data
