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
        try:
            with get_session() as db:
                company = db.get(Company, company_id)
                if not company:
                    logger.warning(f'Company {company_id} not found, skipping sync')
                    return
                if company.is_deleted:
                    logger.info(f'Company {company_id} is marked as deleted, skipping sync')
                    return

                contact_ids = [c.id for c in db.exec(select(Contact).where(Contact.company_id == company_id)).all()]
                if company.paid_invoice_count == 0:
                    # sync deals only when the agency has no paid invoices
                    deal_ids = [
                        d.id
                        for d in db.exec(
                            select(Deal).where(
                                Deal.company_id == company_id,
                                (Deal.pd_deal_id.is_not(None)) | (Deal.status == Deal.STATUS_OPEN),
                            )
                        ).all()
                    ]
                else:
                    deal_ids = []

            await sync_organization(company_id)

            for contact_id in contact_ids:
                await sync_person(contact_id)

            for deal_id in deal_ids:
                await sync_deal(deal_id)

            logger.info(f'Successfully synced company {company_id} to Pipedrive')
        except Exception as e:
            logger.error(f'Error syncing company {company_id}: {e}', exc_info=True)


async def sync_organization(company_id: int):
    """Sync a single organization to Pipedrive"""
    with get_session() as db:
        company = db.get(Company, company_id)
        if not company:
            return
        org_data = _company_to_org_data(company)
        pd_org_id = company.pd_org_id

    if pd_org_id:
        try:
            pd_org = await api.get_organisation(pd_org_id)
            current_data = pd_org.get('data', {})
            changed_fields = api.get_changed_fields(current_data, org_data)

            if changed_fields:
                await api.update_organisation(pd_org_id, changed_fields)
                logger.info(f'Updated organization {pd_org_id} for company {company_id}')
        except Exception as e:
            logger.error(f'Error updating organization {pd_org_id}: {e}')
            if '404' in str(e) or '410' in str(e):
                pd_org_id = None
            else:
                raise

    if not pd_org_id:
        try:
            result = await api.create_organisation(org_data)
            new_pd_org_id = result['data']['id']

            with get_session() as db:
                company = db.get(Company, company_id)
                if company:
                    company.pd_org_id = new_pd_org_id
                    db.add(company)
                    db.commit()

            logger.info(f'Created organization {new_pd_org_id} for company {company_id}')
        except Exception as e:
            logger.error(f'Error creating organization for company {company_id}: {e}')
            raise


async def sync_person(contact_id: int):
    """Sync a single person to Pipedrive"""
    with get_session() as db:
        contact = db.get(Contact, contact_id)
        if not contact:
            return
        person_data = _contact_to_person_data(contact, db)
        pd_person_id = contact.pd_person_id

    if pd_person_id:
        try:
            pd_person = await api.get_person(pd_person_id)
            current_data = pd_person.get('data', {})
            changed_fields = api.get_changed_fields(current_data, person_data)

            if changed_fields:
                await api.update_person(pd_person_id, changed_fields)
                logger.info(f'Updated person {pd_person_id} for contact {contact_id}')
        except Exception as e:
            logger.error(f'Error updating person {pd_person_id}: {e}')
            if '404' in str(e) or '410' in str(e):
                pd_person_id = None

    if not pd_person_id:
        try:
            result = await api.create_person(person_data)
            new_pd_person_id = result['data']['id']

            with get_session() as db:
                contact = db.get(Contact, contact_id)
                if contact:
                    contact.pd_person_id = new_pd_person_id
                    db.add(contact)
                    db.commit()

            logger.info(f'Created person {new_pd_person_id} for contact {contact_id}')
        except Exception as e:
            logger.error(f'Error creating person for contact {contact_id}: {e}')


async def sync_deal(deal_id: int):
    """Sync a single deal to Pipedrive"""
    from app.core.config import settings

    with get_session() as db:
        deal = db.get(Deal, deal_id)
        if not deal:
            return
        deal_data = _deal_to_pd_data(deal, db)
        pd_deal_id = deal.pd_deal_id

    if pd_deal_id:
        try:
            pd_deal = await api.get_deal(pd_deal_id)
            current_data = pd_deal.get('data', {})
            changed_fields = api.get_changed_fields(current_data, deal_data)

            pd_status = current_data.get('status')
            hermes_status = deal_data.get('status')

            # only update deals when an 'open' deal on hermes is actually 'open' on PD
            if (
                pd_status
                and pd_status != Deal.STATUS_OPEN
                and hermes_status == Deal.STATUS_OPEN
                and 'status' in changed_fields
            ):
                logger.info(f'Skipping update for deal {deal_id} because PipeDrive status {pd_status} is not open')
                return

            if changed_fields:
                await api.update_deal(pd_deal_id, changed_fields)
                logger.info(f'Updated deal {pd_deal_id} for deal {deal_id}')
        except Exception as e:
            logger.error(f'Error updating deal {pd_deal_id}: {e}')

    if not pd_deal_id:
        if not settings.sync_create_deals:
            logger.warning(f'Deal {deal_id} has no pd_deal_id, skipping sync (deal creation disabled)')
            return

        try:
            result = await api.create_deal(deal_data)
            new_pd_deal_id = result['data']['id']

            with get_session() as db:
                deal = db.get(Deal, deal_id)
                if deal:
                    deal.pd_deal_id = new_pd_deal_id
                    db.add(deal)
                    db.commit()

            logger.info(f'Created deal {new_pd_deal_id} for deal {deal_id}')
        except Exception as e:
            logger.error(f'Error creating deal for deal {deal_id}: {e}')


async def sync_meeting_to_pipedrive(meeting_id: int):
    """Sync a meeting as an activity to Pipedrive"""
    with logfire.span('sync_meeting_to_pipedrive'):
        try:
            # Fetch meeting data with short-lived connection
            with get_session() as db:
                meeting = db.get(Meeting, meeting_id)
                if not meeting:
                    logger.warning(f'Meeting {meeting_id} not found, skipping sync')
                    return
                activity_data = _meeting_to_activity_data(meeting, db)

            # Make API call without holding database connection
            result = await api.create_activity(activity_data)
            logger.info(f'Created activity {result["data"]["id"]} for meeting {meeting_id}')
        except Exception as e:
            logger.error(f'Error syncing meeting {meeting_id}: {e}', exc_info=True)


async def purge_company_from_pipedrive(company_id: int):
    """Delete a company and all related data from Pipedrive (for NARC companies)"""
    with logfire.span('purge_company_from_pipedrive'):
        try:
            with get_session() as db:
                company = db.get(Company, company_id)
                if not company:
                    return
                pd_org_id = company.pd_org_id

            if pd_org_id:
                try:
                    await api.delete_organisation(pd_org_id)
                    logger.info(f'Deleted organization {pd_org_id}')
                except Exception as e:
                    logger.error(f'Error deleting organization {pd_org_id}: {e}')

            logger.info(f'Purged company {company_id} from Pipedrive')
        except Exception as e:
            logger.error(f'Error purging company {company_id}: {e}', exc_info=True)


def _company_to_org_data(company: Company) -> dict:
    """Convert Company model to Pipedrive organization data"""
    data = {
        'name': company.name,
        'owner_id': company.sales_person.pd_owner_id if company.sales_person else None,
    }

    # Only include address if country is set
    # Note: Pipedrive v2 requires 'value' field when 'country' is provided
    if company.country:
        data['address'] = {'value': company.country, 'country': company.country}

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

        if value is not None and value != '':
            # Convert datetime to ISO date string
            if isinstance(value, datetime):
                value = value.date().isoformat()
            # Convert integers to strings for hermes_id and paid_invoice_count (text fields in Pipedrive)
            elif field_name in ('hermes_id', 'paid_invoice_count') and isinstance(value, int):
                value = str(value)
            custom_fields[pd_field_id] = value

    data['custom_fields'] = custom_fields
    return data


def _contact_to_person_data(contact: Contact, db) -> dict:
    """Convert Contact model to Pipedrive person data"""
    company = db.get(Company, contact.company_id)

    data = {
        'name': contact.name,
        'org_id': company.pd_org_id if company else None,
        'owner_id': company.sales_person.pd_owner_id if (company and company.sales_person) else None,
    }

    if contact.email:
        data['emails'] = [{'value': contact.email, 'label': 'work', 'primary': True}]

    if contact.phone:
        data['phones'] = [{'value': contact.phone, 'label': 'work', 'primary': True}]

    # Add custom fields
    custom_fields = {}
    for field_name, pd_field_id in CONTACT_PD_FIELD_MAP.items():
        if field_name == 'hermes_id':
            custom_fields[pd_field_id] = str(contact.id)

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
        'owner_id': deal.admin.pd_owner_id if deal.admin else None,
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

        if value is not None and value != '':
            # Convert integers to strings for hermes_id and paid_invoice_count (text fields in Pipedrive)
            if field_name in ('hermes_id', 'paid_invoice_count') and isinstance(value, int):
                value = str(value)
            custom_fields[pd_field_id] = value

    data['custom_fields'] = custom_fields
    return data


def _meeting_to_activity_data(meeting: Meeting, db) -> dict:
    """Convert Meeting model to Pipedrive activity data"""
    contact = db.get(Contact, meeting.contact_id)
    company = db.get(Company, meeting.company_id) if meeting.company_id else None

    data = {
        'type': 'meeting',
        'due_date': meeting.start_time.strftime('%Y-%m-%d') if meeting.start_time else None,
        'due_time': meeting.start_time.strftime('%H:%M') if meeting.start_time else None,
        'subject': meeting.name,
        'owner_id': meeting.admin.pd_owner_id if meeting.admin else None,
    }

    # Add participant
    if contact and contact.pd_person_id:
        data['participants'] = [{'person_id': contact.pd_person_id, 'primary': True}]

    # Add org_id if available
    if company and company.pd_org_id:
        data['org_id'] = company.pd_org_id

    if meeting.deal_id:
        deal = db.get(Deal, meeting.deal_id)
        if deal and deal.pd_deal_id:
            data['deal_id'] = deal.pd_deal_id

    return data
