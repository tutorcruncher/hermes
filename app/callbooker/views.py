from datetime import datetime, timedelta
from hmac import compare_digest
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException
from starlette.background import BackgroundTasks
from starlette.responses import JSONResponse
from tortoise.expressions import Q

from app.callbooker._availability import get_admin_available_slots
from app.callbooker._booking import check_gcal_open_slots, create_meeting_gcal_event
from app.callbooker._schema import AvailabilityData, CBSalesCall, CBSupportCall
from app.models import Admin, Company, Contact, Deal, Meeting
from app.pipedrive.tasks import post_sales_call, post_support_call
from app.utils import get_bearer, get_config, sign_args, settings

cb_router = APIRouter()


class MeetingBookingError(Exception):
    pass


async def _get_or_create_contact(company: Company, event: CBSalesCall | CBSupportCall) -> Contact:
    contact = (
        await Contact.filter(company_id=company.id)
        .filter(Q(email=event.email) | Q(last_name__iexact=event.last_name))
        .first()
    )
    if not contact:
        contact = await Contact.create(company_id=company.id, **event.contact_dict())
    return contact


async def _book_meeting(company: Company, contact: Contact, event: CBSalesCall | CBSupportCall) -> Meeting:
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
    admin = await Admin.get(tc_admin_id=event.admin_id)
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


async def _get_or_create_contact_company(event: CBSalesCall | CBSupportCall) -> tuple[Company, Contact]:
    """
    Gets or creates a contact and company based on the CBSalesCall data. The logic is a bit complex:
    The company is got by:
    - A submitted cligency_id (if submitted)
    - The contact's email (if they exist) and getting the company from that
    - The name
    The contact is got by:
    - The contact's email (if they exist)
    - Their last name
    If neither objects exist, they are created.
    """
    contact = None
    company = None
    if event.tc_cligency_id:
        company = await Company.filter(tc_cligency_id=event.tc_cligency_id).first()
    if not company:
        if contact := await Contact.filter(email=event.email).first():
            company = await contact.company
        else:
            company = await Company.filter(name__iexact=event.company_name).first()
            if not company:
                company_data = event.company_dict()
                company = await Company.create(**company_data)
    if isinstance(event, CBSalesCall) and not company.sales_person_id:
        sales_person = await Admin.get(tc_admin_id=event.admin_id)
        company.sales_person_id = sales_person.id
        await company.save()
    contact = contact or await _get_or_create_contact(company, event)
    return company, contact


async def _get_or_create_deal(company: Company, contact: Contact) -> Deal:
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
        )
    return deal


@cb_router.post('/sales/book/')
async def sales_call(event: CBSalesCall, background_tasks: BackgroundTasks):
    """
    Endpoint for someone booking a Sales call from the website.
    """
    # TODO: We need to do authorization here
    company, contact = await _get_or_create_contact_company(event)
    deal = await _get_or_create_deal(company, contact)
    try:
        meeting = await _book_meeting(company=company, contact=contact, event=event)
    except MeetingBookingError as e:
        return JSONResponse({'status': 'error', 'message': str(e)}, status_code=400)
    else:
        meeting.deal = deal
        await meeting.save()
        background_tasks.add_task(post_sales_call, company=company, contact=contact, deal=deal, meeting=meeting)
        return {'status': 'ok'}


@cb_router.post('/support/book/')
async def support_call(event: CBSupportCall, background_tasks: BackgroundTasks):
    """
    Endpoint for someone booking a Support call from the website.
    """
    # TODO: We need to do authorization here

    company, contact = await _get_or_create_contact_company(event)
    try:
        meeting = await _book_meeting(company=company, contact=contact, event=event)
    except MeetingBookingError as e:
        return JSONResponse({'status': 'error', 'message': str(e)}, status_code=400)
    else:
        await meeting.save()
        background_tasks.add_task(post_support_call, contact=contact, meeting=meeting)
        return {'status': 'ok'}


@cb_router.post('/availability/')
async def availability(avail_data: AvailabilityData):
    """
    Endpoint to return timeslots that an admin is available between 2 datetimes.
    """
    admin = await Admin.get(tc_admin_id=avail_data.admin_id)
    slots = get_admin_available_slots(avail_data.start_dt, avail_data.end_dt, admin)
    return {'status': 'ok', 'slots': [slot async for slot in slots]}


@cb_router.get('/support-link/generate/')
async def generate_support_link(admin_id: int, company_id: int, Authorization: Optional[str] = Header(None)):
    """
    Endpoint to generate a support link for a company from within TC2
    """
    if not get_bearer(Authorization) == settings.tc2_api_key:
        raise HTTPException(status_code=403, detail='Unauthorized key')
    admin = await Admin.get(tc_admin_id=admin_id)
    company = await Company.get(tc_cligency_id=company_id)
    expiry = datetime.now() + timedelta(days=settings.support_ttl_days)
    kwargs = {'admin_id': admin.tc_admin_id, 'company_id': company.tc_cligency_id, 'e': int(expiry.timestamp())}
    sig = await sign_args(*kwargs.values())
    return {'link': f"{admin.call_booker_url}/?{urlencode({'s': sig, **kwargs})}"}


@cb_router.get('/support-link/validate/')
async def validate_support_link(admin_id: int, company_id: int, e: int, s: str):
    """
    Endpoint to validate a support link for a company from the website
    """
    admin = await Admin.get(tc_admin_id=admin_id)
    company = await Company.get(tc_cligency_id=company_id)
    kwargs = {'admin_id': admin.tc_admin_id, 'company_id': company.tc_cligency_id, 'e': e}
    sig = await sign_args(*kwargs.values())
    if not compare_digest(sig, s):
        return JSONResponse({'status': 'error', 'message': 'Invalid signature'}, status_code=403)
    elif datetime.now().timestamp() > e:
        return JSONResponse({'status': 'error', 'message': 'Link has expired'}, status_code=403)
    return {'status': 'ok'}
