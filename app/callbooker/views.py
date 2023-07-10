import datetime

from fastapi import APIRouter
from starlette.responses import JSONResponse
from tortoise.exceptions import DoesNotExist
from tortoise.expressions import Q

from app.callbooker._availability import get_admin_available_slots
from app.callbooker._booking import check_gcal_open_slots, create_meeting_gcal_event
from app.callbooker._schema import AvailabilityData, CBEvent
from app.models import Admins, Companies, Contacts, Meetings
from app.settings import Settings

cb_router = APIRouter()
settings = Settings()


async def _get_or_create_contact_company(event: CBEvent) -> tuple[Companies, Contacts]:
    """
    Gets or creates a contact and company based on the event data. The logic is a bit complex:
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
        company = await Companies.filter(tc_cligency_id=event.tc_cligency_id).first()
    if not company:
        if contact := await Contacts.filter(email=event.email).first():
            company = await contact.company
        else:
            company = await Companies.filter(name__iexact=event.company_name).first()
            if not company:
                company_data = event.company_dict()
                if event.client_manager:
                    cli_man = await Admins.filter(tc_admin_id=event.client_manager).first()
                    company_data['client_manager_id'] = cli_man.id
                if event.sales_person:
                    sales_person = await Admins.filter(tc_admin_id=event.sales_person).first()
                    company_data['sales_person_id'] = sales_person.id
                company = await Companies.create(**company_data)
    contact = contact or (
        await Contacts.filter(company_id=company.id)
        .filter(Q(email=event.email) | Q(last_name__iexact=event.last_name))
        .first()
    )
    if not contact:
        contact = await Contacts.create(company_id=company.id, **event.contact_dict())
    return company, contact


@cb_router.post('/callback/')
async def callback(event: CBEvent):
    """
    Call back for someone booking a call from the website.
    """
    # TODO: We need to do authorization here

    # First we get or create the company and contact objects.
    company, contact = await _get_or_create_contact_company(event)
    # Then we check that the meeting object doesn't already exist for this customer
    if await Meetings.filter(
        contact_id=contact.id,
        start_time__range=(
            event.meeting_dt - datetime.timedelta(hours=2),
            event.meeting_dt + datetime.timedelta(hours=2),
        ),
    ):
        return JSONResponse(
            {'status': 'error', 'message': 'You already have a meeting booked around this time.'}, status_code=400
        )

    # Then we check that the admin has space in their calendar (we query Google for this)
    try:
        admin = await Admins.get(tc_admin_id=event.meeting_admin)
    except DoesNotExist:
        return JSONResponse({'status': 'error', 'message': 'Admin does not exist.'}, status_code=400)
    meeting_start = event.meeting_dt
    meeting_end = event.meeting_dt + datetime.timedelta(minutes=settings.meeting_dur_mins)
    admin_is_free = await check_gcal_open_slots(meeting_start, meeting_end, admin.email)

    if admin_is_free:
        meeting_type = Meetings.TYPE_SALES if admin.is_sales_person else Meetings.TYPE_SUPPORT
        meeting = await Meetings.create(
            company=company,
            contact=contact,
            meeting_type=meeting_type,
            start_time=meeting_start,
            end_time=meeting_end,
            admin=admin,
            form_json=event.form_json,
        )
        await create_meeting_gcal_event(meeting=meeting)
        return {'status': 'ok'}
    else:
        return JSONResponse({'status': 'error', 'message': 'Admin is not free at this time.'}, status_code=400)


@cb_router.post('/availability/')
async def availability(avail_data: AvailabilityData):
    """
    Endpoint to return timeslots that an admin is available between 2 datetimes.
    """
    admin = await Admins.get(tc_admin_id=avail_data.admin_id)
    slots = get_admin_available_slots(avail_data.start_dt, avail_data.end_dt, admin)
    return {'status': 'ok', 'slots': slots}
