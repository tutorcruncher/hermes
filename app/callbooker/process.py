import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.callbooker.google import AdminGoogleCalendar
from app.callbooker.meeting_templates import MEETING_CONTENT_TEMPLATES
from app.callbooker.models import CBSalesCall, CBSupportCall
from app.callbooker.utils import iso_8601_to_datetime
from app.core.config import settings
from app.core.database import DBSession
from app.main_app.models import Admin, Company, Config, Contact, Deal, Meeting, Pipeline, Stage

logger = logging.getLogger('hermes.callbooker')


class MeetingBookingError(Exception):
    """Raised when a meeting cannot be booked"""

    pass


async def get_or_create_contact(company: Company, event: CBSalesCall | CBSupportCall, db: DBSession) -> Contact:
    """Get or create contact from callbooker event data"""
    # Try to find existing contact by email or last name
    if event.email:
        contact = db.exec(
            select(Contact).where(Contact.company_id == company.id, Contact.email == event.email)
        ).one_or_none()
    else:
        contact = db.exec(
            select(Contact).where(Contact.company_id == company.id, Contact.last_name.ilike(event.last_name))
        ).one_or_none()

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
        contact = db.exec(select(Contact).where(Contact.email == event.email)).one_or_none()
        if contact:
            logger.info(f'Found contact {contact.id} by email')
            company = db.get(Company, contact.company_id)

    if not company and event.phone:
        contact = db.exec(select(Contact).where(Contact.phone == event.phone)).one_or_none()
        if contact:
            logger.info(f'Found contact {contact.id} by phone')
            company = db.get(Company, contact.company_id)

    # Try to find company by name
    if not company:
        company = db.exec(select(Company).where(Company.name.ilike(event.company_name))).one_or_none()
        if company:
            logger.info(f'Found company {company.id} by name')

    # Create company if not found
    if not company:
        company_data = event.company_dict()
        company = Company(**company_data)
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


async def get_or_create_deal(company: Company, contact: Contact, db: DBSession) -> Deal:
    """Get or create an Open deal for the company"""
    deal = db.exec(select(Deal).where(Deal.company_id == company.id, Deal.status == Deal.STATUS_OPEN)).one_or_none()

    if not deal:
        # Get config - must exist
        config = db.exec(select(Config)).one_or_none()
        if not config:
            raise MeetingBookingError('System configuration not found')

        # Get pipeline based on price plan
        match company.price_plan:
            case Company.PP_PAYG:
                pipeline = db.get(Pipeline, config.payg_pipeline_id)
            case Company.PP_STARTUP:
                pipeline = db.get(Pipeline, config.startup_pipeline_id)
            case Company.PP_ENTERPRISE:
                pipeline = db.get(Pipeline, config.enterprise_pipeline_id)

        if not pipeline:
            raise MeetingBookingError('No pipeline configured')

        # Get default entry stage from pipeline
        stage = db.get(Stage, pipeline.dft_entry_stage_id)
        if not stage:
            raise MeetingBookingError('No stage configured for pipeline')

        deal = Deal(
            company_id=company.id,
            contact_id=contact.id,
            name=company.name,
            pipeline_id=pipeline.id,
            admin_id=company.sales_person_id,
            stage_id=stage.id,
        )
        db.add(deal)
        db.commit()
        db.refresh(deal)

    return deal


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
    # Check contact has email
    if not contact.email:
        raise MeetingBookingError('Contact must have an email address to book a meeting.')

    # Check no meeting already exists within 2 hours
    two_hours_before = event.meeting_dt - timedelta(hours=2)
    two_hours_after = event.meeting_dt + timedelta(hours=2)
    existing_meeting = db.exec(
        select(Meeting).where(
            Meeting.contact_id == contact.id,
            Meeting.start_time >= two_hours_before,
            Meeting.start_time <= two_hours_after,
        )
    ).one_or_none()
    if existing_meeting:
        raise MeetingBookingError('You already have a meeting booked around this time.')

    # Get admin
    admin = db.get(Admin, event.admin_id)
    if not admin:
        raise MeetingBookingError('Admin not found.')

    # Check admin is free (query Google Calendar)
    meeting_start = event.meeting_dt
    meeting_end = event.meeting_dt + timedelta(minutes=settings.meeting_dur_mins)

    if not await check_gcal_open_slots(meeting_start, meeting_end, admin.email):
        raise MeetingBookingError('Admin is not free at this time.')

    # create calender event first
    # If fails, we dont create the meeting in the database
    try:
        g_cal = AdminGoogleCalendar(admin_email=admin.email)
        meeting_template = MEETING_CONTENT_TEMPLATES[
            Meeting.TYPE_SALES if isinstance(event, CBSalesCall) else Meeting.TYPE_SUPPORT
        ]
        meeting_templ_vars = {
            'contact_first_name': contact.first_name or 'there',
            'company_name': company.name,
            'admin_name': admin.first_name,
            'tc2_cligency_id': company.tc2_cligency_id or '',
            'tc2_cligency_url': company.tc2_cligency_url or '',
        }
        if isinstance(event, CBSalesCall):
            meeting_templ_vars.update(
                contact_email=contact.email,
                contact_phone=contact.phone,
                company_estimated_monthly_revenue=company.estimated_income,
                company_country=company.country,
                crm_url=company.pd_org_url or '',
            )
        g_cal.create_cal_event(
            description=meeting_template.format(**meeting_templ_vars),
            summary=f'Sales Call - {contact.first_name or ""} {contact.last_name}'.strip(),
            contact_email=contact.email,
            start=meeting_start,
            end=meeting_end,
        )
        logger.info(f'Created Google Calendar event for {contact.email}')
    except Exception as e:
        logger.error(f'Failed to create Google Calendar event: {e}', exc_info=True)
        raise MeetingBookingError('Failed to create calendar event')

    # Create meeting record AFTER Google Calendar succeeds
    meeting = Meeting(
        company_id=company.id,
        contact_id=contact.id,
        meeting_type=Meeting.TYPE_SALES if isinstance(event, CBSalesCall) else Meeting.TYPE_SUPPORT,
        start_time=meeting_start,
        end_time=meeting_end,
        admin_id=admin.id,
    )
    db.add(meeting)
    db.flush()  # Flush to get meeting.id, but don't commit yet
    db.refresh(meeting)

    # Don't commit here - let the caller (view) handle the commit
    # Since Google Calendar already succeeded, any subsequent commit will persist the meeting
    return meeting


async def check_gcal_open_slots(meeting_start: datetime, meeting_end: datetime, admin_email: str) -> bool:
    """
    Query Google Calendar for busy slots and check if the requested time is available.
    """
    # Everything uses UTC
    assert meeting_start.tzinfo == timezone.utc

    g_cal = AdminGoogleCalendar(admin_email=admin_email)
    cal_data = g_cal.get_free_busy_slots(meeting_start, meeting_start + timedelta(days=1))

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


async def create_meeting_gcal_event(meeting: Meeting, db: DBSession):
    """
    Create a meeting event in the admin and contact's Google Calendar.
    Includes details from Pipedrive/TC2 if available.
    """
    contact = db.get(Contact, meeting.contact_id)
    company = db.get(Company, meeting.company_id)
    admin = db.get(Admin, meeting.admin_id)

    meeting_templ_vars = {
        'contact_first_name': contact.first_name or 'there',
        'company_name': company.name,
        'admin_name': admin.first_name,
        'tc2_cligency_id': company.tc2_cligency_id or '',
        'tc2_cligency_url': company.tc2_cligency_url or '',
    }

    meeting_template = MEETING_CONTENT_TEMPLATES[meeting.meeting_type]

    if meeting.meeting_type == Meeting.TYPE_SALES:
        meeting_templ_vars.update(
            contact_email=contact.email,
            contact_phone=contact.phone,
            company_estimated_monthly_revenue=company.estimated_income,
            company_country=company.country,
            crm_url=company.pd_org_url or '',
        )

    g_cal = AdminGoogleCalendar(admin_email=admin.email)
    g_cal.create_cal_event(
        description=meeting_template.format(**meeting_templ_vars),
        summary=meeting.name,
        contact_email=contact.email,
        start=meeting.start_time,
        end=meeting.end_time,
    )
    logger.info(f'Created Google Calendar event for meeting {meeting.id}')
