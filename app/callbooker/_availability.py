from datetime import datetime, timedelta
from typing import AsyncIterable

import pytz

from app.callbooker._google import AdminGoogleCalendar
from app.callbooker._utils import _iso_8601_to_datetime
from app.models import Admin
from app.utils import get_config


async def _get_day_start_ends(
    start: datetime, end: datetime, admin_tz: str
) -> AsyncIterable[tuple[datetime, datetime]]:
    """
    For each day in the range, we get the earliest and latest possible working hours as if they were in the admin's
    timezone. This allows us to accurately compare across ranges in DST etc.

    For example, if the DST changes on 22nd Oct, then we should get returned:

    21st Oct 10:00 - 17:00 UTC (10:00 - 17:00 GMT)
    22nd Oct 09:00 - 16:00 UTC (10:00 - 17:00 GMT)
    23rd Oct 09:00 - 16:00 UTC (10:00 - 17:00 GMT)
    """
    config = await get_config()

    date_start_ends = []
    min_start_hours, min_start_mins = config.meeting_min_start.split(':')
    min_start_hours = int(min_start_hours)
    min_start_mins = int(min_start_mins)
    max_end_hours, max_end_mins = config.meeting_max_end.split(':')
    max_end_hours = int(max_end_hours)
    max_end_mins = int(max_end_mins)

    # We need the check the days either side of the dt range to catch where admins are in different timezones
    start = start - timedelta(days=1)
    end = end + timedelta(days=1)

    admin_tz = pytz.timezone(admin_tz)

    while start < end:
        admin_local_dt = start.astimezone(admin_tz)
        admin_local_start = admin_local_dt.replace(hour=min_start_hours, minute=min_start_mins, second=0, microsecond=0)
        admin_local_end = admin_local_dt.replace(hour=max_end_hours, minute=max_end_mins, second=0, microsecond=0)
        date_start_ends.append((admin_local_start.astimezone(pytz.utc), admin_local_end.astimezone(pytz.utc)))
        yield admin_local_start.astimezone(pytz.utc), admin_local_end.astimezone(pytz.utc)
        start = start + timedelta(days=1)


async def get_admin_available_slots(
    start: datetime, end: datetime, admin: Admin
) -> AsyncIterable[tuple[datetime, datetime]]:
    """
    Gets the unavailable times from Googles freebusy API then breaks them down
    against 10:00 - 17:00 to find the available slots to send back to TC.com

    We change everything into the admins timezone and work with that.
    """
    # First we get all the "busy" slots from Google
    g_cal = AdminGoogleCalendar(admin_email=admin.email)
    cal_data = g_cal.get_free_busy_slots(start, end)
    calendar_busy_slots = []
    for time_slot in cal_data['calendars'][admin.email]['busy']:
        _slot_start = _iso_8601_to_datetime(time_slot['start'])
        _slot_end = _iso_8601_to_datetime(time_slot['end'])
        calendar_busy_slots.append({'start': _slot_start, 'end': _slot_end})
    # First we create the day slots for the days in the range and loop through them to get the free slots.
    config = await get_config()
    async for day_start, day_end in _get_day_start_ends(start, end, admin.timezone):
        slot_start = day_start
        day_calendar_busy_slots = [s for s in calendar_busy_slots if s['start'] >= day_start and s['end'] <= day_end]
        while slot_start + timedelta(minutes=config.meeting_dur_mins + config.meeting_buffer_mins) <= day_end:
            slot_end = slot_start + timedelta(minutes=config.meeting_dur_mins)
            # We check that the slot is not overlapping with any of the busy slots. Either the start or end of the slot
            # is within the busy slot, or the busy slot is within the slot.
            is_overlapping = next(
                (
                    b
                    for b in day_calendar_busy_slots
                    if b['start'] <= slot_start <= b['end']
                    or b['start'] <= slot_end <= b['end']
                    or (slot_start <= b['start'] and slot_end >= b['end'])
                ),
                None,
            )
            is_outside_range = slot_start < start or slot_end > end
            if not is_overlapping and not is_outside_range:
                # Since we need to get the day starts and end of a bigger range, we need to exclude those slots here.
                yield slot_start, slot_end
            slot_start = slot_end + timedelta(minutes=config.meeting_buffer_mins)
