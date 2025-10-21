from datetime import datetime, timedelta
from typing import AsyncIterable

import pytz
from sqlmodel import select

from app.callbooker.google import AdminGoogleCalendar
from app.callbooker.utils import iso_8601_to_datetime
from app.core.database import get_session
from app.main_app.models import Admin, Config


def is_weekday(dt: datetime) -> bool:
    """Check if datetime is a weekday (not Saturday or Sunday)"""
    return dt.weekday() not in (5, 6)


async def get_day_start_ends(start: datetime, end: datetime, admin_tz: str) -> AsyncIterable[tuple[datetime, datetime]]:
    """
    For each day in the range, get the earliest and latest possible working hours
    as if they were in the admin's timezone. This allows us to accurately compare
    across ranges in DST changes.

    For example, if DST changes on 22nd Oct, we get:
    21st Oct 10:00 - 17:00 UTC (10:00 - 17:00 GMT)
    22nd Oct 09:00 - 16:00 UTC (10:00 - 17:00 GMT)
    23rd Oct 09:00 - 16:00 UTC (10:00 - 17:00 GMT)
    """
    db = get_session()
    config = db.exec(select(Config)).first()
    if not config:
        # Use defaults if no config exists
        config = Config()
    db.close()

    min_start_hours, min_start_mins = config.meeting_min_start.split(':')
    min_start_hours = int(min_start_hours)
    min_start_mins = int(min_start_mins)
    max_end_hours, max_end_mins = config.meeting_max_end.split(':')
    max_end_hours = int(max_end_hours)
    max_end_mins = int(max_end_mins)

    # Check the days either side of the dt range to catch where admins are in different timezones
    start = start - timedelta(days=1)
    end = end + timedelta(days=1)

    admin_tz = pytz.timezone(admin_tz)

    while start < end:
        admin_local_dt = start.astimezone(admin_tz)
        if not is_weekday(admin_local_dt):
            # Skip weekends
            start = start + timedelta(days=1)
            continue

        admin_local_start = admin_local_dt.replace(hour=min_start_hours, minute=min_start_mins, second=0, microsecond=0)
        admin_local_end = admin_local_dt.replace(hour=max_end_hours, minute=max_end_mins, second=0, microsecond=0)
        yield admin_local_start.astimezone(pytz.utc), admin_local_end.astimezone(pytz.utc)
        start = start + timedelta(days=1)


async def get_admin_available_slots(
    start: datetime, end: datetime, admin: Admin
) -> AsyncIterable[tuple[datetime, datetime]]:
    """
    Gets the unavailable times from Google's freebusy API then breaks them down
    against working hours (10:00 - 17:00) to find the available slots.

    We change everything into the admin's timezone and work with that.
    """
    db = get_session()
    config = db.exec(select(Config)).first()
    if not config:
        config = Config()
    db.close()

    # First we get all the 'busy' slots from Google
    g_cal = AdminGoogleCalendar(admin_email=admin.email)
    cal_data = g_cal.get_free_busy_slots(start, end)
    calendar_busy_slots = []
    for time_slot in cal_data['calendars'][admin.email]['busy']:
        _slot_start = iso_8601_to_datetime(time_slot['start'])
        _slot_end = iso_8601_to_datetime(time_slot['end'])
        calendar_busy_slots.append({'start': _slot_start, 'end': _slot_end})

    # Create day slots for the days in the range and loop through them to get free slots
    async for day_start, day_end in get_day_start_ends(start, end, admin.timezone):
        slot_start = day_start
        day_calendar_busy_slots = [s for s in calendar_busy_slots if s['start'] < day_end and s['end'] > day_start]
        while slot_start + timedelta(minutes=config.meeting_dur_mins) <= day_end:
            slot_end = slot_start + timedelta(minutes=config.meeting_dur_mins)

            # Check that the slot doesn't overlap with any busy slots
            is_overlapping = False
            for busy_slot in day_calendar_busy_slots:
                if (
                    busy_slot['start'] <= slot_start <= busy_slot['end']
                    or busy_slot['start'] <= slot_end <= busy_slot['end']
                    or (slot_start <= busy_slot['start'] and slot_end >= busy_slot['end'])
                ):
                    is_overlapping = True
                    break

            is_outside_range = slot_start < start or slot_end > end
            if not is_overlapping and not is_outside_range:
                yield slot_start, slot_end

            slot_start = slot_end + timedelta(minutes=config.meeting_buffer_mins)
