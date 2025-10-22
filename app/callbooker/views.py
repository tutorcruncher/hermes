import logging
from datetime import datetime, timedelta
from hmac import compare_digest
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Header
from sqlmodel import select
from starlette.responses import JSONResponse

from app.callbooker.availability import get_admin_available_slots
from app.callbooker.models import CBSalesCall, CBSupportCall
from app.callbooker.process import (
    MeetingBookingError,
    book_meeting,
    get_or_create_contact,
    get_or_create_contact_company,
    get_or_create_deal,
)
from app.common.utils import get_bearer, sign_args
from app.core.config import settings
from app.core.database import DBSession, get_db
from app.main_app.models import Admin, Company
from app.pipedrive.tasks import sync_company_to_pipedrive, sync_meeting_to_pipedrive
from app.tc2.process import get_or_create_company_from_tc2

logger = logging.getLogger('hermes.callbooker')

router = APIRouter(prefix='/callbooker', tags=['callbooker'])


@router.post('/sales/book/', name='book-sales-call')
async def sales_call(event: CBSalesCall, background_tasks: BackgroundTasks, db: DBSession = Depends(get_db)):
    """
    Endpoint for booking a Sales call from the website.
    Callbooker → Hermes → Pipedrive sync.
    """
    try:
        company, contact = await get_or_create_contact_company(event, db)
        deal = await get_or_create_deal(company, contact, db)
        meeting = await book_meeting(company=company, contact=contact, event=event, db=db)
        meeting.deal_id = deal.id
        db.add(meeting)
        db.commit()
    except MeetingBookingError as e:
        return JSONResponse({'status': 'error', 'message': str(e)}, status_code=400)

    # Queue background tasks to sync to Pipedrive
    background_tasks.add_task(sync_company_to_pipedrive, company.id)
    background_tasks.add_task(sync_meeting_to_pipedrive, meeting.id)

    return {'status': 'ok'}


@router.post('/support/book/', name='book-support-call')
async def support_call(event: CBSupportCall, background_tasks: BackgroundTasks, db: DBSession = Depends(get_db)):
    """
    Endpoint for booking a Support call from the website.
    Callbooker → Hermes → Pipedrive sync.
    """
    company = db.get(Company, event.company_id)
    if not company:
        return JSONResponse({'status': 'error', 'message': 'Company not found'}, status_code=404)

    contact = await get_or_create_contact(company, event, db)

    try:
        meeting = await book_meeting(company=company, contact=contact, event=event, db=db)
    except MeetingBookingError as e:
        return JSONResponse({'status': 'error', 'message': str(e)}, status_code=400)

    # Queue background tasks to sync to Pipedrive
    background_tasks.add_task(sync_company_to_pipedrive, company.id)
    background_tasks.add_task(sync_meeting_to_pipedrive, meeting.id)

    return {'status': 'ok'}


@router.get('/availability/', name='get-availability')
async def availability(admin_id: int, start_dt: datetime, end_dt: datetime, db: DBSession = Depends(get_db)):
    """
    Get available time slots for an admin between two datetimes.
    """
    admin = db.get(Admin, admin_id)
    if not admin:
        return JSONResponse({'status': 'error', 'message': 'Admin not found'}, status_code=404)

    slots = get_admin_available_slots(start_dt, end_dt, admin)
    return {'status': 'ok', 'slots': [slot async for slot in slots]}


@router.get('/support-link/generate/tc2/', name='generate-support-link')
async def generate_support_link(
    tc2_admin_id: int,
    tc2_cligency_id: int,
    authorization: Optional[str] = Header(None),
    db: DBSession = Depends(get_db),
):
    """
    Generate a support link for a company from within TC2.
    This link allows support staff to book meetings.
    """
    if get_bearer(authorization) != settings.tc2_api_key:
        return JSONResponse({'status': 'error', 'message': 'Unauthorized'}, status_code=403)

    # Get admin
    statement = select(Admin).where(Admin.tc2_admin_id == tc2_admin_id)
    admin = db.exec(statement).first()
    if not admin:
        return JSONResponse({'status': 'error', 'message': 'Admin not found'}, status_code=404)

    # Get or create company
    company = await get_or_create_company_from_tc2(tc2_cligency_id, db)
    if not company:  # pragma: no cover
        return JSONResponse({'status': 'error', 'message': 'Company not found'}, status_code=404)

    # Generate signed link
    expiry = datetime.now() + timedelta(days=settings.support_ttl_days)
    kwargs = {'admin_id': admin.id, 'company_id': company.id, 'e': int(expiry.timestamp())}
    sig = await sign_args(*kwargs.values())

    return {'link': f'{admin.call_booker_url}?{urlencode({"s": sig, **kwargs})}'}


@router.get('/support-link/validate/', name='validate-support-link')
async def validate_support_link(admin_id: int, company_id: int, e: int, s: str, db: DBSession = Depends(get_db)):
    """
    Validate a support link for a company from the website.
    Checks signature and expiry.
    """
    admin = db.get(Admin, admin_id)
    company = db.get(Company, company_id)

    if not admin or not company:
        return JSONResponse({'status': 'error', 'message': 'Admin or Company not found'}, status_code=404)

    kwargs = {'admin_id': admin.id, 'company_id': company.id, 'e': e}
    sig = await sign_args(*kwargs.values())

    if not compare_digest(sig, s):
        return JSONResponse({'status': 'error', 'message': 'Invalid signature'}, status_code=403)
    elif datetime.now().timestamp() > e:
        return JSONResponse({'status': 'error', 'message': 'Link has expired'}, status_code=403)

    return {'status': 'ok', 'company_name': company.name}
