import datetime
import logging

from pytz import utc

app_logger = logging.getLogger('tc2')


def _iso_8601_to_datetime(dt_str: str) -> datetime.datetime:
    # Removing the UTC timezone as `fromisoformat` doesn't support ISO 8601
    return datetime.datetime.fromisoformat(dt_str.rstrip('Z')).replace(tzinfo=utc)
