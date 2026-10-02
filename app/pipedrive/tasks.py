import logging
from datetime import datetime

import httpx
import logfire
from sqlmodel import select

from app.core.database import DBSession, get_session
from app.core.locks import RedisLockRegistry
from app.main_app.models import Company, Contact, Deal, Meeting
from app.pipedrive import api
from app.pipedrive.field_mappings import (
    COMPANY_PD_ENUM_OPTION_MAP,
    COMPANY_PD_FIELD_MAP,
    CONTACT_PD_FIELD_MAP,
    DEAL_PD_FIELD_MAP,
)
from app.pipedrive.process import mark_deleted_from_pipedrive

logger = logging.getLogger('hermes.pipedrive')

SYNCABLE_DEAL_FIELDS = ['paid_invoice_count']  # these fields get synced from deal company

# Per-company locks to serialise concurrent syncs for the same company.
# A sync holds its lock while its Pipedrive calls queue behind every other sync's calls in the
# shared rate limiter, so during a TC2 burst a sync can hold it for over 1000s. The lease is renewed
# while held, so it only bounds how long a killed sync keeps the company locked. Waiters wait until
# the lock is released, and max_hold_seconds caps how long a stuck sync can keep it.
_company_sync_locks = RedisLockRegistry('hermes:company-lck', lease_timeout_seconds=300, max_hold_seconds=3600)


async def sync_company_to_pipedrive(company_id: int, booked_contact_id: int | None = None):
    """
    Sync company and related data to Pipedrive.
    This is called after TC2 or Callbooker updates.

    When Pipedrive no longer has the org, a person or a deal, it is marked deleted in Hermes, as the delete webhook
    would do. A sales call booking passes the booked contact, so the booking always reaches Pipedrive: the company
    and that contact are brought back if they were marked deleted, and a gone org or person is recreated.
    """
    recreate_on_404 = booked_contact_id is not None
    async with _company_sync_locks.acquire(company_id):
        with logfire.span('sync_company_to_pipedrive'):
            try:
                with get_session() as db:
                    company = db.get(Company, company_id)
                    if not company:
                        logger.warning(f'Company {company_id} not found, skipping sync')
                        return
                    if booked_contact_id:
                        _bring_back_for_booking(db, company, booked_contact_id)
                    if company.is_deleted:
                        logger.info(f'Company {company_id} is marked as deleted, skipping sync')
                        return

                    contact_ids = [
                        c.id
                        for c in db.exec(
                            select(Contact).where(Contact.company_id == company_id, Contact.is_deleted == False)  # noqa: E712
                        ).all()
                    ]

                    deal_query = select(Deal).where(Deal.company_id == company_id)
                    if not company.paid_invoice_count:
                        # Full sync for non-paying companies (update existing + create new open deals)
                        deal_query = deal_query.where(
                            (Deal.pd_deal_id.is_not(None)) | (Deal.status == Deal.STATUS_OPEN)
                        )
                        only_syncable_deal_fields = False
                    else:
                        # Only sync fields for paying companies' existing open deals
                        deal_query = deal_query.where(Deal.pd_deal_id.is_not(None), Deal.status == Deal.STATUS_OPEN)
                        only_syncable_deal_fields = True

                    deal_ids = [d.id for d in db.exec(deal_query).all()]

                if not await sync_organization(company_id, recreate_on_404):
                    logger.info(f'Company {company_id} has no Pipedrive org, skipping its contacts and deals')
                    return

                for contact_id in contact_ids:
                    await sync_person(contact_id, recreate_on_404)

                for deal_id in deal_ids:
                    await sync_deal(deal_id, only_syncable_deal_fields)

                logger.info(f'Successfully synced company {company_id} to Pipedrive')
            except Exception as e:
                logger.error(f'Error syncing company {company_id}: {e}', exc_info=True)


async def sync_organization(company_id: int, recreate_on_404: bool = False) -> bool:
    """
    Sync a single organization to Pipedrive.
    Returns False when the company should not sync further: it is missing, or Pipedrive no longer has its org and
    the company was marked deleted.
    """
    with get_session() as db:
        company = db.get(Company, company_id)
        if not company:
            return False
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
            if not _is_deleted_in_pipedrive(e):
                raise
            if not recreate_on_404:
                _mark_deleted_after_404(Company, company_id, 'pd_org_id', pd_org_id)
                return False
            pd_org_id = None

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

    return True


async def sync_person(contact_id: int, recreate_on_404: bool = False):
    """Sync a single person to Pipedrive"""
    with get_session() as db:
        contact = db.get(Contact, contact_id)
        if not contact:
            return
        if contact.is_deleted:
            logger.info(f'Contact {contact_id} is marked as deleted, skipping sync')
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
            if _is_deleted_in_pipedrive(e):
                if not recreate_on_404:
                    _mark_deleted_after_404(Contact, contact_id, 'pd_person_id', pd_person_id)
                    return
                pd_person_id = None

    if not pd_person_id:
        try:
            # Only on create — PD allows each status transition once, don't overwrite manual unsubscribes.
            person_data['marketing_status'] = 'subscribed'
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


async def partial_sync_deal_from_company(company: Company, deal: Deal):
    """
    Sets custom fields on a deal based on company data and only sends them to the PD via PATCH.
    """
    if not (company and deal.pd_deal_id):
        return

    custom_fields = {}
    for field in SYNCABLE_DEAL_FIELDS:
        value = getattr(company, field, None)
        if value is None:
            continue
        pd_field_id = DEAL_PD_FIELD_MAP.get(field)
        if pd_field_id:
            custom_fields[pd_field_id] = str(value) if isinstance(value, int) else value

    if not custom_fields:
        return

    try:
        await api.update_deal(deal.pd_deal_id, {'custom_fields': custom_fields})
        logger.info(f'Updated deal {deal.pd_deal_id}')
    except Exception as e:
        logger.error(f'Error updating deal {deal.pd_deal_id}: {e}')
        # The PATCH only sends custom fields, so a not-found answer can only mean the deal itself is gone
        if _is_deleted_in_pipedrive(e, method='PATCH'):
            _mark_deleted_after_404(Deal, deal.id, 'pd_deal_id', deal.pd_deal_id)


async def sync_deal(deal_id: int, only_syncable_deal_fields: bool = False):
    """
    Sync a single deal to Pipedrive.
    """
    from app.core.config import settings

    company = None
    with get_session() as db:
        deal = db.get(Deal, deal_id)
        if not deal:
            return
        if only_syncable_deal_fields:
            company = db.get(Company, deal.company_id)
        else:
            deal_data = _deal_to_pd_data(deal, db)
            # pipeline/stage are excluded from _deal_to_pd_data (issue #399) so that
            # updates never overwrite stages set by sales in Pipedrive. But new deals
            # still need them so PD places them in the correct pipeline. Captured here
            # while the session is open so as to put into deal_data only on the create path.
            pd_pipeline_id = deal.pipeline.pd_pipeline_id if deal.pipeline else None
            pd_stage_id = deal.stage.pd_stage_id if deal.stage else None
        pd_deal_id = deal.pd_deal_id

    if only_syncable_deal_fields:
        # we do this so we don't hold the db connection
        return await partial_sync_deal_from_company(company, deal)

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
            if _is_deleted_in_pipedrive(e):
                _mark_deleted_after_404(Deal, deal_id, 'pd_deal_id', pd_deal_id)

    else:
        # We don't have a deal and creating one
        if not settings.sync_create_deals:
            logger.warning(f'Deal {deal_id} has no pd_deal_id, skipping sync (deal creation disabled)')
            return

        try:
            # Only include pipeline/stage for creation (see comment above)
            deal_data['pipeline_id'] = pd_pipeline_id
            deal_data['stage_id'] = pd_stage_id
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


def _bring_back_for_booking(db: DBSession, company: Company, contact_id: int) -> None:
    """
    A sales call was booked, so the customer is live. If the company or the booked contact was marked deleted
    (deleted or merged away in Pipedrive), bring it back so the sync recreates it and the booking is not lost.
    A NARC company is left as it is: TC2 would delete it from Pipedrive again on its next update.
    """
    if company.narc:
        return
    contact = db.get(Contact, contact_id)
    booked = [company]
    if contact and contact.company_id == company.id:
        booked.append(contact)
    deleted = [obj for obj in booked if obj.is_deleted]
    for obj in deleted:
        obj.is_deleted = False
        db.add(obj)
        logger.warning(f'Sales call booked for deleted {type(obj).__name__} {obj.id}, bringing it back')
    if deleted:
        db.commit()


def _is_deleted_in_pipedrive(e: Exception, method: str = 'GET') -> bool:
    """
    Whether the error says Pipedrive no longer has the object: deleted over 30 days ago or merged into another one.
    Pipedrive answers 410, or 404 with its ERR_NOT_FOUND error body. The body check keeps a 404 that did not come
    from the Pipedrive API, e.g. from a wrong base URL, from marking every record deleted.
    Syncs only trust the GET: a PATCH after a successful GET can fail for another reason, such as a missing linked
    object.
    """
    if not isinstance(e, httpx.HTTPStatusError) or e.request.method != method:
        return False
    if e.response.status_code == 410:
        return True
    if e.response.status_code != 404:
        return False
    try:
        body = e.response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get('code') == 'ERR_NOT_FOUND'


def _mark_deleted_after_404(
    model: type[Company | Contact | Deal], hermes_id: int, pd_id_field: str, pd_id: int
) -> None:
    """
    Do what the Pipedrive delete webhook would have done for an object Pipedrive answered 404/410 for.
    The row is re-read and only marked if it still holds that Pipedrive id, so a webhook that already
    deleted or relinked it wins.
    """
    with get_session() as db:
        obj = db.get(model, hermes_id)
        if obj and getattr(obj, pd_id_field) == pd_id:
            logger.warning(
                f'Pipedrive no longer has {pd_id_field} {pd_id}, marking {model.__name__} {hermes_id} deleted'
            )
            mark_deleted_from_pipedrive(db, obj, pd_id_field)


def _bool_to_pd_enum_option(field_name: str, value: bool) -> int | None:
    """Map a Hermes bool to a Pipedrive single-option (enum) field option ID."""
    options = COMPANY_PD_ENUM_OPTION_MAP.get(field_name)
    if not options:
        return None
    if value:
        option_id = options.get('yes')
    else:
        option_id = options.get('no')
    if option_id is None:
        return None
    return int(option_id)


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

        # Pipedrive has no native boolean field type — use enum option IDs where configured.
        if isinstance(value, bool):
            enum_option_id = _bool_to_pd_enum_option(field_name, value)
            if enum_option_id is None:
                continue
            value = enum_option_id

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
        elif field_name == 'paid_invoice_count':
            value = company.paid_invoice_count if company else None
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
