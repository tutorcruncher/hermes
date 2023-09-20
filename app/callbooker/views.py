from datetime import datetime, timedelta
from hmac import compare_digest
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException
from starlette.background import BackgroundTasks
from starlette.responses import JSONResponse

from app.callbooker._availability import get_admin_available_slots
from app.callbooker._process import (
    book_meeting,
    get_or_create_contact_company,
    get_or_create_deal,
    MeetingBookingError,
    get_or_create_contact,
)
from app.callbooker._schema import CBSalesCall, CBSupportCall
from app.models import Admin, Company
from app.pipedrive.tasks import pd_post_process_sales_call, pd_post_process_support_call
from app.utils import get_bearer, sign_args, settings

cb_router = APIRouter()


@cb_router.post('/sales/book/')
async def sales_call(event: CBSalesCall, tasks: BackgroundTasks):
    """
    Endpoint for someone booking a Sales call from the website.
    We can't do standard auth as this comes from the website. We use a CORS policy instead.
    """
    await event.a_validate()
    company, contact = await get_or_create_contact_company(event)
    deal = await get_or_create_deal(company, contact)
    try:
        meeting = await book_meeting(company=company, contact=contact, event=event)
    except MeetingBookingError as e:
        return JSONResponse({'status': 'error', 'message': str(e)}, status_code=400)
    else:
        meeting.deal = deal
        await meeting.save()
        tasks.add_task(pd_post_process_sales_call, company=company, contact=contact, deal=deal, meeting=meeting)
        return {'status': 'ok'}


@cb_router.post('/support/book/')
async def support_call(event: CBSupportCall, tasks: BackgroundTasks):
    """
    Endpoint for someone booking a Support call from the website.
    We can't do standard auth as this comes from the website. We use a CORS policy instead.
    """
    await event.a_validate()
    company = await event.company
    contact = await get_or_create_contact(company, event)
    try:
        meeting = await book_meeting(company=company, contact=contact, event=event)
    except MeetingBookingError as e:
        return JSONResponse({'status': 'error', 'message': str(e)}, status_code=400)
    else:
        await meeting.save()
        tasks.add_task(pd_post_process_support_call, contact=contact, meeting=meeting)
        return {'status': 'ok'}


@cb_router.get('/availability/')
async def availability(admin_id: int, start_dt: datetime, end_dt: datetime):
    """
    Endpoint to return timeslots that an admin is available between 2 datetimes.
    """
    admin = await Admin.get(id=admin_id)
    slots = get_admin_available_slots(start_dt, end_dt, admin)
    return {'status': 'ok', 'slots': [slot async for slot in slots]}


@cb_router.get('/support-link/generate/tc2/')
async def generate_support_link(tc2_admin_id: int, tc2_cligency_id: int, Authorization: Optional[str] = Header(None)):
    """
    Endpoint to generate a support link for a company from within TC2
    """
    debug(tc2_admin_id, tc2_cligency_id)
    if get_bearer(Authorization) != settings.tc2_api_key.decode():
        raise HTTPException(status_code=403, detail='Unauthorized key')
    admin = await Admin.get(tc2_admin_id=tc2_admin_id)
    company = await Company.get(tc2_cligency_id=tc2_cligency_id)
    expiry = datetime.now() + timedelta(days=settings.support_ttl_days)
    kwargs = {'admin_id': admin.id, 'company_id': company.id, 'e': int(expiry.timestamp())}
    sig = await sign_args(*kwargs.values())
    debug(kwargs, sig
          )
    return {'link': f"{admin.call_booker_url}?{urlencode({'s': sig, **kwargs})}"}


@cb_router.get('/support-link/validate/')
async def validate_support_link(admin_id: int, company_id: int, e: int, s: str):
    """
    Endpoint to validate a support link for a company from the website
    """
    debug(admin_id, company_id, e, s)
    admin = await Admin.get(id=admin_id)
    company = await Company.get(id=company_id)
    kwargs = {'admin_id': admin.id, 'company_id': company.id, 'e': e}
    sig = await sign_args(*kwargs.values())
    if not compare_digest(sig, s):
        return JSONResponse({'status': 'error', 'message': 'Invalid signature'}, status_code=403)
    elif datetime.now().timestamp() > e:
        return JSONResponse({'status': 'error', 'message': 'Link has expired'}, status_code=403)
    return {'status': 'ok', 'company_name': company.name}
