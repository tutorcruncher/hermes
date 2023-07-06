import datetime

from fastapi import APIRouter
from pytz import utc
from starlette.responses import JSONResponse
from tortoise.exceptions import DoesNotExist
from tortoise.expressions import Q

from app.callbooker._google import AdminGoogleCalendar
from app.callbooker._schema import CBEvent
from app.callbooker._utils import app_logger
from app.models import Admins, Companies, Contacts, Meetings
from app.settings import Settings

cb_router = APIRouter()
settings = Settings()


def get_bearer(auth: str):
    try:
        return auth.split(' ')[1]
    except (AttributeError, IndexError):
        return


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


def _iso_8601_to_datetime(dt_str: str) -> datetime.datetime:
    # Removing the UTC timezone as `fromisoformat` doesn't support ISO 8601
    return datetime.datetime.fromisoformat(dt_str.rstrip('Z')).replace(tzinfo=utc)


async def _check_gcal_open_slots(meeting_start: datetime, meeting_end: datetime, admin_email: str) -> bool:
    """
    Queries Google to for all busy slots for the admin and checks if the start time is in one of them.
    """
    # Everything uses UTC
    assert meeting_start.tzinfo == utc
    g_cal = AdminGoogleCalendar(admin_email=admin_email)
    cal_data = g_cal.get_free_busy_slots(meeting_start)
    for time_slot in cal_data['calendars'][admin_email]['busy']:
        _ts_start = _iso_8601_to_datetime(time_slot['start'])
        _ts_end = _iso_8601_to_datetime(time_slot['end'])
        if _ts_start <= meeting_start <= _ts_end or _ts_start <= meeting_end <= _ts_end:
            app_logger.info('Meeting already booked for this time slot: %s', meeting_start)
            return False
    return True


@cb_router.post('/callback/callbooker/')
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
    admin_is_free = await _check_gcal_open_slots(meeting_start, meeting_end, admin.email)

    if admin_is_free:
        meeting_type = Meetings.TYPE_SALES if admin.is_sales_person else Meetings.TYPE_SUPPORT
        await Meetings.create(
            company=company,
            contact=contact,
            meeting_type=meeting_type,
            start_time=meeting_start,
            end_time=meeting_end,
            admin=admin,
            form_json=event.form_json,
        )
        return {'status': 'ok'}
    else:
        return JSONResponse({'status': 'error', 'message': 'Admin is not free at this time.'}, status_code=400)
