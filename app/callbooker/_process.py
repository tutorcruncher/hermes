from datetime import timedelta

from tortoise.expressions import Q

from app.callbooker._booking import check_gcal_open_slots, create_meeting_gcal_event
from app.callbooker._schema import CBSalesCall, CBSupportCall
from app.models import Company, Contact, Deal, Meeting
from app.utils import get_config, settings


async def get_or_create_contact(company: Company, event: CBSalesCall | CBSupportCall) -> Contact:
    contact = (
        await Contact.filter(company_id=company.id)
        .filter(Q(email=event.email) | Q(last_name__iexact=event.last_name))
        .first()
    )
    if not contact:
        contact_data = await event.contact_dict()
        contact = await Contact.create(company_id=company.id, **contact_data)
    return contact


async def book_meeting(company: Company, contact: Contact, event: CBSalesCall | CBSupportCall) -> Meeting:
    """
    Check that:
    A) There isn't already a meeting booked for this contact within 2 hours
    B) The admin exists
    C) The admin is free at this time

    If all of these are true, create the meeting and return it.
    """
    # Then we check that the meeting object doesn't already exist for this customer
    meeting_exists = await Meeting.filter(
        contact_id=contact.id,
        start_time__range=(event.meeting_dt - timedelta(hours=2), event.meeting_dt + timedelta(hours=2)),
    ).exists()
    if meeting_exists:
        raise MeetingBookingError('You already have a meeting booked around this time.')

    # Then we check that the admin has space in their calendar (we query Google for this)
    admin = await event.admin
    meeting_start = event.meeting_dt
    meeting_end = event.meeting_dt + timedelta(minutes=settings.meeting_dur_mins)
    try:
        assert await check_gcal_open_slots(meeting_start, meeting_end, admin.email)
    except AssertionError:
        raise MeetingBookingError('Admin is not free at this time.')
    meeting = Meeting(
        company=company,
        contact=contact,
        meeting_type=Meeting.TYPE_SALES if isinstance(event, CBSalesCall) else Meeting.TYPE_SUPPORT,
        start_time=meeting_start,
        end_time=meeting_end,
        admin=admin,
    )
    await create_meeting_gcal_event(meeting=meeting)
    return meeting


async def get_or_create_contact_company(event: CBSalesCall) -> tuple[Company, Contact]:
    """
    Gets or creates a contact and company based on the CBSalesCall data. The logic is a bit complex:
    The company is got by:
    - A submitted company_id (if submitted)
    - The contact's email (if they exist) and getting the company from that
    - The name
    The contact is got by:
    - The contact's email (if they exist)
    - Their last name
    If neither objects exist, they are created.
    """
    contact = None
    company = event.company_id and await event.company
    if not company:
        if contact := await Contact.filter(email=event.email).first():
            company = await contact.company
        else:
            company = await Company.filter(name__iexact=event.company_name).first()
            if not company:
                company_data = await event.company_dict()
                company = await Company.create(**company_data)
    if not company.sales_person_id:
        company.sales_person = event.admin
        await company.save()
    contact = contact or await get_or_create_contact(company, event)
    return company, contact


async def get_or_create_deal(company: Company, contact: Contact) -> Deal:
    """
    Get or create an Open deal.
    """
    deal = await Deal.filter(company_id=company.id, status=Deal.STATUS_OPEN).first()
    config = await get_config()
    if not deal:
        match company.price_plan:
            case Company.PP_PAYG:
                pipeline = await config.payg_pipeline
            case Company.PP_STARTUP:
                pipeline = await config.startup_pipeline
            case Company.PP_ENTERPRISE:
                pipeline = await config.enterprise_pipeline
            case _:
                raise ValueError(f'Unknown price plan {company.price_plan}')

        deal = await Deal.create(
            company_id=company.id,
            contact_id=contact.id,
            name=company.name,
            pipeline_id=pipeline.id,
            admin_id=company.sales_person_id,
            stage_id=pipeline.dft_entry_stage_id,
        )
    return deal


class MeetingBookingError(Exception):
    pass
