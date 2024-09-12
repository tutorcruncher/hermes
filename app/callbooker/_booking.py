from datetime import datetime, timedelta, timezone

from app.callbooker._google import AdminGoogleCalendar
from app.callbooker._meeting_content_templates import MEETING_CONTENT_TEMPLATES
from app.callbooker._utils import _iso_8601_to_datetime, app_logger
from app.models import Meeting


async def check_gcal_open_slots(meeting_start: datetime, meeting_end: datetime, admin_email: str) -> bool:
    """
    Queries Google to for all busy slots for the admin and checks if the start time is in one of them.
    """
    # Everything uses UTC
    assert meeting_start.tzinfo == timezone.utc
    g_cal = AdminGoogleCalendar(admin_email=admin_email)
    cal_data = g_cal.get_free_busy_slots(meeting_start, (meeting_start + timedelta(days=1)))
    for time_slot in cal_data['calendars'][admin_email]['busy']:
        _slot_start = _iso_8601_to_datetime(time_slot['start'])
        _slot_end = _iso_8601_to_datetime(time_slot['end'])
        if _slot_start <= meeting_start <= _slot_end or _slot_start <= meeting_end <= _slot_end:
            app_logger.info('Tried to book meeting with %s for slot %s - %s', admin_email, _slot_start, _slot_end)
            return False
    return True


async def create_meeting_gcal_event(meeting: Meeting):
    """
    A job to create a meeting event in the admin/contact's Google Calendar.
    If the meeting is a sales meeting, then we check PipeDrive to see if they exist already. That way, we can include
    the link to their profile for the Admin.
    If the meeting is a support meeting, then we include a link to their TC meta profile.
    """
    contact = await meeting.contact
    company = await contact.company
    admin = await meeting.admin

    meeting_templ_vars = {
        'contact_first_name': contact.first_name or 'there',
        'company_name': company.name,
        'tc2_cligency_id': '',
        'tc2_cligency_url': '',
        'admin_name': admin.first_name,
    }

    if company.tc2_cligency_id:
        meeting_templ_vars.update(tc2_cligency_id=company.tc2_cligency_id, tc2_cligency_url=company.tc2_cligency_url)

    if meeting.meeting_type == Meeting.TYPE_SALES:
        meeting_templ_vars.update(
            {
                'crm_url': f'https://app.pipedrive.com/organization/{company.pd_org_id}' if company.pd_org_id else '',
                'company_name': company.name or '',
                'contact_email': contact.email or '',
                'contact_phone': contact.phone or '',
                'company_estimated_monthly_revenue': company.estimated_income or '',
                'company_country': company.country or '',
            }
        )

    meeting_template = MEETING_CONTENT_TEMPLATES[meeting.meeting_type]
    g_cal = AdminGoogleCalendar(admin_email=admin.email)
    g_cal.create_cal_event(
        description=meeting_template.format(**meeting_templ_vars),
        summary=meeting.name,
        contact_email=contact.email,
        start=meeting.start_time,
        end=meeting.end_time,
    )
    app_logger.info('Created Google Calendar event for %s', meeting, extra=meeting.__dict__)
