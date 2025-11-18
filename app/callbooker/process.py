import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.callbooker.google import AdminGoogleCalendar
from app.callbooker.meeting_templates import MEETING_CONTENT_TEMPLATES
from app.callbooker.models import CBSalesCall, CBSupportCall
from app.callbooker.utils import iso_8601_to_datetime
from app.core.config import settings
from app.core.database import DBSession
from app.main_app.models import Admin, Company, Contact, Meeting

logger = logging.getLogger('hermes.callbooker')


class MeetingBookingError(Exception):
    """Raised when a meeting cannot be booked"""

    pass


async def get_or_create_contact(company: Company, event: CBSalesCall | CBSupportCall, db: DBSession) -> Contact:
    """Get or create contact from callbooker event data"""
    # Try to find existing contact by email or last name
    if event.email:
        contact = db.exec(
            select(Contact)
            .where(Contact.company_id == company.id, Contact.email == event.email)
            .order_by(Contact.id.desc())
        ).first()
    else:
        contact = db.exec(
            select(Contact)
            .where(Contact.company_id == company.id, Contact.last_name.ilike(event.last_name))
            .order_by(Contact.id.desc())
        ).first()

    if not contact:
        # Create new contact
        contact_data = event.contact_dict()
        contact = Contact(company_id=company.id, **contact_data)
        db.add(contact)
        db.commit()
        db.refresh(contact)

    return contact


async def get_or_create_contact_company(event: CBSalesCall, db: DBSession) -> tuple[Company, Contact]:
    """
    Get or create contact and company based on CBSalesCall data.

    The company is found by:
    - Submitted company_id (if provided)
    - Contact's email (if they exist) and get company from that
    - Company name

    The contact is found by:
    - Contact's email
    - Contact's phone
    - Their last name

    If neither exist, they are created.
    """
    contact = None
    company = None

    # Try to get company by ID
    if event.company_id:
        company = db.get(Company, event.company_id)

    # Try to find contact by email or phone, then get their company
    if not company and event.email:
        contact = db.exec(select(Contact).where(Contact.email == event.email).order_by(Contact.id.desc())).first()
        if contact:
            logger.info(f'Found contact {contact.id} by email')
            company = db.get(Company, contact.company_id)

    if not company and event.phone:
        contact = db.exec(select(Contact).where(Contact.phone == event.phone).order_by(Contact.id.desc())).first()
        if contact:
            logger.info(f'Found contact {contact.id} by phone')
            company = db.get(Company, contact.company_id)

    # Try to find company by name
    if not company:
        company = db.exec(
            select(Company).where(Company.name.ilike(event.company_name)).order_by(Company.id.desc())
        ).first()
        if company:
            logger.info(f'Found company {company.id} by name')

    # Create company if not found
    if not company:
        company_data = event.company_dict()
        company = Company(**company_data)
        db.add(company)
        try:
            db.commit()
        except IntegrityError:
            # Previously tc2_admin_id was passed as bdr_id, but with the rebuild we expect the hermes_admin_id.
            # So this handles those old urls.
            db.rollback()
            bdr_id = company_data.get('bdr_person_id')
            if not bdr_id:
                raise

            admin = db.exec(select(Admin).where(Admin.tc2_admin_id == bdr_id)).one_or_none()
            if not admin:
                logger.error(f'Could not find admin with tc2_admin_id {bdr_id}')
                raise

            company.bdr_person_id = admin.id
            db.add(company)
            db.commit()

        db.refresh(company)
        logger.info(f'Created company {company.id}')

    # Get or create contact
    contact = contact or await get_or_create_contact(company, event, db)
    logger.info(f'Got company {company.id} and contact {contact.id}')

    # Mark that company has booked a call
    company.has_booked_call = True
    db.add(company)
    db.commit()

    return company, contact


async def book_meeting(
    company: Company, contact: Contact, event: CBSalesCall | CBSupportCall, db: DBSession
) -> Meeting:
    """
    Book a meeting after checking:
    A) Contact has an email address
    B) No meeting already booked within 2 hours
    C) Admin exists and is free at this time

    If all checks pass, creates the meeting and syncs to Google Calendar.
    """
    if not contact.email:
        raise MeetingBookingError('Contact must have an email address to book a meeting.')

    _check_no_duplicate_meeting(contact.id, event.meeting_dt, db)

    admin = db.get(Admin, event.admin_id)
    if not admin:
        raise MeetingBookingError('Admin not found.')

    meeting_start = event.meeting_dt
    meeting_end = event.meeting_dt + timedelta(minutes=settings.meeting_dur_mins)
    await _check_admin_availability(meeting_start, meeting_end, admin.email)

    meeting = _create_meeting_record(company.id, contact.id, event, meeting_start, meeting_end, db)

    try:
        await _create_google_calendar_event(meeting, company, contact, admin, db)
    except Exception as e:
        _delete_meeting_on_calendar_failure(meeting.id, db)
        raise e
    return meeting


def _check_no_duplicate_meeting(contact_id: int, meeting_dt: datetime, db: DBSession) -> None:
    """Check that no meeting already exists within 2 hours of the requested time"""
    two_hours_before = meeting_dt - timedelta(hours=2)
    two_hours_after = meeting_dt + timedelta(hours=2)

    existing_meeting = db.exec(
        select(Meeting).where(
            Meeting.contact_id == contact_id,
            Meeting.start_time >= two_hours_before,
            Meeting.start_time <= two_hours_after,
        )
    ).one_or_none()

    if existing_meeting:
        raise MeetingBookingError('You already have a meeting booked around this time.')


async def _check_admin_availability(meeting_start: datetime, meeting_end: datetime, admin_email: str) -> None:
    if not await check_gcal_open_slots(meeting_start, meeting_end, admin_email):
        raise MeetingBookingError('Admin is not free at this time.')


def _create_meeting_record(
    company_id: int,
    contact_id: int,
    event: CBSalesCall | CBSupportCall,
    meeting_start: datetime,
    meeting_end: datetime,
    db: DBSession,
) -> Meeting:
    """Create meeting record in database and commit to release DB connection before external API call"""
    meeting_type = Meeting.TYPE_SALES if isinstance(event, CBSalesCall) else Meeting.TYPE_SUPPORT

    meeting = Meeting(
        company_id=company_id,
        contact_id=contact_id,
        meeting_type=meeting_type,
        start_time=meeting_start,
        end_time=meeting_end,
        admin_id=event.admin_id,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    return meeting


def _delete_meeting_on_calendar_failure(meeting_id: int, db: DBSession) -> None:
    """Delete meeting from database if Google Calendar event creation fails"""
    meeting = db.get(Meeting, meeting_id)
    if meeting:
        db.delete(meeting)
        db.commit()
        logger.info(f'Deleted meeting {meeting_id} due to Google Calendar failure')


def _build_meeting_template_vars(company: Company, contact: Contact, admin: Admin, meeting_type: str) -> dict:
    """Build template variables for meeting description"""
    template_vars = {
        'contact_first_name': contact.first_name or 'there',
        'company_name': company.name,
        'admin_name': admin.first_name,
        'tc2_cligency_id': company.tc2_cligency_id or '',
        'tc2_cligency_url': company.tc2_cligency_url or '',
    }

    if meeting_type == Meeting.TYPE_SALES:
        template_vars.update(
            {
                'contact_email': contact.email,
                'contact_phone': contact.phone,
                'company_estimated_monthly_revenue': company.estimated_income,
                'company_country': company.country,
                'crm_url': company.pd_org_url or '',
            }
        )

    return template_vars


async def _create_google_calendar_event(
    meeting: Meeting, company: Company, contact: Contact, admin: Admin, db: DBSession
) -> None:
    """Create Google Calendar event for the meeting"""
    meeting_template = MEETING_CONTENT_TEMPLATES[meeting.meeting_type]
    template_vars = _build_meeting_template_vars(company, contact, admin, meeting.meeting_type)

    try:
        g_cal = AdminGoogleCalendar(admin_email=admin.email)
        await asyncio.to_thread(
            g_cal.create_cal_event,
            description=meeting_template.format(**template_vars),
            summary=meeting.name,
            contact_email=contact.email,
            start=meeting.start_time,
            end=meeting.end_time,
        )
        logger.info(f'Created Google Calendar event for meeting {meeting.id}')
    except Exception as e:
        logger.error(f'Failed to create Google Calendar event for meeting {meeting.id}: {e}', exc_info=True)
        raise MeetingBookingError('Failed to create calendar event')


async def check_gcal_open_slots(meeting_start: datetime, meeting_end: datetime, admin_email: str) -> bool:
    """
    Query Google Calendar for busy slots and check if the requested time is available.
    """
    # Everything uses UTC
    assert meeting_start.tzinfo == timezone.utc

    g_cal = AdminGoogleCalendar(admin_email=admin_email)
    cal_data = await asyncio.to_thread(g_cal.get_free_busy_slots, meeting_start, meeting_start + timedelta(days=1))

    busy_slots = cal_data.get('calendars', {}).get(admin_email, {}).get('busy', [])
    for time_slot in busy_slots:
        slot_start = iso_8601_to_datetime(time_slot['start'])
        slot_end = iso_8601_to_datetime(time_slot['end'])
        if (
            slot_start <= meeting_start <= slot_end
            or slot_start <= meeting_end <= slot_end
            or (slot_start <= meeting_start and slot_end >= meeting_end)
        ):
            logger.info(f'Tried to book meeting with {admin_email} for slot {slot_start} - {slot_end}')
            return False
    return True
