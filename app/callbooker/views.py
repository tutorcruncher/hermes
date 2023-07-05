import datetime

from fastapi import APIRouter
from tortoise.expressions import Q

from app.callbooker._availability import run_free_busy
from app.callbooker._schema import CBEvent
from app.callbooker._utils import app_logger
from app.models import Companies, Contacts, Meetings, Admins
from app.settings import Settings

cb_router = APIRouter()
settings = Settings()


def get_bearer(auth: str):
    try:
        return auth.split(' ')[1]
    except (AttributeError, IndexError):
        return


async def _get_or_create_contact_company(event: CBEvent) -> tuple[Companies, Contacts]:
    contact = None
    if event.tc_cligency_id:
        company = await Companies.filter(id=event.tc_cligency_id).first()
    else:
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
        await Contacts.filter(company_id=company.id).filter(Q(email=event.email) | Q(last_name=event.last_name)).first()
    )
    if not contact:
        contact = await Contacts.create(company_id=company.id, **event.contact_dict())
    return company, contact


async def _check_gcal_open_slots(start: datetime, timezone: str, admin_email: str) -> bool:
    data = {
        'timeMin': start.isoformat(),
        'timeMax': (start + datetime.timedelta(hours=2)).isoformat(),
        'timeZone': timezone,
        'groupExpansionMax': 100,
        'items': [{'id': admin_email}],
    }
    debug(data)
    check_google = run_free_busy(admin_email, data)
    debug(check_google)
    return True
    # for time_slot in check_google['calendars'][admin_email]['busy']:
    #     debug(timeslot)
    #
    #     if time_slot['start'].endswith('Z'):
    #         slot_start = datetime.strptime(time_slot['start'], '%Y-%m-%dT%H:%M:%SZ').astimezone(
    #             pytz.timezone('Europe/London')
    #         )
    #         slot_end = datetime.strptime(time_slot['end'], '%Y-%m-%dT%H:%M:%SZ').astimezone(
    #             pytz.timezone('Europe/London')
    #         )
    #     else:
    #         slot_start = (
    #             pytz.timezone(data['timeZone'])
    #             .localize(datetime.strptime(time_slot['start'][:-6], '%Y-%m-%dT%H:%M:%S'))
    #             .astimezone(pytz.timezone('Europe/London'))
    #         )
    #         slot_end = (
    #             pytz.timezone(data['timeZone'])
    #             .localize(datetime.strptime(time_slot['end'][:-6], '%Y-%m-%dT%H:%M:%S'))
    #             .astimezone(pytz.timezone('Europe/London'))
    #         )
    #     if slot_start <= start_time <= slot_end:
    #         logger.info('Meeting already booked for this time slot: %s', start_time)
    #         return {'status': 'ok', 'message': 'Time slot already has a meeting at this time'}


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
        return {'status': 'error', 'message': 'You already have a meeting booked around this time.'}

    debug('bar')
    # Then we check that the admin has space in their calendar (which is a bit complex)
    try:
        admin = await Admins.get(tc_admin_id=event.meeting_admin)
        debug('pol')
    except Admins.DoesNotExist:
        return {'status': 'error', 'message': 'Admin does not exist.'}
    admin_is_free = await _check_gcal_open_slots(event.meeting_dt, event.timezone, admin.email)

    if admin_is_free:
        meeting_type = Meetings.MEETING_TYPE_SALES if admin.is_sales_person else Meetings.MEETING_TYPE_SUPPORT
        await Meetings.create(
            company=company, contact=contact, meeting_type=meeting_type, start_time=event.meeting_dt, admin=admin
        )
    return {'status': 'ok'}
