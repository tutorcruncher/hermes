from copy import copy
from datetime import date, datetime

import googleapiclient
import pytz
from dateutil.relativedelta import relativedelta

from app.callbooker._google import GoogleCalendar, logger

DATE_STRING_FORMAT = '%Y-%m-%d'
TIME_STRING_FORMAT = '%-I:%M %p'


def run_free_busy(email, data) -> dict:
    """
    Authenticates with google for the correct calendar then requests all the freebusy
    slots for the month sent in the url
    """
    google_cal = GoogleCalendar(email=email).create_builder()
    try:
        return google_cal.freebusy().query(body=data).execute()
    except googleapiclient.errors.HttpError as e:
        logger.info(e)
        return {}


def end_of_day_check(date_time, mins=0):
    if date_time.hour < 23:
        return date_time.replace(hour=date_time.hour + 1, minute=mins)
    else:
        try:
            return date_time.replace(day=date_time.day + 1, hour=0, minute=mins)
        except ValueError:
            return date_time.replace(day=1, month=date_time.month + 1, hour=0, minute=mins)


async def process_availablility(data: dict) -> dict:
    """
    Gets the unavailable times from Googles freebusy API then breaks them down
    against 10:00 - 17:00 to find the available slots to send back to TC.com
    """

    from_date_time = copy(data['timeMin'])
    to_date_time = copy(data['timeMax'])
    data['timeMin'] = f"{data['timeMin'].strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z"
    data['timeMax'] = f"{data['timeMax'].strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}Z"
    client_tz = data['timeZone']
    london_tz = pytz.timezone('Europe/London')
    now = datetime.now().astimezone(london_tz)

    email = data['items'][0]['id']
    freebusy = run_free_busy(email, data)
    freebusy_dict = {}
    for time_slot in freebusy['calendars'][email]['busy']:
        ts_start_str = time_slot['start']
        ts_end_str = time_slot['end']
        if ts_start_str.endswith('Z'):
            ts_start = datetime.strptime(ts_start_str, '%Y-%m-%dT%H:%M:%SZ').astimezone(london_tz)
            ts_end = datetime.strptime(ts_end_str, '%Y-%m-%dT%H:%M:%SZ').astimezone(london_tz)
        else:
            ts_start = (
                pytz.timezone(client_tz)
                .localize(datetime.strptime(ts_start_str[:-6], '%Y-%m-%dT%H:%M:%S'))
                .astimezone(london_tz)
            )
            ts_end = (
                pytz.timezone(client_tz)
                .localize(datetime.strptime(ts_end_str[:-6], '%Y-%m-%dT%H:%M:%S'))
                .astimezone(london_tz)
            )

        # Yeah this is a bit gross but keeps it clean around lunch and allows space around other busy periods
        if ts_start.hour == 13:
            ts_start = ts_start.replace(hour=13, minute=0)

        if ts_start.minute < 15:
            ts_start = ts_start.replace(hour=max(0, ts_start.hour - 1), minute=30)
        elif ts_start.minute < 45:
            ts_start = ts_start.replace(minute=0)
        else:
            ts_start = ts_start.replace(minute=30)

        if ts_end.minute <= 15:
            ts_end = ts_end.replace(minute=30)
        elif ts_end.minute <= 45:
            ts_end = end_of_day_check(ts_end)
        else:
            ts_end = end_of_day_check(ts_end, mins=30)

        while ts_start < ts_end:
            tzoned_time = ts_start.astimezone(pytz.timezone(client_tz))
            date_str = tzoned_time.strftime(DATE_STRING_FORMAT)
            time_str = tzoned_time.strftime(TIME_STRING_FORMAT)
            if freebusy_dict.get(date_str):
                freebusy_dict[date_str].append(time_str)
            else:
                freebusy_dict[date_str] = [time_str]
            ts_start += relativedelta(minutes=30)
    date_times = {}
    date_time = from_date_time.astimezone(london_tz)
    if date_time.hour < 10 or date_time.date() != date.today():
        date_time = now.replace(hour=10, minute=0)
    elif date_time.minute <= 30:
        date_time = date_time.replace(minute=30)
    else:
        date_time = end_of_day_check(date_time)

    while date_time.date() <= to_date_time.astimezone(london_tz).date():
        if date_time.hour < 10:
            date_time += relativedelta(minutes=30)
            continue
        elif date_time.hour > 17:
            date_time = (date_time + relativedelta(days=1)).replace(hour=10, minute=0)
            continue
        if date_time.weekday() in [5, 6]:
            date_time = (date_time + relativedelta(days=1)).replace(hour=10, minute=0)
            continue
        elif date_time.weekday() == 4:
            end_time = date_time.astimezone(london_tz).replace(hour=17)
        else:
            end_time = date_time.astimezone(london_tz).replace(hour=17, minute=30)

        while date_time < end_time:
            time_slot = date_time.astimezone(pytz.timezone(client_tz)).strftime(TIME_STRING_FORMAT)
            date_str = date_time.astimezone(pytz.timezone(client_tz)).strftime(DATE_STRING_FORMAT)
            if not freebusy_dict.get(date_str) or time_slot not in freebusy_dict.get(date_str):
                if date_times.get(date_str):
                    date_times[date_str].append(time_slot)
                else:
                    date_times[date_str] = [time_slot]
            date_time += relativedelta(minutes=30)
        date_time = (date_time + relativedelta(days=1)).replace(hour=10, minute=0)
    return date_times
